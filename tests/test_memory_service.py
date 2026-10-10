from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from carapace.database.models import User
from carapace.jobs import JobsStore
from carapace.memory.models import (
    MemoryTask,
    ModelRole,
    TaskEstimate,
    TaskFilter,
    TaskKind,
    TaskOutcome,
    TaskRunRequest,
    TaskSelection,
    TaskSpawnRequest,
    TaskStatus,
)
from carapace.memory.service import MemoryService
from carapace.models.config import Config
from carapace.models.user import UserConfig
from carapace.session import SessionManager

NOW = datetime(2026, 9, 21, 12, tzinfo=UTC)


class FakeHandler:
    def __init__(self, kind: TaskKind, role: ModelRole) -> None:
        self.kind = kind
        self.model_role = role

    async def estimate(self, user: str, target: str, model: str) -> TaskEstimate:
        cost = Decimal("0.02") if model.endswith("override") else Decimal("0.01")
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
        config=Config(),
        session_factory=db_factory,
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

    [view] = (await service.list_tasks("alice", TaskFilter(), None, 10)).items
    assert (view.target_label, view.week_key, view.spawned_by) == ("Weekend trip", "2026-W38", "manual")


async def test_manual_digest_spawn_validates_the_period(setup):
    service, _ = setup
    response = await service.spawn_tasks(
        "alice", TaskSpawnRequest(kind=TaskKind.week_digest, targets=["2026-W38", "2025-W53"])
    )
    assert len(response.task_ids) == 1
    assert [(s.target, s.reason) for s in response.skipped] == [("2025-W53", "invalid_period")]
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
    assert (estimate.task_count, estimate.cost_usd) == (2, Decimal("0.02"))
    override = await service.estimate_tasks("alice", TaskRunRequest(selection=selection, model_override="m-override"))
    assert override.cost_usd == Decimal("0.04")

    assert (await service.run_tasks("alice", TaskRunRequest(selection=selection))).count == 2
    status = await service.status("alice")
    assert status.queue[TaskStatus.queued] == 2 and status.queue[TaskStatus.pending] == 0
    assert status.models.memory_low == Config().agent.title_model
    assert status.sessions_without_transcript == 0

    listing = await service.list_tasks("alice", TaskFilter(status=[TaskStatus.queued]), None, 10)
    assert (listing.total, listing.estimate.cost_usd) == (2, Decimal("0.02"))
    assert (await service.cancel_tasks("alice", selection)).count == 2


async def test_spawn_by_filter_is_not_available_yet(setup):
    service, _ = setup
    with pytest.raises(NotImplementedError):
        await service.spawn_tasks("alice", TaskSpawnRequest(kind=TaskKind.session_extract, filter={}))
