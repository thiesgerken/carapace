from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from carapace.database.models import User
from carapace.jobs import JobsStore
from carapace.memory.models import (
    DependencySummary,
    MemoryTask,
    ModelRole,
    SessionMemoryFilter,
    TaskEstimate,
    TaskFilter,
    TaskKind,
    TaskOutcome,
    TaskRunRequest,
    TaskSelection,
    TaskSort,
    TaskSpawnRequest,
    TaskStatus,
)
from carapace.memory.service import MemoryService, ModelOverrideError
from carapace.memory.store import MemoryStore
from carapace.models.config import Config
from carapace.models.user import UserConfig
from carapace.session import SessionManager

NOW = datetime(2026, 9, 21, 12, tzinfo=UTC)
OVERRIDE = "anthropic:claude-sonnet-4-6"  # in the default catalog, but not the memory roles' default


class FakeHandler:
    def __init__(self, kind: TaskKind, role: ModelRole) -> None:
        self.kind = kind
        self.model_role = role

    async def estimate(self, user: str, target: str, model: str) -> TaskEstimate:
        if target == "broken":
            raise ValueError("cannot prepare the input")
        cost = Decimal("0.02") if model == OVERRIDE else Decimal("0.01")
        return TaskEstimate(model=model, input_tokens=100, output_tokens_cap=10, cost_usd=cost)

    async def run(self, task: MemoryTask, model: str | None) -> TaskOutcome:
        raise AssertionError("not run in these tests")


@pytest.fixture
def setup(db_factory, tmp_path):
    with db_factory.begin() as db:
        for name in ("alice", "bob"):
            db.add(
                User(
                    username=name,
                    password_hash="x",
                    config=UserConfig(),
                    created_at=NOW,
                    updated_at=NOW,
                    password_changed_at=NOW,
                )
            )
    sessions = SessionManager(db_factory, tmp_path)
    service = MemoryService(
        current_config=Config,
        store=MemoryStore(db_factory),
        sessions=sessions,
        jobs=JobsStore(db_factory),
        handlers={
            TaskKind.session_extract: FakeHandler(TaskKind.session_extract, ModelRole.memory_low),  # type: ignore[dict-item]
            TaskKind.week_digest: FakeHandler(TaskKind.week_digest, ModelRole.memory_high),  # type: ignore[dict-item]
        },
        user_config_for=lambda _: UserConfig(),
        users=lambda: ["alice", "bob"],
        is_agent_running=lambda _: False,
        clock=lambda: NOW,
    )
    return service, sessions


def _session(sessions: SessionManager, user: str = "alice", *, private: bool = False, title: str | None = None) -> str:
    state = sessions.create_session("web", user=user, private=private)
    state.title = title
    state.last_active = NOW - timedelta(days=1)
    sessions.save_state(state)
    sessions.append_events(
        state.session_id, [{"role": "user", "content": "hi", "timestamp": "2026-09-14T09:00:00+00:00"}]
    )
    return state.session_id


async def test_manual_spawn_reports_skips(setup):
    service, sessions = setup
    ok = _session(sessions, title="Weekend trip")
    private = _session(sessions, private=True)
    bobs = _session(sessions, user="bob")

    response = await service.spawn_tasks(
        "alice", TaskSpawnRequest(kind=TaskKind.session_extract, targets=[ok, private, bobs, "missing"])
    )
    assert len(response.task_ids) == 1
    assert {s.target: s.reason for s in response.skipped} == {
        private: "private",
        bobs: "not_found",
        "missing": "not_found",
    }

    again = await service.spawn_tasks("alice", TaskSpawnRequest(kind=TaskKind.session_extract, targets=[ok]))
    assert again.task_ids == response.task_ids  # a pending task is replaced in place

    [view] = (await service.list_tasks("alice", TaskFilter(), TaskSort.activity, None, 10)).items
    assert (view.target_label, view.week_key, view.spawned_by) == ("Weekend trip", "2026-W38", "manual")
    assert view.dependencies is None


async def test_manual_digest_spawn_validates_the_period(setup):
    service, _ = setup
    response = await service.spawn_tasks(
        "alice", TaskSpawnRequest(kind=TaskKind.week_digest, targets=["2026-W38", "2025-W53"])
    )
    assert len(response.task_ids) == 1
    assert [(s.target, s.reason) for s in response.skipped] == [("2025-W53", "invalid_period")]
    [digest] = (await service.list_tasks("alice", TaskFilter(), TaskSort.activity, None, 10)).items
    assert digest.dependencies == DependencySummary(waiting=0, pending_ids=[], failed=0)
    no_handler = await service.spawn_tasks("alice", TaskSpawnRequest(kind=TaskKind.month_digest, targets=["2026-09"]))
    assert [s.reason for s in no_handler.skipped] == ["no_handler"]


async def test_estimate_run_and_status(setup):
    service, sessions = setup
    ids = (
        await service.spawn_tasks(
            "alice", TaskSpawnRequest(kind=TaskKind.session_extract, targets=[_session(sessions), _session(sessions)])
        )
    ).task_ids
    selection = TaskSelection(ids=ids)

    estimate = await service.estimate_tasks("alice", TaskRunRequest(selection=selection))
    assert (estimate.task_count, estimate.cost_usd, estimate.missing_dependencies) == (2, Decimal("0.02"), 0)
    override = await service.estimate_tasks("alice", TaskRunRequest(selection=selection, model_override=OVERRIDE))
    assert override.cost_usd == Decimal("0.04")

    assert (await service.run_tasks("alice", TaskRunRequest(selection=selection))).count == 2
    status = await service.status("alice")
    assert status.queue[TaskStatus.queued] == 2 and status.queue[TaskStatus.pending] == 0
    assert status.models.memory_low == Config().agent.sentinel_model
    assert status.sessions_without_transcript == 0

    listing = await service.list_tasks("alice", TaskFilter(status=[TaskStatus.queued]), TaskSort.activity, None, 10)
    assert (listing.total, listing.estimate.cost_usd) == (2, Decimal("0.02"))
    assert (await service.cancel_tasks("alice", selection)).count == 2


async def test_runs_cover_failed_tasks_and_estimate_them_afresh(setup):
    service, sessions = setup
    store: MemoryStore = service._store
    spawn = TaskSpawnRequest(kind=TaskKind.session_extract, targets=[_session(sessions), _session(sessions)])
    _, cancelled = (await service.spawn_tasks("alice", spawn)).task_ids
    await service.cancel_tasks("alice", TaskSelection(ids=[cancelled]))
    # Spawn failures carry no estimate: one can be estimated now, the other still cannot be prepared.
    store.record_spawn_failure("alice", TaskKind.session_extract, _session(sessions), "fixed since", NOW)
    store.record_spawn_failure("alice", TaskKind.session_extract, "broken", "still broken", NOW)
    run = TaskRunRequest(selection=TaskSelection(filter=TaskFilter()))

    estimate = await service.estimate_tasks("alice", run)
    assert (estimate.task_count, estimate.cost_usd, estimate.unestimated) == (2, Decimal("0.02"), 1)
    assert (await service.run_tasks("alice", run)).count == 3
    status = await service.status("alice")
    assert (status.queue[TaskStatus.queued], status.queue[TaskStatus.failed]) == (3, 0)


async def test_spawn_by_filter_uses_the_session_query_and_eligibility(setup):
    service, sessions = setup
    first, second = _session(sessions), _session(sessions)
    _session(sessions, private=True)  # never listed, so never spawned
    _session(sessions, user="bob")

    response = await service.spawn_tasks(
        "alice", TaskSpawnRequest(kind=TaskKind.session_extract, filter=SessionMemoryFilter())
    )
    tasks = (await service.list_tasks("alice", TaskFilter(), TaskSort.activity, None, 10)).items
    assert {t.target for t in tasks} == {first, second}
    assert len(response.task_ids) == 2 and response.skipped == []

    # Respawning the same selection replaces the pending tasks in place.
    again = await service.spawn_tasks(
        "alice", TaskSpawnRequest(kind=TaskKind.session_extract, filter=SessionMemoryFilter())
    )
    assert sorted(again.task_ids) == sorted(response.task_ids)


async def test_unregistered_model_overrides_are_rejected_up_front(setup):
    service, sessions = setup
    session = _session(sessions)
    spawn = TaskSpawnRequest(kind=TaskKind.session_extract, targets=[session], model_override="m:unknown")
    with pytest.raises(ModelOverrideError, match="not registered"):
        await service.spawn_tasks("alice", spawn)

    ids = (
        await service.spawn_tasks("alice", TaskSpawnRequest(kind=TaskKind.session_extract, targets=[session]))
    ).task_ids
    run = TaskRunRequest(selection=TaskSelection(ids=ids), model_override="m:unknown")
    for call in (service.estimate_tasks, service.run_tasks):
        with pytest.raises(ModelOverrideError):
            await call("alice", run)
    assert (await service.status("alice")).queue[TaskStatus.pending] == 1
