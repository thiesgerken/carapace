from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from ..jobs import JobsStore
from ..models.config import Config
from ..models.user import UserConfig
from ..session import SessionManager
from ..user_defaults import effective_memory_model
from .budget import budget_windows, sum_estimates
from .handlers import TaskHandler
from .input import first_user_message_at
from .models import (
    BudgetWindowStatus,
    DigestLevel,
    EffectiveMemoryModels,
    EstimateTotal,
    FactFilter,
    FactListResponse,
    MemoryStatus,
    MemoryTask,
    ModelRole,
    PeriodDetail,
    PeriodTree,
    SessionMemoryDetail,
    SessionMemoryFilter,
    SessionMemoryListResponse,
    SpawnedBy,
    SpawnSkip,
    TaskCountResponse,
    TaskEstimate,
    TaskFilter,
    TaskKind,
    TaskListResponse,
    TaskRunRequest,
    TaskSelection,
    TaskSpawnRequest,
    TaskSpawnResponse,
    TaskStatus,
    TaskView,
)
from .periods import period_dates, week_key
from .spawner import MALFORMED_TRANSCRIPT_ERRORS, Spawner
from .store import MemoryStore
from .worker import DEFAULT_TIMING, MemoryWorker, WorkerTiming

_DIGEST_LEVELS = {TaskKind.week_digest: DigestLevel.week, TaskKind.month_digest: DigestLevel.month}


class MemoryService:
    """Facade the server uses for everything memory: queries, task actions and the worker loop."""

    def __init__(
        self,
        *,
        config: Config,
        store: MemoryStore,
        sessions: SessionManager,
        jobs: JobsStore,
        handlers: Mapping[TaskKind, TaskHandler],
        user_config_for: Callable[[str], UserConfig],
        users: Callable[[], list[str]],
        is_agent_running: Callable[[str], bool],
        timing: WorkerTiming = DEFAULT_TIMING,
        clock: Callable[[], datetime] = lambda: datetime.now(tz=UTC),
    ) -> None:
        self._config = config
        self._sessions = sessions
        self._handlers = handlers
        self._user_config_for = user_config_for
        self._clock = clock
        # Shared with the handlers, which read records through the same store.
        self._store = store
        self._spawner = Spawner(
            store=self._store,
            sessions=sessions,
            jobs=jobs,
            handlers=handlers,
            config=config,
            user_config_for=user_config_for,
            users=users,
            is_agent_running=is_agent_running,
            on_records_changed=lambda user, now: self._worker.note_records_changed(user, now),
        )
        self._worker = MemoryWorker(
            store=self._store,
            handlers=handlers,
            config=config,
            user_config_for=user_config_for,
            users=users,
            sweep=self._spawner.sweep,
            recheck_session=self._spawner.recheck,
            max_parallel=config.agent.max_parallel_llm,
            timing=timing,
            clock=clock,
        )

    @property
    def worker(self) -> MemoryWorker:
        return self._worker

    async def run(self) -> None:
        """Worker loop: spawn, promote, claim, execute. Started once by the server lifespan."""
        await self._worker.run()

    # --- status and tasks ---

    async def status(self, user: str) -> MemoryStatus:
        user_config = self._user_config_for(user)
        budget = user_config.memory.budget
        windows = budget_windows(self._clock(), ZoneInfo(user_config.timezone))
        day, month = self._store.spend(user, windows.day_start), self._store.spend(user, windows.month_start)
        counts, blocked = self._store.status_counts(user)
        return MemoryStatus(
            auto_mode=user_config.memory.auto_mode,
            timezone=user_config.timezone,
            day=BudgetWindowStatus(
                window_start=windows.day_start,
                spent_cost_usd=day.cost_usd,
                spent_input_tokens=day.input_tokens,
                limit_cost_usd=budget.cost_usd_per_day,
                limit_input_tokens=budget.input_tokens_per_day,
            ),
            month=BudgetWindowStatus(
                window_start=windows.month_start,
                spent_cost_usd=month.cost_usd,
                spent_input_tokens=month.input_tokens,
                limit_cost_usd=budget.cost_usd_per_month,
                limit_input_tokens=budget.input_tokens_per_month,
            ),
            queue=counts,
            blocked=blocked,
            models=EffectiveMemoryModels(
                memory_low=effective_memory_model(self._config, user_config, ModelRole.memory_low),
                memory_high=effective_memory_model(self._config, user_config, ModelRole.memory_high),
            ),
            sessions_without_transcript=self._spawner.sessions_without_transcript.get(user, 0),
        )

    async def list_tasks(self, user: str, task_filter: TaskFilter, cursor: str | None, limit: int) -> TaskListResponse:
        page = self._store.list_tasks(user, task_filter, cursor, limit)
        matching = self._store.select_tasks(user, TaskSelection(filter=task_filter), set(TaskStatus))
        return TaskListResponse(
            items=self._views(page.items),
            next_cursor=page.next_cursor,
            total=page.total,
            estimate=sum_estimates(t.estimate for t in matching if t.estimate is not None),
        )

    async def estimate_tasks(self, user: str, request: TaskRunRequest) -> EstimateTotal:
        """What running the pending tasks of a selection would cost, with the requested model."""
        tasks = self._store.select_tasks(user, request.selection, {TaskStatus.pending})
        return sum_estimates([await self._estimate_for(t, request.model_override) for t in tasks if t.estimate])

    async def run_tasks(self, user: str, request: TaskRunRequest) -> TaskCountResponse:
        count = self._store.run(user, request.selection, request.model_override, self._clock())
        self._worker.wake()
        return TaskCountResponse(count=count)

    async def cancel_tasks(self, user: str, selection: TaskSelection) -> TaskCountResponse:
        running = [t.id for t in self._store.select_tasks(user, selection, {TaskStatus.running})]
        count = self._store.cancel(user, selection, self._clock())
        self._worker.abort(running)
        self._worker.wake()
        return TaskCountResponse(count=count)

    async def retry_tasks(self, user: str, task_ids: list[int]) -> TaskCountResponse:
        count = self._store.retry(user, task_ids, self._clock())
        self._worker.wake()
        return TaskCountResponse(count=count)

    async def spawn_tasks(self, user: str, request: TaskSpawnRequest) -> TaskSpawnResponse:
        """Manual spawn/respawn for explicit targets; identity never blocks it, eligibility does."""
        if request.targets is None:
            raise NotImplementedError("spawning by session filter lands with the session views")
        now = self._clock()
        user_config = self._user_config_for(user)
        task_ids: list[int] = []
        skipped: list[SpawnSkip] = []
        for target in request.targets:
            try:
                reason = await self._spawn_one(user, user_config, request, target, now, task_ids)
            except MALFORMED_TRANSCRIPT_ERRORS as exc:
                reason = f"cannot prepare transcript: {type(exc).__name__}: {exc}"
            if reason is not None:
                skipped.append(SpawnSkip(target=target, reason=reason))
        return TaskSpawnResponse(task_ids=task_ids, skipped=skipped)

    async def _spawn_one(
        self,
        user: str,
        user_config: UserConfig,
        request: TaskSpawnRequest,
        target: str,
        now: datetime,
        task_ids: list[int],
    ) -> str | None:
        """Spawn one target; the skip reason when it gets no task."""
        session_week_key: str | None = None
        if request.kind is TaskKind.session_extract:
            state = self._sessions.load_state(target)
            if state is None or not self._sessions.is_owned_by(target, user):
                return "not_found"
            events = self._sessions.load_events(target)
            if (ineligible := self._spawner.ineligibility(state, events)) is not None:
                return ineligible.value
            first_message_at = first_user_message_at(events)
            if first_message_at is None:
                raise ValueError("eligible session without a user message")
            session_week_key = week_key(first_message_at, ZoneInfo(user_config.timezone))
        elif request.kind in _DIGEST_LEVELS:
            try:
                period_dates(_DIGEST_LEVELS[request.kind], target)
            except ValueError:
                return "invalid_period"
        elif target != user:
            return "not_found"  # a mirror's target is its user
        handler = self._handlers.get(request.kind)
        if handler is None:
            return "no_handler"
        estimate = None
        if handler.model_role is not None:
            model = request.model_override or effective_memory_model(self._config, user_config, handler.model_role)
            estimate = await handler.estimate(user, target, model)
        task = self._store.spawn(
            user,
            request.kind,
            target,
            spawned_by=SpawnedBy.manual,
            now=now,
            session_week_key=session_week_key,
            estimate=estimate,
            model_override=request.model_override,
        )
        if task is None:
            return "already_open"
        task_ids.append(task.id)
        return None

    # --- views ---

    async def list_sessions(
        self, user: str, session_filter: SessionMemoryFilter, cursor: str | None, limit: int
    ) -> SessionMemoryListResponse:
        # ponytail: the session views land in task 5b.
        return SessionMemoryListResponse(items=[], next_cursor=None, total=0)

    async def session_detail(self, user: str, session_id: str) -> SessionMemoryDetail | None:
        return None

    async def periods(self, user: str) -> PeriodTree:
        return PeriodTree(months=[])

    async def period_detail(self, user: str, level: DigestLevel, key: str) -> PeriodDetail | None:
        return None

    async def facts(self, user: str, fact_filter: FactFilter) -> FactListResponse:
        return FactListResponse(items=self._store.facts(user, fact_filter))

    # --- helpers ---

    def _views(self, tasks: list[MemoryTask]) -> list[TaskView]:
        titles = self._store.session_titles([t.target for t in tasks if t.kind is TaskKind.session_extract])
        return [
            TaskView(
                **task.model_dump(),
                target_label=(titles.get(task.target) or task.target)
                if task.kind is TaskKind.session_extract
                else task.target,
            )
            for task in tasks
        ]

    async def _estimate_for(self, task: MemoryTask, model_override: str | None) -> TaskEstimate:
        if task.estimate is None:
            raise ValueError(f"task {task.id} has no estimate")
        if model_override is None or model_override == task.estimate.model:
            return task.estimate
        return await self._handlers[task.kind].estimate(task.user, task.target, model_override)
