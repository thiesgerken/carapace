from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from carapace.database.models import User
from carapace.jobs import JobsStore
from carapace.memory.coverage import coverage_hash, week_coverage
from carapace.memory.input import INPUT_FORMAT_VERSION, render_extraction_input
from carapace.memory.models import (
    CoverageEntry,
    DigestLevel,
    DigestResult,
    ExtractionResult,
    Ineligible,
    MemoryTask,
    ModelRole,
    PeriodDigest,
    Provenance,
    SessionExtraction,
    SpawnedBy,
    TaskEstimate,
    TaskFilter,
    TaskKind,
    TaskOutcome,
    TaskSelection,
    TaskStatus,
)
from carapace.memory.spawner import Spawner
from carapace.memory.store import MemoryStore
from carapace.models.config import Config
from carapace.models.jobs import JobDefinition
from carapace.models.session import SessionJobRunContext, SessionState
from carapace.models.user import UserConfig
from carapace.session import SessionManager

NOW = datetime(2026, 9, 21, 12, tzinfo=UTC)  # Monday of 2026-W39
LONG_AGO = NOW - timedelta(days=10)


class FakeHandler:
    def __init__(self, kind: TaskKind, role: ModelRole) -> None:
        self.kind = kind
        self.model_role = role
        self.estimated: list[tuple[str, str, str]] = []
        self.fail_estimate: Exception | None = None

    async def estimate(self, user: str, target: str, model: str) -> TaskEstimate:
        if self.fail_estimate is not None:
            raise self.fail_estimate
        self.estimated.append((user, target, model))
        return TaskEstimate(model=model, input_tokens=100, output_tokens_cap=10, cost_usd=Decimal("0.001"))

    async def run(self, task: MemoryTask, model: str | None) -> TaskOutcome:
        raise AssertionError("the spawner never runs tasks")


class Env:
    def __init__(self, db_factory, tmp_path) -> None:
        with db_factory.begin() as db:
            db.add(
                User(
                    username="alice",
                    password_hash="x",
                    config=UserConfig(),
                    created_at=NOW,
                    updated_at=NOW,
                    password_changed_at=NOW,
                )
            )
        self.store = MemoryStore(db_factory)
        self.sessions = SessionManager(db_factory, tmp_path)
        self.jobs = JobsStore(db_factory)
        self.user_config = UserConfig(timezone="Europe/Berlin")
        self.running: set[str] = set()
        self.changed: list[str] = []
        self.handlers: dict[TaskKind, FakeHandler] = {
            TaskKind.session_extract: FakeHandler(TaskKind.session_extract, ModelRole.memory_low)
        }
        self.spawner = Spawner(
            store=self.store,
            sessions=self.sessions,
            jobs=self.jobs,
            handlers=self.handlers,  # type: ignore[arg-type]
            config=Config(),
            user_config_for=lambda _: self.user_config,
            users=lambda: ["alice"],
            is_agent_running=lambda session_id: session_id in self.running,
            on_records_changed=lambda user, now: self.changed.append(user),
        )

    def session(
        self,
        events: list[dict[str, Any]] | None = None,
        *,
        last_active: datetime = LONG_AGO,
        archived: bool = False,
        channel_type: str = "web",
        job_id: str | None = None,
    ) -> SessionState:
        state = self.sessions.create_session(channel_type, user="alice")
        state.last_active = last_active
        state.attributes.archived = archived
        if job_id is not None:
            state.latest_job_run = SessionJobRunContext(job_id=job_id, trigger_kind="cron", triggered_at=LONG_AGO)
        self.sessions.save_state(state)
        if events is None:
            # Sunday evening in Berlin, Sunday afternoon UTC: week 2026-W37 either way.
            events = [{"role": "user", "content": "hello", "timestamp": "2026-09-13T15:00:00+00:00"}]
        if events:
            self.sessions.append_events(state.session_id, events)
        return state

    def tasks(self, kind: TaskKind = TaskKind.session_extract) -> list[MemoryTask]:
        return self.store.list_tasks("alice", TaskFilter(kind=[kind]), None, 100).items

    def extract(
        self,
        session_id: str,
        *,
        input_hash: str,
        week: str = "2026-W37",
        format_version: int = INPUT_FORMAT_VERSION,
        at: datetime = LONG_AGO,
    ) -> None:
        """Simulate a finished extraction of the session."""
        task = self.store.spawn(
            "alice",
            TaskKind.session_extract,
            session_id,
            spawned_by=SpawnedBy.manual,
            now=at,
            session_week_key=week,
            estimate=TaskEstimate(model="m", input_tokens=1, output_tokens_cap=1, cost_usd=None),
        )
        assert task is not None
        self.store.run("alice", TaskSelection(ids=[task.id]), None, at)
        assert self.store.claim(task.id, at)
        provenance = Provenance(
            carapace_version="0",
            model="m",
            prompt_version="p",
            input_format_version=format_version,
            input_hash=input_hash,
            input_tokens=1,
            output_tokens=1,
            cost_usd=None,
            duration_ms=1,
            task_id=task.id,
            created_at=at,
        )
        extraction = SessionExtraction(
            abstract="a", outcomes=[], open_loops=[], on_my_mind=[], facts=[], friction=[], tags=[]
        )
        result = ExtractionResult(session_id=session_id, week_key=week, month_key="2026-09", extraction=extraction)
        assert self.store.record_outcome(task.id, TaskOutcome(provenance=provenance, result=result), at)


@pytest.fixture
def env(db_factory, tmp_path) -> Env:
    return Env(db_factory, tmp_path)


async def test_spawns_settled_session_with_week_and_estimate(env: Env):
    state = env.session()
    await env.spawner.sweep(NOW)

    [task] = env.tasks()
    assert (task.target, task.status, task.week_key, task.month_key) == (
        state.session_id,
        TaskStatus.pending,
        "2026-W37",
        "2026-09",
    )
    assert task.estimate is not None and task.estimate.model == Config().agent.title_model
    # A second sweep finds the open task and leaves it alone.
    await env.spawner.sweep(NOW)
    assert len(env.tasks()) == 1


async def test_week_follows_the_user_timezone(env: Env):
    # 23:30 UTC on Sunday is Monday in Berlin: the next ISO week.
    env.session([{"role": "user", "content": "late", "timestamp": "2026-09-13T23:30:00+00:00"}])
    await env.spawner.sweep(NOW)
    assert env.tasks()[0].week_key == "2026-W38"


async def test_skips_active_and_ineligible_sessions(env: Env):
    env.session(last_active=NOW - timedelta(minutes=5))  # still active
    archived = env.session(last_active=NOW - timedelta(minutes=5), archived=True)
    running = env.session()
    env.running.add(running.session_id)
    env.session(channel_type="job", job_id="nightly")  # job did not opt in
    env.session([{"role": "assistant", "content": "no user here", "timestamp": "2026-09-13T15:00:00+00:00"}])
    legacy = env.session([])

    await env.spawner.sweep(NOW)

    assert [t.target for t in env.tasks()] == [archived.session_id]
    assert env.spawner.sessions_without_transcript == {"alice": 1}
    assert env.spawner.quick_ineligibility(legacy) is None


async def test_job_sessions_need_the_job_opt_in(env: Env):
    env.jobs.create_job(JobDefinition(user="alice", id="nightly", name="Nightly", prompt="p", memory_enabled=True))
    state = env.session(channel_type="job", job_id="nightly")
    await env.spawner.sweep(NOW)
    assert [t.target for t in env.tasks()] == [state.session_id]


async def test_respawns_only_on_changed_input(env: Env):
    state = env.session()
    events = env.sessions.load_events(state.session_id)
    env.extract(state.session_id, input_hash=render_extraction_input(events).input_hash)

    await env.spawner.sweep(NOW)
    assert [t.status for t in env.tasks()] == [TaskStatus.done]

    # The session continued: new input, new task.
    env.sessions.append_events(state.session_id, [{"role": "assistant", "content": "more"}])
    state.last_active = NOW - timedelta(days=1)
    env.sessions.save_state(state)
    await env.spawner.sweep(NOW)
    assert sorted(t.status for t in env.tasks()) == [TaskStatus.done, TaskStatus.pending]


async def test_format_bump_marks_outdated_instead_of_respawning(env: Env):
    state = env.session()
    env.extract(state.session_id, input_hash="from-old-format", format_version=INPUT_FORMAT_VERSION - 1)
    state.last_active = NOW - timedelta(days=1)  # touched after the extraction
    env.sessions.save_state(state)
    await env.spawner.sweep(NOW)
    assert [t.status for t in env.tasks()] == [TaskStatus.done]


async def test_private_session_is_purged(env: Env):
    extracted = env.session()
    env.extract(extracted.session_id, input_hash="h")
    pending = env.session()
    await env.spawner.sweep(NOW)
    assert any(t.target == pending.session_id and t.status is TaskStatus.pending for t in env.tasks())

    for state in (extracted, pending):
        state.attributes.private = True
        env.sessions.save_state(state)
    await env.spawner.sweep(NOW)

    assert env.store.current_extraction("alice", extracted.session_id) is None
    assert {t.target: t.status for t in env.tasks()}[pending.session_id] is TaskStatus.cancelled
    assert env.changed == ["alice"]


async def test_malformed_transcript_fails_only_that_session(env: Env):
    broken = env.session([{"role": "user", "content": "hi", "timestamp": "not-a-date"}])
    fine = env.session()

    await env.spawner.sweep(NOW)
    by_target = {t.target: t for t in env.tasks()}
    assert by_target[fine.session_id].status is TaskStatus.pending
    failed = by_target[broken.session_id]
    assert failed.status is TaskStatus.failed and failed.error is not None and "ValueError" in failed.error

    # Unchanged input is not retried by the sweep; the user retries from the Tasks tab.
    await env.spawner.sweep(NOW + timedelta(minutes=5))
    assert len(env.tasks()) == 2


async def test_unexpected_errors_fail_the_sweep(env: Env):
    env.session()
    env.handlers[TaskKind.session_extract].fail_estimate = RuntimeError("provider catalog broken")
    with pytest.raises(RuntimeError, match="catalog"):
        await env.spawner.sweep(NOW)


async def test_recheck_before_running(env: Env):
    state = env.session()
    env.extract(state.session_id, input_hash="h")
    task = env.tasks()[0]
    assert env.spawner.recheck(task, NOW) is None

    env.running.add(state.session_id)
    assert env.spawner.recheck(task, NOW) is Ineligible.agent_running
    env.running.clear()

    state.attributes.private = True
    env.sessions.save_state(state)
    assert env.spawner.recheck(task, NOW) is Ineligible.private
    assert env.store.current_extraction("alice", state.session_id) is None
    assert env.changed == ["alice"]

    env.sessions.delete_session(state.session_id)
    assert env.spawner.recheck(task, NOW) is Ineligible.deleted


async def test_week_digest_waits_for_ended_settled_weeks(env: Env):
    env.handlers[TaskKind.week_digest] = FakeHandler(TaskKind.week_digest, ModelRole.memory_high)
    done = env.session()
    env.extract(done.session_id, input_hash="h")
    env.session([{"role": "user", "content": "this week", "timestamp": "2026-09-21T08:00:00+00:00"}])

    await env.spawner.sweep(NOW)
    # W37 has ended and is settled; W39 (this week) has not ended.
    [digest] = env.tasks(TaskKind.week_digest)
    assert (digest.target, digest.month_key) == ("2026-W37", "2026-09")
    assert digest.estimate is not None and digest.estimate.model == Config().agent.model


async def test_week_digest_not_spawned_while_week_has_open_extractions(env: Env):
    env.handlers[TaskKind.week_digest] = FakeHandler(TaskKind.week_digest, ModelRole.memory_high)
    done = env.session()
    env.extract(done.session_id, input_hash="h")
    env.session()  # same week, still to be extracted
    await env.spawner.sweep(NOW)
    assert env.tasks(TaskKind.week_digest) == []


async def test_week_digest_respawns_only_when_coverage_changes(env: Env):
    env.handlers[TaskKind.week_digest] = FakeHandler(TaskKind.week_digest, ModelRole.memory_high)
    done = env.session()
    env.extract(done.session_id, input_hash="h")
    sources = env.store.current_extractions("alice", "2026-W37")
    digest_task = env.store.spawn(
        "alice",
        TaskKind.week_digest,
        "2026-W37",
        spawned_by=SpawnedBy.auto,
        now=LONG_AGO,
        estimate=TaskEstimate(model="m", input_tokens=1, output_tokens_cap=1, cost_usd=None),
    )
    assert digest_task is not None
    env.store.run("alice", TaskSelection(ids=[digest_task.id]), None, LONG_AGO)
    env.store.claim(digest_task.id, LONG_AGO)
    coverage = week_coverage(sources)
    result = DigestResult(
        level=DigestLevel.week,
        period_key="2026-W37",
        coverage=coverage,
        coverage_hash=coverage_hash(coverage),
        digest=PeriodDigest(summary="s", on_my_mind=[], highlights=[], open_loops=[], learned=[]),
    )
    provenance = Provenance(
        carapace_version="0",
        model="m",
        prompt_version="p",
        input_format_version=1,
        input_hash="i",
        input_tokens=1,
        output_tokens=1,
        cost_usd=None,
        duration_ms=1,
        task_id=digest_task.id,
        created_at=LONG_AGO,
    )
    env.store.record_outcome(digest_task.id, TaskOutcome(provenance=provenance, result=result), LONG_AGO)

    await env.spawner.sweep(NOW)
    assert [t.status for t in env.tasks(TaskKind.week_digest)] == [TaskStatus.done]

    # A re-extraction is a new source record: the digest is stale.
    env.extract(done.session_id, input_hash="h2", at=NOW - timedelta(days=1))
    await env.spawner.sweep(NOW)
    assert sorted(t.status for t in env.tasks(TaskKind.week_digest)) == [TaskStatus.done, TaskStatus.pending]
    assert coverage != week_coverage(env.store.current_extractions("alice", "2026-W37"))
    assert CoverageEntry(source_id=done.session_id, source_hash=str(sources[0].id)) in coverage


async def test_digests_need_their_handler(env: Env):
    done = env.session()
    env.extract(done.session_id, input_hash="h")
    await env.spawner.sweep(NOW)
    assert env.tasks(TaskKind.week_digest) == []


async def test_deleted_session_triggers_a_mirror(env: Env):
    state = env.session()
    env.extract(state.session_id, input_hash="h")
    await env.spawner.sweep(NOW)
    assert env.changed == []
    env.sessions.delete_session(state.session_id)
    await env.spawner.sweep(NOW)
    assert env.changed == ["alice"]


async def test_pending_task_is_refreshed_when_the_session_continues(env: Env):
    state = env.session()
    await env.spawner.sweep(NOW)
    [pending] = env.tasks()
    handler = env.handlers[TaskKind.session_extract]
    assert len(handler.estimated) == 1

    # Continued after the spawn, then idle long enough to settle again.
    env.sessions.append_events(state.session_id, [{"role": "assistant", "content": "more"}])
    state.last_active = NOW + timedelta(hours=1)
    env.sessions.save_state(state)
    later = NOW + timedelta(days=1)
    await env.spawner.sweep(later)

    [refreshed] = env.tasks()
    assert refreshed.id == pending.id and refreshed.created_at == later
    assert len(handler.estimated) == 2


async def test_queued_task_is_not_replaced(env: Env):
    state = env.session()
    await env.spawner.sweep(NOW)
    [task] = env.tasks()
    env.store.run("alice", TaskSelection(ids=[task.id]), None, NOW)

    env.sessions.append_events(state.session_id, [{"role": "assistant", "content": "more"}])
    state.last_active = NOW + timedelta(hours=1)
    env.sessions.save_state(state)
    await env.spawner.sweep(NOW + timedelta(days=1))
    assert [(t.id, t.status) for t in env.tasks()] == [(task.id, TaskStatus.queued)]
    assert len(env.handlers[TaskKind.session_extract].estimated) == 1
