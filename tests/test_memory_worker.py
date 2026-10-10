from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from carapace.database.models import SessionRow, User
from carapace.memory.handlers import TaskRunError
from carapace.memory.models import (
    BlockedReason,
    ExtractionResult,
    Ineligible,
    MemoryTask,
    MirrorResult,
    ModelRole,
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
from carapace.memory.store import MemoryStore
from carapace.memory.worker import MemoryWorker, WorkerTiming
from carapace.models.config import Config
from carapace.models.user import MemoryBudget, UserConfig, UserMemoryConfig

NOW = datetime(2026, 9, 21, 12, tzinfo=UTC)


def _provenance(task: MemoryTask, model: str, cost: str) -> Provenance:
    return Provenance(
        carapace_version="0",
        model=model,
        prompt_version="p",
        input_format_version=1,
        input_hash="h",
        input_tokens=100,
        output_tokens=10,
        cost_usd=Decimal(cost),
        duration_ms=1,
        task_id=task.id,
        created_at=NOW,
    )


class ExtractHandler:
    kind = TaskKind.session_extract
    model_role = ModelRole.memory_low

    def __init__(self) -> None:
        self.cost = Decimal("0.60")
        self.runs: list[tuple[str, str | None]] = []
        self.fail: Exception | None = None
        self.block: asyncio.Event | None = None

    async def estimate(self, user: str, target: str, model: str) -> TaskEstimate:
        return TaskEstimate(model=model, input_tokens=100, output_tokens_cap=10, cost_usd=self.cost)

    async def run(self, task: MemoryTask, model: str | None) -> TaskOutcome:
        self.runs.append((task.target, model))
        if self.block is not None:
            await self.block.wait()
        if self.fail is not None:
            raise self.fail
        assert model is not None
        extraction = SessionExtraction(
            abstract="a", outcomes=[], open_loops=[], on_my_mind=[], facts=[], friction=[], tags=[]
        )
        result = ExtractionResult(
            session_id=task.target, week_key="2026-W37", month_key="2026-09", extraction=extraction
        )
        return TaskOutcome(provenance=_provenance(task, model, "0.50"), result=result)


class MirrorHandler:
    kind = TaskKind.mirror
    model_role = None

    def __init__(self) -> None:
        self.runs = 0

    async def estimate(self, user: str, target: str, model: str) -> TaskEstimate:
        raise AssertionError("mirrors are never estimated")

    async def run(self, task: MemoryTask, model: str | None) -> TaskOutcome:
        assert model is None
        self.runs += 1
        return TaskOutcome(provenance=None, result=MirrorResult(commit="abc"))


class Env:
    def __init__(self, db_factory) -> None:
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
            db.flush()
            for session_id in ("s1", "s2", "s3"):
                db.add(
                    SessionRow(session_id=session_id, user="alice", channel_type="web", created_at=NOW, last_active=NOW)
                )
        self.store = MemoryStore(db_factory)
        self.now = NOW
        self.user_config = UserConfig(memory=UserMemoryConfig(budget=MemoryBudget(cost_usd_per_day=Decimal("1.00"))))
        self.extract = ExtractHandler()
        self.mirror = MirrorHandler()
        self.ineligible: dict[str, Ineligible] = {}
        self.sweeps = 0
        self.worker = MemoryWorker(
            store=self.store,
            handlers={TaskKind.session_extract: self.extract, TaskKind.mirror: self.mirror},  # type: ignore[dict-item]
            config=Config(),
            user_config_for=lambda _: self.user_config,
            users=lambda: ["alice"],
            sweep=self._sweep,
            recheck_session=lambda task, now: self.ineligible.get(task.target),
            max_parallel=4,
            timing=WorkerTiming(mirror_debounce=timedelta(minutes=2)),
            clock=lambda: self.now,
        )

    async def _sweep(self, now: datetime) -> None:
        self.sweeps += 1

    def pending(self, session_id: str, cost: str = "0.60") -> MemoryTask:
        task = self.store.spawn(
            "alice",
            TaskKind.session_extract,
            session_id,
            spawned_by=SpawnedBy.auto,
            now=self.now,
            session_week_key="2026-W37",
            estimate=TaskEstimate(
                model=Config().agent.title_model, input_tokens=100, output_tokens_cap=10, cost_usd=Decimal(cost)
            ),
        )
        assert task is not None
        return task

    def queued(self, session_id: str, cost: str = "0.60") -> MemoryTask:
        task = self.pending(session_id, cost)
        self.store.run("alice", TaskSelection(ids=[task.id]), None, self.now)
        return task

    def task(self, task_id: int) -> MemoryTask:
        task = self.store.get_task("alice", task_id)
        assert task is not None
        return task

    async def tick(self) -> None:
        await self.worker.tick()
        await self.worker.drain()


@pytest.fixture
def env(db_factory) -> Env:
    return Env(db_factory)


async def test_two_tasks_that_fit_alone_but_not_together(env: Env):
    first, second = env.queued("s1"), env.queued("s2")  # 0.60 each against a 1.00 day limit
    env.extract.block = asyncio.Event()
    await env.worker.tick()

    assert env.task(first.id).status is TaskStatus.running
    blocked = env.task(second.id)
    assert (blocked.status, blocked.blocked_reason) == (TaskStatus.queued, BlockedReason.budget)
    env.extract.block.set()
    await env.worker.drain()


async def test_raising_the_budget_unblocks(env: Env):
    task = env.queued("s1", cost="2.00")
    await env.tick()
    assert env.task(task.id).blocked_reason is BlockedReason.budget

    env.user_config.memory.budget.cost_usd_per_day = Decimal("5.00")
    await env.tick()
    assert env.task(task.id).status is TaskStatus.done


async def test_success_records_outcome_and_schedules_a_debounced_mirror(env: Env):
    a, b = env.queued("s1", cost="0.10"), env.queued("s2", cost="0.10")
    env.store.run("alice", TaskSelection(ids=[a.id, b.id]), None, env.now)
    await env.tick()

    assert env.task(a.id).status is TaskStatus.done
    assert env.store.current_extraction("alice", "s1") is not None
    [mirror] = env.store.list_tasks("alice", TaskFilter(kind=[TaskKind.mirror]), None, 10).items
    assert mirror.status is TaskStatus.pending

    # The queue is empty now, so the mirror runs on the next tick without waiting.
    await env.tick()
    assert env.mirror.runs == 1
    assert env.task(mirror.id).status is TaskStatus.done


async def test_mirror_waits_for_a_quiet_queue_or_the_debounce(env: Env):
    env.worker.note_records_changed("alice", env.now)
    env.queued("s1", cost="2.00")  # blocked by the budget: the queue never drains
    await env.tick()
    assert env.mirror.runs == 0
    env.now += timedelta(minutes=3)
    await env.tick()
    await env.tick()
    assert env.mirror.runs == 1


async def test_failures_are_recorded_with_billing_when_billed(env: Env):
    unbilled = env.queued("s1", cost="0.10")
    env.extract.fail = RuntimeError("boom")
    await env.tick()
    failed = env.task(unbilled.id)
    assert (failed.status, failed.error) == (TaskStatus.failed, "RuntimeError: boom")
    assert env.store.spend("alice", NOW).cost_usd == 0

    billed = env.queued("s2", cost="0.10")
    env.extract.fail = TaskRunError("output validation failed", _provenance(billed, "m", "0.07"))
    await env.tick()
    assert env.task(billed.id).error == "output validation failed"
    assert env.store.spend("alice", NOW).cost_usd == Decimal("0.07")


async def test_cancel_aborts_a_running_call(env: Env):
    task = env.queued("s1", cost="0.10")
    env.extract.block = asyncio.Event()
    await env.worker.tick()
    assert env.task(task.id).status is TaskStatus.running

    env.store.cancel("alice", TaskSelection(ids=[task.id]), env.now)
    env.worker.abort([task.id])
    await env.worker.drain()
    assert env.task(task.id).status is TaskStatus.cancelled
    assert env.store.current_extraction("alice", "s1") is None


async def test_recheck_cancels_ineligible_sessions_and_defers_running_turns(env: Env):
    private, busy = env.queued("s1", cost="0.10"), env.queued("s2", cost="0.10")
    env.ineligible = {"s1": Ineligible.private, "s2": Ineligible.agent_running}
    await env.tick()

    cancelled = env.task(private.id)
    assert cancelled.status is TaskStatus.cancelled and cancelled.error == "session became ineligible: private"
    assert env.task(busy.id).status is TaskStatus.queued
    assert env.extract.runs == []

    env.ineligible = {}
    await env.tick()
    assert env.task(busy.id).status is TaskStatus.done


async def test_model_override_re_estimates_and_runs_with_that_model(env: Env):
    task = env.pending("s1", cost="0.10")
    env.store.run("alice", TaskSelection(ids=[task.id]), "test:override", env.now)
    await env.tick()
    assert env.extract.runs == [("s1", "test:override")]
    done = env.task(task.id)
    assert done.estimate is not None and done.estimate.model == "test:override"


async def test_auto_mode_promotes_what_the_budget_covers(env: Env):
    env.user_config.memory.auto_mode = True
    tasks = [env.pending(s, cost="0.40") for s in ("s1", "s2", "s3")]
    env.extract.block = asyncio.Event()
    await env.worker.tick()

    statuses = [env.task(t.id).status for t in tasks]
    assert statuses.count(TaskStatus.pending) == 1  # three at 0.40 exceed 1.00
    env.extract.block.set()
    await env.worker.drain()


async def test_manual_mode_never_promotes(env: Env):
    task = env.pending("s1", cost="0.10")
    await env.tick()
    assert env.task(task.id).status is TaskStatus.pending


async def test_sweep_runs_on_its_interval(env: Env):
    await env.tick()
    await env.tick()
    assert env.sweeps == 1
    env.now += timedelta(minutes=6)
    await env.tick()
    assert env.sweeps == 2
