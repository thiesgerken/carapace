from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from ..jobs import JobsStore
from ..models.config import Config
from ..models.user import UserConfig
from ..session import SessionManager
from ..user_defaults import effective_memory_model
from .budget import budget_windows, sum_estimates
from .coverage import coverage_hash, month_coverage, week_coverage
from .handlers import TaskHandler
from .input import first_user_message_at
from .models import (
    BudgetWindowStatus,
    DigestLevel,
    DigestRecord,
    DigestSummary,
    EffectiveMemoryModels,
    EstimateTotal,
    ExtractionRecord,
    ExtractionSummary,
    FactCategory,
    FactCounts,
    FactFilter,
    FactListResponse,
    Ineligible,
    MemoryStatus,
    MemoryTask,
    ModelRole,
    MonthNode,
    PeriodDetail,
    PeriodNode,
    PeriodTree,
    SessionMemoryDetail,
    SessionMemoryFilter,
    SessionMemoryListResponse,
    SessionMemoryRow,
    SpawnedBy,
    SpawnSkip,
    TaskCountResponse,
    TaskEstimate,
    TaskFilter,
    TaskKind,
    TaskListResponse,
    TaskRef,
    TaskRunRequest,
    TaskSelection,
    TaskSpawnRequest,
    TaskSpawnResponse,
    TaskStatus,
    TaskView,
)
from .outdated import CurrentVersions, current_versions, outdated_reasons
from .periods import month_key_for_week, period_dates, week_key
from .spawner import MALFORMED_TRANSCRIPT_ERRORS, Spawner
from .store import MemoryStore, SessionCandidate, parse_cursor
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

    def matching_sessions(self, user: str, session_filter: SessionMemoryFilter) -> list[SessionCandidate]:
        """Sessions the memory views list, filtered, newest first.

        The one selection behind GET /sessions and spawning by filter, so both always agree.
        Private sessions and job sessions without memory_enabled are left out; a running agent
        turn is transient, so such sessions stay listed.

        ponytail: eligibility needs Python, so every matching session of the user loads before
        paging; fine for thousands of sessions per user, push the private/job rules into SQL beyond.
        """
        versions = self._extraction_versions(user)
        candidates = self._store.session_candidates(user, session_filter, versions)
        return [c for c in candidates if self._listed(c)]

    async def list_sessions(
        self, user: str, session_filter: SessionMemoryFilter, cursor: str | None, limit: int
    ) -> SessionMemoryListResponse:
        matching = self.matching_sessions(user, session_filter)
        offset = parse_cursor(cursor) if cursor is not None else 0
        page = matching[offset : offset + limit]
        return SessionMemoryListResponse(
            items=self._session_rows(user, page),
            next_cursor=str(offset + limit) if offset + limit < len(matching) else None,
            total=len(matching),
        )

    async def session_detail(self, user: str, session_id: str) -> SessionMemoryDetail | None:
        """None when the session does not exist, belongs to someone else or is not listed."""
        versions = self._extraction_versions(user)
        candidates = self._store.session_candidates(user, SessionMemoryFilter(), versions, session_id=session_id)
        listed = [c for c in candidates if self._listed(c)]
        if not listed:
            return None
        return SessionMemoryDetail(
            session=self._session_rows(user, listed)[0],
            current=self._store.current_extraction(user, session_id),
            history=self._store.extraction_history(user, session_id),
        )

    async def periods(self, user: str) -> PeriodTree:
        return PeriodTree(months=self._period_tree(user))

    async def period_detail(self, user: str, level: DigestLevel, key: str) -> PeriodDetail | None:
        """None when the period key is invalid or the period has no sources."""
        try:
            period_dates(level, key)
        except ValueError:
            return None
        months = self._period_tree(user)
        if level is DigestLevel.month:
            month = next((m for m in months if m.key == key), None)
            if month is None:
                return None
            node = PeriodNode.model_validate(month.model_dump(exclude={"weeks"}))
            weeks, sessions = month.weeks, []
        else:
            node = next((w for m in months for w in m.weeks if w.key == key), None)
            if node is None:
                return None
            weeks, sessions = [], self._session_rows(user, self.matching_sessions(user, SessionMemoryFilter(week=key)))
        return PeriodDetail(
            node=node,
            current=self._store.current_digest(user, level, key),
            history=self._store.digest_history(user, level, key),
            sessions=sessions,
            weeks=weeks,
        )

    async def facts(self, user: str, fact_filter: FactFilter) -> FactListResponse:
        return FactListResponse(items=self._store.facts(user, fact_filter))

    def _listed(self, candidate: SessionCandidate) -> bool:
        return self._spawner.quick_ineligibility(candidate.state) in (None, Ineligible.agent_running)

    def _extraction_versions(self, user: str) -> CurrentVersions:
        return current_versions(self._config, self._user_config_for(user), TaskKind.session_extract)

    def _session_rows(self, user: str, candidates: list[SessionCandidate]) -> list[SessionMemoryRow]:
        records = self._store.extractions_by_id([c.extraction_id for c in candidates if c.extraction_id is not None])
        versions = self._extraction_versions(user)
        return [
            SessionMemoryRow(
                session_id=c.state.session_id,
                title=c.title,
                channel_type=c.channel_type,
                created_at=c.created_at,
                week_key=c.week_key,
                extraction=_extraction_summary(records[c.extraction_id], versions)
                if c.extraction_id is not None
                else None,
                task=c.task,
            )
            for c in candidates
        ]

    def _period_tree(self, user: str) -> list[MonthNode]:
        """Months newest first, each with its weeks in order.

        A week's sources are its listed sessions with a known week (extracted or spawned) plus its
        current extractions; staleness uses the same coverage the spawner compares.
        """
        user_config = self._user_config_for(user)
        week_versions = current_versions(self._config, user_config, TaskKind.week_digest)
        month_versions = current_versions(self._config, user_config, TaskKind.month_digest)
        sessions_by_week: dict[str, set[str]] = defaultdict(set)
        for candidate in self.matching_sessions(user, SessionMemoryFilter()):
            if candidate.week_key is not None:
                sessions_by_week[candidate.week_key].add(candidate.state.session_id)
        extractions_by_week: dict[str, list[ExtractionRecord]] = defaultdict(list)
        for record in self._store.current_extractions(user):
            extractions_by_week[record.week_key].append(record)
            sessions_by_week[record.week_key].add(record.session_id)
        week_digests = {d.period_key: d for d in self._store.current_digests(user, DigestLevel.week)}
        month_digests = {d.period_key: d for d in self._store.current_digests(user, DigestLevel.month)}
        week_tasks = self._store.latest_tasks(user, TaskKind.week_digest)
        month_tasks = self._store.latest_tasks(user, TaskKind.month_digest)

        weeks_by_month: dict[str, list[str]] = defaultdict(list)
        for week in sorted(sessions_by_week.keys() | week_digests.keys()):
            weeks_by_month[month_key_for_week(week)].append(week)
        for month in month_digests:
            weeks_by_month.setdefault(month, [])

        months = []
        for month in sorted(weeks_by_month, reverse=True):
            weeks = [
                _period_node(
                    DigestLevel.week,
                    week,
                    covered=len(extractions_by_week[week]),
                    total=len(sessions_by_week[week]),
                    digest=week_digests.get(week),
                    sources_hash=coverage_hash(week_coverage(extractions_by_week[week])),
                    task=week_tasks.get(week),
                    versions=week_versions,
                )
                for week in weeks_by_month[month]
            ]
            week_sources = [week_digests[w] for w in weeks_by_month[month] if w in week_digests]
            node = _period_node(
                DigestLevel.month,
                month,
                covered=len(week_sources),
                total=len(weeks),
                digest=month_digests.get(month),
                sources_hash=coverage_hash(month_coverage(week_sources)),
                task=month_tasks.get(month),
                versions=month_versions,
            )
            months.append(MonthNode(**node.model_dump(), weeks=weeks))
        return months

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


def _extraction_summary(record: ExtractionRecord, versions: CurrentVersions) -> ExtractionSummary:
    counts = Counter(fact.category for fact in record.extraction.facts)
    return ExtractionSummary(
        id=record.id,
        abstract=record.extraction.abstract,
        fact_counts=FactCounts(**{category.value: counts[category] for category in FactCategory}),
        model=record.provenance.model,
        prompt_version=record.provenance.prompt_version,
        cost_usd=record.provenance.cost_usd,
        created_at=record.created_at,
        outdated=outdated_reasons(record.provenance, versions),
    )


def _period_node(
    level: DigestLevel,
    key: str,
    *,
    covered: int,
    total: int,
    digest: DigestRecord | None,
    sources_hash: str,
    task: MemoryTask | None,
    versions: CurrentVersions,
) -> PeriodNode:
    start, end = period_dates(level, key)
    return PeriodNode(
        level=level,
        key=key,
        start=start,
        end=end,
        covered=covered,
        total=total,
        digest=_digest_summary(digest, versions) if digest is not None else None,
        stale=digest is not None and digest.coverage_hash != sources_hash,
        task=TaskRef(id=task.id, status=task.status, blocked_reason=task.blocked_reason) if task is not None else None,
    )


def _digest_summary(record: DigestRecord, versions: CurrentVersions) -> DigestSummary:
    return DigestSummary(
        id=record.id,
        model=record.provenance.model,
        prompt_version=record.provenance.prompt_version,
        carapace_version=record.provenance.carapace_version,
        cost_usd=record.provenance.cost_usd,
        created_at=record.created_at,
        outdated=outdated_reasons(record.provenance, versions),
    )
