"""The memory queue loop: sweep, promote, gate, claim, execute, record."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from loguru import logger

from ..models.config import Config
from ..models.user import UserConfig
from ..user_defaults import effective_memory_model
from .budget import Spend, affordable_count, budget_windows, fits
from .handlers import TaskHandler, TaskRunError
from .models import (
    BlockedReason,
    Ineligible,
    MemoryTask,
    SpawnedBy,
    TaskEstimate,
    TaskKind,
    TaskSelection,
    TaskStatus,
)
from .spawner import MALFORMED_TRANSCRIPT_ERRORS
from .store import MemoryStore

# How many queued tasks one tick looks at; budget-blocked ones are re-checked every tick.
_DISPATCH_WINDOW = 200
# How many pending tasks auto mode considers per user and tick.
_PROMOTION_WINDOW = 500


@dataclass(frozen=True)
class WorkerTiming:
    sweep_interval: timedelta = timedelta(minutes=5)
    # Longest sleep between ticks; API actions and finished tasks wake the loop earlier.
    idle_timeout: timedelta = timedelta(seconds=30)
    # A pending mirror waits until the user's records have been quiet this long, or the queue is empty.
    mirror_debounce: timedelta = timedelta(minutes=2)


DEFAULT_TIMING = WorkerTiming()


class MemoryWorker:
    def __init__(
        self,
        *,
        store: MemoryStore,
        handlers: Mapping[TaskKind, TaskHandler],
        config: Config,
        user_config_for: Callable[[str], UserConfig],
        users: Callable[[], list[str]],
        sweep: Callable[[datetime], Awaitable[None]],
        recheck_session: Callable[[MemoryTask, datetime], Ineligible | None],
        max_parallel: int,
        timing: WorkerTiming = DEFAULT_TIMING,
        clock: Callable[[], datetime] = lambda: datetime.now(tz=UTC),
    ) -> None:
        self._store = store
        self._handlers = handlers
        self._config = config
        self._user_config_for = user_config_for
        self._users = users
        self._sweep = sweep
        self._recheck_session = recheck_session
        self._max_parallel = max_parallel
        self._timing = timing
        self._clock = clock
        self._wake = asyncio.Event()
        self._running: dict[int, asyncio.Task[None]] = {}
        # Users whose records changed while their mirror was running: it must run once more.
        self._mirror_dirty: set[str] = set()
        self._last_sweep: datetime | None = None

    async def run(self) -> None:
        requeued = self._store.requeue_running()
        if requeued:
            logger.info(f"Memory: requeued {requeued} task(s) left running by the previous process")
        while True:
            await self.tick()
            self._wake.clear()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), self._timing.idle_timeout.total_seconds())

    def wake(self) -> None:
        self._wake.set()

    def abort(self, task_ids: list[int]) -> None:
        """Stop the calls of tasks the store already marked cancelled."""
        for task_id in task_ids:
            job = self._running.get(task_id)
            if job is not None:
                job.cancel()

    async def tick(self) -> None:
        now = self._clock()
        if self._last_sweep is None or now - self._last_sweep >= self._timing.sweep_interval:
            self._last_sweep = now
            await self._sweep(now)
        for user in self._users():
            user_config = self._user_config_for(user)
            if user_config.memory.auto_mode:
                await self._promote(user, user_config, now)
            self._promote_mirror(user, now)
        await self._dispatch(now)

    async def drain(self) -> None:
        """Wait for every running task (tests and shutdown)."""
        while self._running:
            await asyncio.gather(*list(self._running.values()), return_exceptions=True)

    def note_records_changed(self, user: str, now: datetime) -> None:
        """Schedule a mirror of the user's records (spawns or refreshes the pending one)."""
        if TaskKind.mirror not in self._handlers:
            return
        if self._store.spawn(user, TaskKind.mirror, user, spawned_by=SpawnedBy.auto, now=now) is None:
            self._mirror_dirty.add(user)

    # --- promotion ---

    async def _promote(self, user: str, user_config: UserConfig, now: datetime) -> None:
        """Auto mode: queue as many pending LLM tasks, in priority order, as the budget covers."""
        candidates: list[tuple[MemoryTask, TaskEstimate]] = []
        for task in self._store.pending_for_promotion(user, _PROMOTION_WINDOW):
            if task.kind not in self._handlers:
                continue
            estimate = await self._estimate_or_fail(task, user_config, now)
            if estimate is not None:
                candidates.append((task, estimate))
        # Already queued tasks have a claim on the budget too; without them every tick would queue
        # another affordable prefix and the backlog would pile up blocked.
        day, month = self._spend(user, user_config, now)
        queued = self._store.queued_spend(user)
        day, month = day.plus_spend(queued), month.plus_spend(queued)
        count = affordable_count(user_config.memory.budget, day, month, [e for _, e in candidates])
        if count:
            self._store.run(user, TaskSelection(ids=[t.id for t, _ in candidates[:count]]), None, now)

    def _promote_mirror(self, user: str, now: datetime) -> None:
        """Mirrors are free and run in manual mode too, batched behind a debounce."""
        mirror = self._store.open_tasks(user, TaskKind.mirror).get(user)
        if mirror is None or mirror.status is not TaskStatus.pending:
            return
        counts, _ = self._store.status_counts(user)
        llm_busy = counts[TaskStatus.queued] + counts[TaskStatus.running] > 0
        if llm_busy and now - mirror.created_at < self._timing.mirror_debounce:
            return
        self._store.run(user, TaskSelection(ids=[mirror.id]), None, now)

    # --- dispatch ---

    async def _dispatch(self, now: datetime) -> None:
        # Per user and pass: committed spend, grown by each task this pass claims.
        spend: dict[str, tuple[Spend, Spend]] = {}
        for task in self._store.next_queued(_DISPATCH_WINDOW):
            if len(self._running) >= self._max_parallel:
                return
            if task.id in self._running:
                continue
            handler = self._handlers.get(task.kind)
            if handler is None:
                self._store.fail_unclaimed(task.id, f"no handler registered for {task.kind}", now)
                continue
            user_config = self._user_config_for(task.user)
            estimate: TaskEstimate | None = None
            if handler.model_role is not None:
                estimate = await self._estimate_or_fail(task, user_config, now)
                if estimate is None:
                    continue
                if task.user not in spend:
                    spend[task.user] = self._spend(task.user, user_config, now)
                day, month = spend[task.user]
                if not fits(user_config.memory.budget, day, month, estimate):
                    if task.blocked_reason is not BlockedReason.budget:
                        self._store.set_blocked(task.id, BlockedReason.budget)
                    continue
            # Only now, for the task about to run: the re-check loads its transcript, and budget-
            # blocked tasks must not do that every tick.
            if task.kind is TaskKind.session_extract and not self._session_still_eligible(task, now):
                continue
            if not self._store.claim(task.id, now):
                continue
            if estimate is not None:
                day, month = spend[task.user]
                spend[task.user] = (day.plus(estimate), month.plus(estimate))
            self._start(task, self._model_for(task, user_config))

    def _session_still_eligible(self, task: MemoryTask, now: datetime) -> bool:
        """Re-check right before running; an ineligible session's task is cancelled at no cost."""
        try:
            reason = self._recheck_session(task, now)
        except MALFORMED_TRANSCRIPT_ERRORS as exc:
            self._store.fail_unclaimed(task.id, f"cannot prepare transcript: {type(exc).__name__}: {exc}", now)
            return False
        if reason is None:
            return True
        if reason is not Ineligible.agent_running:  # a running turn only means "not yet"
            self._store.cancel_task(task.id, f"session became ineligible: {reason}", now)
        return False

    def _start(self, task: MemoryTask, model: str | None) -> None:
        job = asyncio.create_task(self._execute(task, model), name=f"memory-task-{task.id}")
        self._running[task.id] = job
        job.add_done_callback(lambda _, task_id=task.id: self._finished(task_id))

    def _finished(self, task_id: int) -> None:
        self._running.pop(task_id, None)
        self.wake()

    async def _execute(self, task: MemoryTask, model: str | None) -> None:
        try:
            outcome = await self._handlers[task.kind].run(task, model)
        except asyncio.CancelledError:
            logger.info(f"Memory task {task.id} ({task.kind} {task.target}) cancelled while running")
            raise
        except TaskRunError as exc:
            logger.exception(f"Memory task {task.id} ({task.kind} {task.target}) failed after billing")
            self._store.record_failure(task.id, str(exc), self._clock(), exc.provenance)
            return
        except Exception as exc:
            # The failure is the task's result: stored on the row, shown in the UI, retryable.
            logger.exception(f"Memory task {task.id} ({task.kind} {task.target}) failed")
            self._store.record_failure(task.id, f"{type(exc).__name__}: {exc}", self._clock())
            return
        now = self._clock()
        if not self._store.record_outcome(task.id, outcome, now):
            logger.info(f"Memory task {task.id} finished after it was cancelled; result discarded")
            return
        if task.kind is not TaskKind.mirror:
            self.note_records_changed(task.user, now)
        elif task.user in self._mirror_dirty:
            self._mirror_dirty.discard(task.user)
            self.note_records_changed(task.user, now)

    # --- helpers ---

    def _model_for(self, task: MemoryTask, user_config: UserConfig) -> str | None:
        role = self._handlers[task.kind].model_role
        if role is None:
            return None
        return task.model_override or effective_memory_model(self._config, user_config, role)

    async def _estimate_or_fail(self, task: MemoryTask, user_config: UserConfig, now: datetime) -> TaskEstimate | None:
        """The task's estimate for the model it would run with now, refreshed when that changed.

        None, with the task failed, when estimating raised: such a task could never pass the gate.
        """
        model = self._model_for(task, user_config)
        if model is None:
            raise ValueError(f"{task.kind} makes no LLM call and has no estimate")
        if task.estimate is not None and task.estimate.model == model:
            return task.estimate
        try:
            estimate = await self._handlers[task.kind].estimate(task.user, task.target, model)
        except Exception as exc:
            # Same contract as a failed run: the error lands on the task, visible and retryable.
            logger.exception(f"Memory task {task.id} ({task.kind} {task.target}): estimate failed")
            self._store.fail_unclaimed(task.id, f"estimate failed: {type(exc).__name__}: {exc}", now)
            return None
        self._store.set_estimate(task.id, estimate)
        return estimate

    def _spend(self, user: str, user_config: UserConfig, now: datetime) -> tuple[Spend, Spend]:
        windows = budget_windows(now, ZoneInfo(user_config.timezone))
        return self._store.spend(user, windows.day_start), self._store.spend(user, windows.month_start)
