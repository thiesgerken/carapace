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
from .handlers import TaskHandler
from .models import BlockedReason, MemoryTask, SpawnedBy, TaskEstimate, TaskKind, TaskSelection, TaskStatus
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


@dataclass(frozen=True)
class _InFlight:
    user: str
    estimate: TaskEstimate | None
    job: asyncio.Task[None]


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
        max_parallel: int,
        timing: WorkerTiming = WorkerTiming(),
        clock: Callable[[], datetime] = lambda: datetime.now(tz=UTC),
    ) -> None:
        self._store = store
        self._handlers = handlers
        self._config = config
        self._user_config_for = user_config_for
        self._users = users
        self._sweep = sweep
        self._max_parallel = max_parallel
        self._timing = timing
        self._clock = clock
        self._wake = asyncio.Event()
        self._in_flight: dict[int, _InFlight] = {}
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
        """Stop the LLM calls of tasks the store already marked cancelled."""
        for task_id in task_ids:
            in_flight = self._in_flight.get(task_id)
            if in_flight is not None:
                in_flight.job.cancel()

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
        while self._in_flight:
            await asyncio.gather(*(f.job for f in list(self._in_flight.values())), return_exceptions=True)

    # --- promotion ---

    async def _promote(self, user: str, user_config: UserConfig, now: datetime) -> None:
        """Auto mode: queue as many pending LLM tasks, in priority order, as the budget covers."""
        pending = self._store.pending_for_promotion(user, _PROMOTION_WINDOW)
        if not pending:
            return
        estimates = [await self._current_estimate(task, user_config) for task in pending]
        day, month = self._spend(user, user_config, now)
        count = affordable_count(user_config.memory.budget, day, month, estimates)
        if count:
            self._store.run(user, TaskSelection(ids=[task.id for task in pending[:count]]), None, now)

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

    def note_records_changed(self, user: str, now: datetime) -> None:
        """Schedule a mirror of the user's records (spawns or refreshes the pending one)."""
        mirror = self._store.spawn(user, TaskKind.mirror, user, spawned_by=SpawnedBy.auto, now=now)
        if mirror is None:
            self._mirror_dirty.add(user)

    # --- dispatch ---

    async def _dispatch(self, now: datetime) -> None:
        spend_cache: dict[str, tuple[Spend, Spend]] = {}
        for task in self._store.next_queued(_DISPATCH_WINDOW):
            if len(self._in_flight) >= self._max_parallel:
                return
            if task.id in self._in_flight:
                continue
            user_config = self._user_config_for(task.user)
            estimate = await self._current_estimate(task, user_config)
            if task.user not in spend_cache:
                spend_cache[task.user] = self._spend(task.user, user_config, now)
            day, month = spend_cache[task.user]
            if not fits(user_config.memory.budget, day, month, estimate):
                if task.blocked_reason is not BlockedReason.budget:
                    self._store.set_blocked(task.id, BlockedReason.budget)
                continue
            if not self._store.claim(task.id, now):
                continue
            if estimate is not None:
                spend_cache[task.user] = (day.plus(estimate), month.plus(estimate))
            model = self._model_for(task, user_config)
            job = asyncio.create_task(self._execute(task, model), name=f"memory-task-{task.id}")
            self._in_flight[task.id] = _InFlight(task.user, estimate, job)
            job.add_done_callback(lambda _, task_id=task.id: self._finished(task_id))

    def _finished(self, task_id: int) -> None:
        self._in_flight.pop(task_id, None)
        self.wake()

    async def _execute(self, task: MemoryTask, model: str | None) -> None:
        handler = self._handlers.get(task.kind)
        try:
            if handler is None:
                raise LookupError(f"no handler registered for {task.kind}")
            outcome = await handler.run(task, model)
        except asyncio.CancelledError:
            logger.info(f"Memory task {task.id} ({task.kind} {task.target}) cancelled while running")
            raise
        except Exception as exc:
            # The failure is the task's result: stored on the row, shown in the UI, retryable.
            logger.exception(f"Memory task {task.id} ({task.kind} {task.target}) failed")
            self._store.record_failure(task.id, f"{type(exc).__name__}: {exc}", self._clock())
            return
        now = self._clock()
        if not self._store.record_outcome(task.id, outcome, now):
            logger.info(f"Memory task {task.id} finished after it was cancelled; result discarded")
            return
        if task.kind is TaskKind.mirror:
            if task.user in self._mirror_dirty:
                self._mirror_dirty.discard(task.user)
                self.note_records_changed(task.user, now)
        else:
            self.note_records_changed(task.user, now)

    # --- helpers ---

    def _model_for(self, task: MemoryTask, user_config: UserConfig) -> str | None:
        handler = self._handlers.get(task.kind)
        if handler is None or handler.model_role is None:
            return None
        return task.model_override or effective_memory_model(self._config, user_config, handler.model_role)

    async def _current_estimate(self, task: MemoryTask, user_config: UserConfig) -> TaskEstimate | None:
        """The task's estimate for the model it would run with now, refreshed when that changed."""
        model = self._model_for(task, user_config)
        if model is None:
            return None
        if task.estimate is not None and task.estimate.model == model:
            return task.estimate
        estimate = await self._handlers[task.kind].estimate(task, model)
        self._store.set_estimate(task.id, estimate)
        return estimate

    def _spend(self, user: str, user_config: UserConfig, now: datetime) -> tuple[Spend, Spend]:
        """Finished spend plus the estimates of the user's running tasks, per budget window."""
        windows = budget_windows(now, ZoneInfo(user_config.timezone))
        day = self._store.spend(user, windows.day_start)
        month = self._store.spend(user, windows.month_start)
        for in_flight in self._in_flight.values():
            if in_flight.user == user and in_flight.estimate is not None:
                day, month = day.plus(in_flight.estimate), month.plus(in_flight.estimate)
        return day, month
