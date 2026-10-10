"""Decides which memory tasks should exist. Polls sessions and records; never hooks into the engine.

Spawning is cheap and automatic; whether a task runs is the worker's (and the user's) business.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from loguru import logger

from ..jobs import JobsStore
from ..models.config import Config
from ..models.session import SessionState
from ..models.user import UserConfig
from ..session import SessionManager
from ..user_defaults import effective_memory_model
from .coverage import coverage_hash, month_coverage, week_coverage
from .handlers import TaskHandler
from .input import INPUT_FORMAT_VERSION, first_user_message_at, render_extraction_input
from .models import (
    DigestLevel,
    DigestRecord,
    ExtractionRecord,
    Ineligible,
    MemoryTask,
    SpawnedBy,
    TaskKind,
    TaskSelection,
    TaskStatus,
)
from .periods import month_key_for_week, period_ended, week_key
from .store import MemoryStore

# What a malformed transcript raises while rendering (missing or broken event timestamps and
# fields). Only these are isolated per session; anything else is a bug and fails the sweep.
MALFORMED_TRANSCRIPT_ERRORS = (KeyError, ValueError, TypeError)


def _in_progress(task: MemoryTask | None) -> bool:
    """Queued or running tasks stand. A pending one is respawned (and replaced, with a fresh
    estimate) when its sources changed, so the gate never prices stale input."""
    return task is not None and task.status is not TaskStatus.pending


class Spawner:
    def __init__(
        self,
        *,
        store: MemoryStore,
        sessions: SessionManager,
        jobs: JobsStore,
        handlers: Mapping[TaskKind, TaskHandler],
        config: Config,
        user_config_for: Callable[[str], UserConfig],
        users: Callable[[], list[str]],
        is_agent_running: Callable[[str], bool],
        on_records_changed: Callable[[str, datetime], None],
    ) -> None:
        self._store = store
        self._sessions = sessions
        self._jobs = jobs
        self._handlers = handlers
        self._config = config
        self._user_config_for = user_config_for
        self._users = users
        self._is_agent_running = is_agent_running
        self._on_records_changed = on_records_changed
        # Per user, as of the last sweep; shown on /status so the skip is visible.
        self.sessions_without_transcript: dict[str, int] = {}
        # Current extraction ids per user at the last sweep. Deleting a session drops its
        # extractions by cascade, invisibly to memory; a shrinking set is how the mirror hears.
        # ponytail: in memory, so a deletion before a restart waits for the next record change.
        self._known_extractions: dict[str, set[int]] = {}

    async def sweep(self, now: datetime) -> None:
        for user in self._users():
            await self.sweep_user(user, now)

    async def sweep_user(self, user: str, now: datetime) -> None:
        user_config = self._user_config_for(user)
        await self._sweep_sessions(user, user_config, now)
        await self._spawn_week_digests(user, user_config, now)
        await self._spawn_month_digests(user, user_config, now)

    # --- eligibility (shared with manual spawns) ---

    def quick_ineligibility(self, state: SessionState) -> Ineligible | None:
        """The checks that need no transcript."""
        if state.attributes.private:
            return Ineligible.private
        if state.channel_type == "job" and not self._job_opted_in(state):
            return Ineligible.job_excluded
        if self._is_agent_running(state.session_id):
            return Ineligible.agent_running
        return None

    def ineligibility(self, state: SessionState, events: list[dict[str, Any]]) -> Ineligible | None:
        """Every rule; raises one of MALFORMED_TRANSCRIPT_ERRORS for a broken transcript."""
        if (reason := self.quick_ineligibility(state)) is not None:
            return reason
        if not events:
            return Ineligible.no_transcript
        if first_user_message_at(events) is None:
            return Ineligible.no_user_message
        return None

    def recheck(self, task: MemoryTask, now: datetime) -> Ineligible | None:
        """Eligibility of a session_extract task's session right before it runs.

        Things change between spawn and run (private, deleted, a new agent turn). A session
        that turned private is purged here, as in the sweep.
        """
        state = self._sessions.load_state(task.target)
        if state is None:
            return Ineligible.deleted
        reason = self.ineligibility(state, self._sessions.load_events(task.target))
        if reason is Ineligible.private and self._store.current_extraction(task.user, task.target) is not None:
            self._store.purge_extractions(task.target)
            self._on_records_changed(task.user, now)
        return reason

    def _job_opted_in(self, state: SessionState) -> bool:
        if state.latest_job_run is None:
            return False
        job = self._jobs.get_job(state.latest_job_run.job_id)
        return job is not None and job.memory_enabled

    # --- session extractions ---

    async def _sweep_sessions(self, user: str, user_config: UserConfig, now: datetime) -> None:
        tz = ZoneInfo(user_config.timezone)
        current = {record.session_id: record for record in self._store.current_extractions(user)}
        known = self._known_extractions.get(user)
        self._known_extractions[user] = {record.id for record in current.values()}
        open_tasks = self._store.open_tasks(user, TaskKind.session_extract)
        last_spawned = self._store.latest_task_times(user, TaskKind.session_extract)
        settled_before = now - timedelta(hours=self._config.sessions.commit.autosave_inactivity_hours)
        records_changed = False
        without_transcript = 0

        for session_id in self._sessions.list_sessions(user=user):
            state = self._sessions.load_state(session_id)
            if state is None:
                continue
            if state.attributes.private:
                records_changed |= self._purge(user, session_id, session_id in current, open_tasks.get(session_id), now)
                continue
            if _in_progress(open_tasks.get(session_id)) or self.quick_ineligibility(state) is not None:
                continue
            if not state.attributes.archived and state.last_active > settled_before:
                continue
            spawned_at = last_spawned.get(session_id)
            if spawned_at is not None and spawned_at >= state.last_active:
                continue
            try:
                reason = await self._spawn_extraction(user, user_config, state, current.get(session_id), tz, now)
            except MALFORMED_TRANSCRIPT_ERRORS as exc:
                error = f"cannot prepare transcript: {type(exc).__name__}: {exc}"
                logger.error(f"Memory spawner: session {session_id} of {user!r}: {error}")
                self._store.record_spawn_failure(user, TaskKind.session_extract, session_id, error, now)
                continue
            if reason is Ineligible.no_transcript:
                without_transcript += 1

        self.sessions_without_transcript[user] = without_transcript
        if known is not None and not known <= self._known_extractions[user]:
            records_changed = True
        if records_changed:
            self._on_records_changed(user, now)

    async def _spawn_extraction(
        self,
        user: str,
        user_config: UserConfig,
        state: SessionState,
        current: ExtractionRecord | None,
        tz: ZoneInfo,
        now: datetime,
    ) -> Ineligible | None:
        events = self._sessions.load_events(state.session_id)
        if (reason := self.ineligibility(state, events)) is not None:
            return reason
        rendered = render_extraction_input(events)
        if current is not None:
            # A format bump changes every hash; such records are outdated, never auto-respawned.
            if current.provenance.input_format_version != INPUT_FORMAT_VERSION:
                return None
            if current.input_hash == rendered.input_hash:
                return None
        first_message_at = first_user_message_at(events)
        if first_message_at is None:
            raise ValueError("eligible session without a user message")
        await self._spawn(
            user, user_config, TaskKind.session_extract, state.session_id, now, week_key(first_message_at, tz)
        )
        return None

    def _purge(
        self, user: str, session_id: str, has_extraction: bool, open_task: MemoryTask | None, now: datetime
    ) -> bool:
        """A private session keeps no memory: drop its records and cancel its open task."""
        if open_task is not None:
            # ponytail: a running call finishes and its result is discarded; aborting it needs
            # the worker, which the cancel API path already wires.
            self._store.cancel(user, TaskSelection(ids=[open_task.id]), now)
        if not has_extraction:
            return False
        self._store.purge_extractions(session_id)
        logger.info(f"Memory spawner: purged extractions of private session {session_id}")
        return True

    # --- digests ---

    async def _spawn_week_digests(self, user: str, user_config: UserConfig, now: datetime) -> None:
        if TaskKind.week_digest not in self._handlers:
            return
        tz = ZoneInfo(user_config.timezone)
        by_week: dict[str, list[ExtractionRecord]] = defaultdict(list)
        for record in self._store.current_extractions(user):
            by_week[record.week_key].append(record)
        busy_weeks = {t.week_key for t in self._store.open_tasks(user, TaskKind.session_extract).values()}
        digests = {d.period_key: d for d in self._store.current_digests(user, DigestLevel.week)}
        open_digests = self._store.open_tasks(user, TaskKind.week_digest)
        last_spawned = self._store.latest_task_times(user, TaskKind.week_digest)

        for week, sources in by_week.items():
            if (
                _in_progress(open_digests.get(week))
                or week in busy_weeks
                or not period_ended(DigestLevel.week, week, now, tz)
            ):
                continue
            if not self._digest_due(
                digests.get(week), coverage_hash(week_coverage(sources)), sources, last_spawned.get(week)
            ):
                continue
            await self._spawn(user, user_config, TaskKind.week_digest, week, now)

    async def _spawn_month_digests(self, user: str, user_config: UserConfig, now: datetime) -> None:
        if TaskKind.month_digest not in self._handlers:
            return
        tz = ZoneInfo(user_config.timezone)
        by_month: dict[str, list[DigestRecord]] = defaultdict(list)
        for record in self._store.current_digests(user, DigestLevel.week):
            by_month[month_key_for_week(record.period_key)].append(record)
        busy_months = {
            t.month_key
            for kind in (TaskKind.session_extract, TaskKind.week_digest)
            for t in self._store.open_tasks(user, kind).values()
        }
        digests = {d.period_key: d for d in self._store.current_digests(user, DigestLevel.month)}
        open_digests = self._store.open_tasks(user, TaskKind.month_digest)
        last_spawned = self._store.latest_task_times(user, TaskKind.month_digest)

        for month, sources in by_month.items():
            if (
                _in_progress(open_digests.get(month))
                or month in busy_months
                or not period_ended(DigestLevel.month, month, now, tz)
            ):
                continue
            if not self._digest_due(
                digests.get(month), coverage_hash(month_coverage(sources)), sources, last_spawned.get(month)
            ):
                continue
            await self._spawn(user, user_config, TaskKind.month_digest, month, now)

    @staticmethod
    def _digest_due(
        current: DigestRecord | None,
        current_coverage_hash: str,
        sources: list[ExtractionRecord] | list[DigestRecord],
        spawned_at: datetime | None,
    ) -> bool:
        """No digest yet or its coverage changed, and no task already tried these exact sources."""
        if current is not None and current.coverage_hash == current_coverage_hash:
            return False
        newest_source = max(source.created_at for source in sources)
        return spawned_at is None or spawned_at < newest_source

    # --- spawning ---

    async def _spawn(
        self,
        user: str,
        user_config: UserConfig,
        kind: TaskKind,
        target: str,
        now: datetime,
        session_week_key: str | None = None,
    ) -> None:
        handler = self._handlers.get(kind)
        if handler is None:
            logger.debug(f"Memory spawner: no handler for {kind} yet, not spawning {target}")
            return
        if handler.model_role is None:
            raise ValueError(f"{kind} is not an LLM task and is never spawned by the sweep")
        model = effective_memory_model(self._config, user_config, handler.model_role)
        estimate = await handler.estimate(user, target, model)
        task = self._store.spawn(
            user,
            kind,
            target,
            spawned_by=SpawnedBy.auto,
            now=now,
            session_week_key=session_week_key,
            estimate=estimate,
        )
        if task is not None and task.status is TaskStatus.pending:
            logger.debug(f"Memory spawner: {kind} {target} for {user!r} pending")
