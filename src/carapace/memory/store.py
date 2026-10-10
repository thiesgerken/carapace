"""MemoryStore: the only module that builds SQL for the memory tables."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import ColumnElement, and_, case, delete, exists, func, not_, or_, select, update
from sqlalchemy.orm import Session

from ..database.engine import SessionFactory
from ..database.models import (
    MemoryDigestRow,
    MemoryFactRow,
    MemorySessionExtractionRow,
    MemoryTaskRow,
    SessionEventRow,
    SessionRow,
)
from ..models.session import SessionState
from .budget import Spend
from .models import (
    OPEN_TASK_STATUSES,
    BlockedReason,
    DigestLevel,
    DigestRecord,
    DigestResult,
    ExtractionRecord,
    ExtractionResult,
    ExtractionState,
    FactFilter,
    FactView,
    MemoryTask,
    MirrorResult,
    OutdatedReason,
    Provenance,
    SessionMemoryFilter,
    SpawnedBy,
    TaskEstimate,
    TaskFilter,
    TaskKind,
    TaskOutcome,
    TaskRef,
    TaskSelection,
    TaskStatus,
)
from .outdated import CurrentVersions
from .periods import month_key_for_week, period_weeks

_OPEN = [s.value for s in OPEN_TASK_STATUSES]

# Auto mode promotes session extractions first, then week digests, then month digests.
_PROMOTION_RANK = case(
    (MemoryTaskRow.kind == TaskKind.session_extract, 0),
    (MemoryTaskRow.kind == TaskKind.week_digest, 1),
    else_=2,
)
# "Newest" means newest period, not newest task: a backfill spawns everything at once.
_NEWEST_FIRST = (MemoryTaskRow.month_key.desc(), MemoryTaskRow.week_key.desc(), MemoryTaskRow.id.desc())


@dataclass(frozen=True)
class TaskPage:
    items: list[MemoryTask]
    next_cursor: str | None
    total: int


@dataclass(frozen=True)
class SessionCandidate:
    """A session as the memory views list it, before eligibility (which needs Python) is applied."""

    state: SessionState
    title: str | None
    channel_type: str
    created_at: datetime
    # From the current extraction, else the latest task; None until the session was first spawned.
    week_key: str | None
    extraction_id: int | None
    task: TaskRef | None


def task_periods(kind: TaskKind, target: str, session_week_key: str | None) -> tuple[str | None, str | None]:
    """(week_key, month_key) a task's target falls into; extractions need their session's week."""
    match kind:
        case TaskKind.session_extract:
            if session_week_key is None:
                raise ValueError("session_extract tasks need the session's week key")
            return session_week_key, month_key_for_week(session_week_key)
        case TaskKind.week_digest:
            return target, month_key_for_week(target)
        case TaskKind.month_digest:
            return None, target
        case TaskKind.mirror:
            return None, None


class MemoryStore:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    # --- tasks: spawning and user actions ---

    def spawn(
        self,
        user: str,
        kind: TaskKind,
        target: str,
        *,
        spawned_by: SpawnedBy,
        now: datetime,
        session_week_key: str | None = None,
        estimate: TaskEstimate | None = None,
        model_override: str | None = None,
    ) -> MemoryTask | None:
        """Create a pending task, or replace the target's pending one.

        Returns None when the target already has a queued or running task: that one stands.
        """
        if (estimate is None) != (kind is TaskKind.mirror):
            raise ValueError(f"{kind} tasks need an estimate exactly when they make an LLM call")
        week_key, month_key = task_periods(kind, target, session_week_key)
        values = {
            "spawned_by": spawned_by.value,
            "model_override": model_override,
            "estimate": estimate,
            "model": model_override or (estimate.model if estimate is not None else None),
            "week_key": week_key,
            "month_key": month_key,
            "created_at": now,
        }
        with self._session_factory.begin() as db:
            row = db.scalar(
                select(MemoryTaskRow).where(
                    MemoryTaskRow.user == user,
                    MemoryTaskRow.kind == kind,
                    MemoryTaskRow.target == target,
                    MemoryTaskRow.status.in_(_OPEN),
                )
            )
            if row is not None and row.status != TaskStatus.pending:
                return None
            if row is None:
                row = MemoryTaskRow(
                    user=user, kind=kind.value, target=target, status=TaskStatus.pending.value, **_UNBILLED
                )
                db.add(row)
            for name, value in values.items():
                setattr(row, name, value)
            db.flush()
            return _task(row)

    def record_spawn_failure(self, user: str, kind: TaskKind, target: str, error: str, now: datetime) -> MemoryTask:
        """A failed task for a target the spawner could not even prepare (e.g. a malformed transcript).

        It surfaces the problem in the Tasks tab with a retry button, and its timestamp keeps the
        spawner from retrying the same unchanged input on every sweep.
        """
        with self._session_factory.begin() as db:
            row = MemoryTaskRow(
                user=user,
                kind=kind.value,
                target=target,
                status=TaskStatus.failed.value,
                spawned_by=SpawnedBy.auto.value,
                error=error,
                **_UNBILLED,
                created_at=now,
                finished_at=now,
            )
            db.add(row)
            db.flush()
            return _task(row)

    def set_estimate(self, task_id: int, estimate: TaskEstimate) -> None:
        with self._session_factory.begin() as db:
            db.execute(
                update(MemoryTaskRow).where(MemoryTaskRow.id == task_id).values(estimate=estimate, model=estimate.model)
            )

    def list_tasks(self, user: str, task_filter: TaskFilter, cursor: str | None, limit: int) -> TaskPage:
        """Newest period first, the order "run newest N" selects in, so the top N rows are what runs.

        ponytail: offset cursor, so rows shift if tasks appear between pages; a compound keyset
        cursor over (month_key, week_key, id) with NULLs is the upgrade if that bites.
        """
        clauses = [MemoryTaskRow.user == user, *_filter_clauses(task_filter)]
        offset = parse_cursor(cursor) if cursor is not None else 0
        with self._session_factory() as db:
            total = db.scalar(select(func.count()).select_from(MemoryTaskRow).where(*clauses)) or 0
            rows = db.scalars(
                select(MemoryTaskRow).where(*clauses).order_by(*_NEWEST_FIRST).offset(offset).limit(limit + 1)
            ).all()
        items = [_task(row) for row in rows[:limit]]
        next_cursor = str(offset + limit) if len(rows) > limit else None
        return TaskPage(items=items, next_cursor=next_cursor, total=total)

    def select_tasks(self, user: str, selection: TaskSelection, statuses: set[TaskStatus]) -> list[MemoryTask]:
        """Tasks of a selection that are in one of *statuses*, newest period first."""
        with self._session_factory() as db:
            ids = _selected_ids(db, user, selection, statuses)
            rows = db.scalars(select(MemoryTaskRow).where(MemoryTaskRow.id.in_(ids)).order_by(*_NEWEST_FIRST)).all()
        return [_task(row) for row in rows]

    def run(self, user: str, selection: TaskSelection, model_override: str | None, now: datetime) -> int:
        """pending -> queued."""
        values: dict[str, object] = {"status": TaskStatus.queued.value, "queued_at": now, "blocked_reason": None}
        if model_override is not None:
            values |= {"model_override": model_override, "model": model_override}
        return self._transition(user, selection, {TaskStatus.pending}, values)

    def retry(self, user: str, task_ids: list[int], now: datetime) -> int:
        """failed -> queued. The row is reused; attempts grows on the next claim."""
        values = {"status": TaskStatus.queued.value, "queued_at": now, "error": None, "finished_at": None}
        return self._transition(user, TaskSelection(ids=task_ids), {TaskStatus.failed}, values)

    def cancel(self, user: str, selection: TaskSelection, now: datetime) -> int:
        """Any open task -> cancelled. A running task's result is discarded when it arrives."""
        values = {"status": TaskStatus.cancelled.value, "finished_at": now, "blocked_reason": None}
        return self._transition(user, selection, set(OPEN_TASK_STATUSES), values)

    def _transition(
        self, user: str, selection: TaskSelection, from_statuses: set[TaskStatus], values: Mapping[str, object]
    ) -> int:
        with self._session_factory.begin() as db:
            ids = _selected_ids(db, user, selection, from_statuses)
            if not ids:
                return 0
            # ponytail: one IN list; chunk it if selections ever outgrow SQLite's parameter limit.
            result = db.execute(
                update(MemoryTaskRow)
                .where(MemoryTaskRow.id.in_(ids), MemoryTaskRow.status.in_([s.value for s in from_statuses]))
                .values(**values)
            )
            return result.rowcount  # type: ignore[missing-attribute]

    # --- tasks: worker side ---

    def requeue_running(self) -> int:
        """Return tasks left running by a previous server process to the queue."""
        with self._session_factory.begin() as db:
            result = db.execute(
                update(MemoryTaskRow)
                .where(MemoryTaskRow.status == TaskStatus.running)
                .values(status=TaskStatus.queued.value, started_at=None)
            )
            return result.rowcount  # type: ignore[missing-attribute]

    def next_queued(self, limit: int) -> list[MemoryTask]:
        """Oldest queued first across users, budget-blocked ones included for re-evaluation."""
        with self._session_factory() as db:
            rows = db.scalars(
                select(MemoryTaskRow)
                .where(MemoryTaskRow.status == TaskStatus.queued)
                .order_by(MemoryTaskRow.queued_at, MemoryTaskRow.id)
                .limit(limit)
            ).all()
        return [_task(row) for row in rows]

    def pending_for_promotion(self, user: str, limit: int) -> list[MemoryTask]:
        """Pending LLM tasks in auto-mode order: extractions, week digests, month digests; newest first."""
        with self._session_factory() as db:
            rows = db.scalars(
                select(MemoryTaskRow)
                .where(
                    MemoryTaskRow.user == user,
                    MemoryTaskRow.status == TaskStatus.pending,
                    MemoryTaskRow.kind != TaskKind.mirror,
                )
                .order_by(_PROMOTION_RANK, *_NEWEST_FIRST)
                .limit(limit)
            ).all()
        return [_task(row) for row in rows]

    def set_blocked(self, task_id: int, reason: BlockedReason | None) -> None:
        with self._session_factory.begin() as db:
            db.execute(
                update(MemoryTaskRow)
                .where(MemoryTaskRow.id == task_id, MemoryTaskRow.status == TaskStatus.queued)
                .values(blocked_reason=reason.value if reason is not None else None)
            )

    def cancel_task(self, task_id: int, reason: str, now: datetime) -> bool:
        """Open -> cancelled with the reason kept as error, e.g. the session turned private."""
        with self._session_factory.begin() as db:
            result = db.execute(
                update(MemoryTaskRow)
                .where(MemoryTaskRow.id == task_id, MemoryTaskRow.status.in_(_OPEN))
                .values(status=TaskStatus.cancelled.value, error=reason, finished_at=now, blocked_reason=None)
            )
            return result.rowcount == 1  # type: ignore[missing-attribute]

    def fail_unclaimed(self, task_id: int, error: str, now: datetime) -> bool:
        """pending/queued -> failed, for tasks that broke before they could run (estimation)."""
        with self._session_factory.begin() as db:
            result = db.execute(
                update(MemoryTaskRow)
                .where(
                    MemoryTaskRow.id == task_id,
                    MemoryTaskRow.status.in_([TaskStatus.pending.value, TaskStatus.queued.value]),
                )
                .values(status=TaskStatus.failed.value, error=error, finished_at=now, blocked_reason=None)
            )
            return result.rowcount == 1  # type: ignore[missing-attribute]

    def claim(self, task_id: int, now: datetime) -> bool:
        """queued -> running, atomically: False if someone else claimed or cancelled it first."""
        with self._session_factory.begin() as db:
            result = db.execute(
                update(MemoryTaskRow)
                .where(MemoryTaskRow.id == task_id, MemoryTaskRow.status == TaskStatus.queued)
                .values(
                    status=TaskStatus.running.value,
                    started_at=now,
                    blocked_reason=None,
                    attempts=MemoryTaskRow.attempts + 1,
                )
            )
            return result.rowcount == 1  # type: ignore[missing-attribute]

    def record_outcome(self, task_id: int, outcome: TaskOutcome, now: datetime) -> bool:
        """Persist a handler's result and mark the task done, in one transaction.

        False (and nothing written) when the task is no longer running, e.g. cancelled meanwhile.
        """
        with self._session_factory.begin() as db:
            row = db.get(MemoryTaskRow, task_id, with_for_update=True)
            if row is None or row.status != TaskStatus.running:
                return False
            match outcome.result:
                case ExtractionResult() as result:
                    result_id = _write_extraction(db, row.user, result, outcome, now)
                case DigestResult() as result:
                    result_id = _write_digest(db, row.user, result, outcome, now)
                case MirrorResult():
                    result_id = None
            row.status = TaskStatus.done.value
            if outcome.provenance is not None:
                _add_billing(row, outcome.provenance, now)
            row.provenance = outcome.provenance
            row.result_id = result_id
            row.error = None
            row.finished_at = now
            if outcome.provenance is not None:
                row.model = outcome.provenance.model
            return True

    def record_failure(self, task_id: int, error: str, now: datetime, provenance: Provenance | None = None) -> bool:
        """running -> failed with the error kept. False when the task is no longer running.

        *provenance* carries the usage of a call that failed after it was billed; it adds to the
        task's billed totals like a finished call.
        """
        with self._session_factory.begin() as db:
            row = db.get(MemoryTaskRow, task_id, with_for_update=True)
            if row is None or row.status != TaskStatus.running:
                return False
            row.status = TaskStatus.failed.value
            row.error = error
            row.finished_at = now
            if provenance is not None:
                _add_billing(row, provenance, now)
                row.provenance = provenance
            return True

    def spend(self, user: str, since: datetime) -> Spend:
        """Committed spend in a window: what tasks billed since *since* over all their attempts, plus
        every running task at its estimate, a reservation that keeps parallel claims from
        overshooting a limit.

        ponytail: a task's billed totals count in the window of its latest billed finish, so a
        failure yesterday plus a retry today lands entirely in today. Per-attempt rows if exact
        windows ever matter.
        """
        with self._session_factory() as db:
            tokens, micro_usd = db.execute(
                select(
                    func.coalesce(func.sum(MemoryTaskRow.billed_input_tokens), 0),
                    func.coalesce(func.sum(MemoryTaskRow.billed_cost_micro_usd), 0),
                ).where(MemoryTaskRow.user == user, MemoryTaskRow.billed_at >= since)
            ).one()
            reservations = db.scalars(
                select(MemoryTaskRow.estimate).where(
                    MemoryTaskRow.user == user, MemoryTaskRow.status == TaskStatus.running
                )
            ).all()
        total = Spend(Decimal(micro_usd) / _MICRO, tokens)
        for estimate in reservations:
            if estimate is not None:
                total = total.plus(estimate)
        return total

    def queued_spend(self, user: str) -> Spend:
        """The estimates of the user's queued tasks: spend that is promised but not yet claimed."""
        with self._session_factory() as db:
            estimates = db.scalars(
                select(MemoryTaskRow.estimate).where(
                    MemoryTaskRow.user == user, MemoryTaskRow.status == TaskStatus.queued
                )
            ).all()
        total = Spend()
        for estimate in estimates:
            if estimate is not None:
                total = total.plus(estimate)
        return total

    def status_counts(self, user: str) -> tuple[dict[TaskStatus, int], int]:
        """Task count per status, and how many queued tasks the budget holds back."""
        with self._session_factory() as db:
            rows = db.execute(
                select(MemoryTaskRow.status, func.count())
                .where(MemoryTaskRow.user == user)
                .group_by(MemoryTaskRow.status)
            ).all()
            blocked = db.scalar(
                select(func.count())
                .select_from(MemoryTaskRow)
                .where(
                    MemoryTaskRow.user == user,
                    MemoryTaskRow.status == TaskStatus.queued,
                    MemoryTaskRow.blocked_reason.is_not(None),
                )
            )
        counts = dict.fromkeys(TaskStatus, 0) | {TaskStatus(status): count for status, count in rows}
        return counts, blocked or 0

    def open_tasks(self, user: str, kind: TaskKind) -> dict[str, MemoryTask]:
        """Open tasks of a kind by target, for the spawner."""
        with self._session_factory() as db:
            rows = db.scalars(
                select(MemoryTaskRow).where(
                    MemoryTaskRow.user == user, MemoryTaskRow.kind == kind, MemoryTaskRow.status.in_(_OPEN)
                )
            ).all()
        return {row.target: _task(row) for row in rows}

    def session_titles(self, session_ids: list[str]) -> dict[str, str | None]:
        """Titles of the given sessions, for task labels."""
        with self._session_factory() as db:
            rows = db.execute(
                select(SessionRow.session_id, SessionRow.title).where(SessionRow.session_id.in_(session_ids))
            ).all()
        return {session_id: title for session_id, title in rows}

    # --- session views ---

    def session_candidates(
        self,
        user: str,
        session_filter: SessionMemoryFilter,
        versions: CurrentVersions,
        session_id: str | None = None,
    ) -> list[SessionCandidate]:
        """The user's sessions with an event transcript, joined with their current extraction and
        latest extraction task, filtered and newest first.

        *versions* are what a fresh extraction would record; the ``outdated`` state and reasons are
        matched against the extraction's projection columns. Sessions without events (legacy, no
        timestamps) never appear.
        """
        extraction = MemorySessionExtractionRow
        latest_ids = (
            select(func.max(MemoryTaskRow.id).label("id"))
            .where(MemoryTaskRow.user == user, MemoryTaskRow.kind == TaskKind.session_extract)
            .group_by(MemoryTaskRow.target)
            .subquery()
        )
        task = (
            select(
                MemoryTaskRow.id,
                MemoryTaskRow.target,
                MemoryTaskRow.status,
                MemoryTaskRow.blocked_reason,
                MemoryTaskRow.week_key,
            )
            .join(latest_ids, latest_ids.c.id == MemoryTaskRow.id)
            .subquery()
        )
        week_key = func.coalesce(extraction.week_key, task.c.week_key)
        clauses: list[ColumnElement[bool]] = [
            SessionRow.user == user,
            SessionRow.state.is_not(None),
            exists().where(SessionEventRow.session_id == SessionRow.session_id),
            *_session_clauses(session_filter, versions, week_key, task.c.status),
        ]
        if session_id is not None:
            clauses.append(SessionRow.session_id == session_id)
        query = (
            select(
                SessionRow.state,
                SessionRow.title,
                SessionRow.channel_type,
                SessionRow.created_at,
                week_key,
                extraction.id,
                task.c.id,
                task.c.status,
                task.c.blocked_reason,
            )
            .outerjoin(
                extraction,
                and_(extraction.session_id == SessionRow.session_id, extraction.is_current.is_(True)),
            )
            .outerjoin(task, task.c.target == SessionRow.session_id)
            .where(*clauses)
            .order_by(SessionRow.created_at.desc(), SessionRow.session_id)
        )
        with self._session_factory() as db:
            rows = db.execute(query).all()
        return [_session_candidate(*row) for row in rows]

    def extractions_by_id(self, extraction_ids: list[int]) -> dict[int, ExtractionRecord]:
        with self._session_factory() as db:
            rows = db.scalars(
                select(MemorySessionExtractionRow).where(MemorySessionExtractionRow.id.in_(extraction_ids))
            ).all()
        return {row.id: ExtractionRecord.model_validate(row, from_attributes=True) for row in rows}

    def latest_tasks(self, user: str, kind: TaskKind) -> dict[str, MemoryTask]:
        """The newest task of *kind* per target, whatever its status."""
        latest_ids = (
            select(func.max(MemoryTaskRow.id))
            .where(MemoryTaskRow.user == user, MemoryTaskRow.kind == kind)
            .group_by(MemoryTaskRow.target)
        )
        with self._session_factory() as db:
            rows = db.scalars(select(MemoryTaskRow).where(MemoryTaskRow.id.in_(latest_ids))).all()
        return {row.target: _task(row) for row in rows}

    # --- extractions and facts ---

    def current_extraction(self, user: str, session_id: str) -> ExtractionRecord | None:
        with self._session_factory() as db:
            row = db.scalar(
                select(MemorySessionExtractionRow).where(
                    MemorySessionExtractionRow.user == user,
                    MemorySessionExtractionRow.session_id == session_id,
                    MemorySessionExtractionRow.is_current.is_(True),
                )
            )
            return ExtractionRecord.model_validate(row, from_attributes=True) if row is not None else None

    def extraction_history(self, user: str, session_id: str) -> list[ExtractionRecord]:
        """Non-current extractions of a session, newest first."""
        with self._session_factory() as db:
            rows = db.scalars(
                select(MemorySessionExtractionRow)
                .where(
                    MemorySessionExtractionRow.user == user,
                    MemorySessionExtractionRow.session_id == session_id,
                    MemorySessionExtractionRow.is_current.is_(False),
                )
                .order_by(MemorySessionExtractionRow.id.desc())
            ).all()
        return [ExtractionRecord.model_validate(row, from_attributes=True) for row in rows]

    def current_extractions(self, user: str, week_key: str | None = None) -> list[ExtractionRecord]:
        """Current extractions of the user, optionally of one week, in session order.

        Chronological by session, not by extraction: digests keep the later source on conflicts,
        and a re-extraction must not move an old session behind newer ones.
        """
        clauses = [MemorySessionExtractionRow.user == user, MemorySessionExtractionRow.is_current.is_(True)]
        if week_key is not None:
            clauses.append(MemorySessionExtractionRow.week_key == week_key)
        with self._session_factory() as db:
            rows = db.scalars(
                select(MemorySessionExtractionRow)
                .join(SessionRow, SessionRow.session_id == MemorySessionExtractionRow.session_id)
                .where(*clauses)
                .order_by(SessionRow.created_at, SessionRow.session_id)
            ).all()
        return [ExtractionRecord.model_validate(row, from_attributes=True) for row in rows]

    def purge_extractions(self, session_id: str) -> int:
        """Drop every extraction (and, by cascade, fact) of a session, e.g. once it turned private."""
        with self._session_factory.begin() as db:
            result = db.execute(
                delete(MemorySessionExtractionRow).where(MemorySessionExtractionRow.session_id == session_id)
            )
            return result.rowcount  # type: ignore[missing-attribute]

    def facts(self, user: str, fact_filter: FactFilter) -> list[FactView]:
        """Facts of current extractions, newest week first."""
        clauses = [MemoryFactRow.user == user, *_fact_clauses(fact_filter)]
        with self._session_factory() as db:
            rows = db.execute(
                select(MemoryFactRow, SessionRow.title)
                .join(SessionRow, SessionRow.session_id == MemoryFactRow.session_id)
                .where(*clauses)
                .order_by(MemoryFactRow.week_key.desc(), MemoryFactRow.id)
            ).all()
        return [FactView.model_validate(_fact_view_fields(fact) | {"session_title": title}) for fact, title in rows]

    # --- digests ---

    def current_digest(self, user: str, level: DigestLevel, period_key: str) -> DigestRecord | None:
        digests = self.current_digests(user, level, [period_key])
        return digests[0] if digests else None

    def current_digests(
        self, user: str, level: DigestLevel, period_keys: list[str] | None = None
    ) -> list[DigestRecord]:
        """Current digests of a level, optionally restricted to some periods, oldest period first."""
        clauses = [
            MemoryDigestRow.user == user,
            MemoryDigestRow.level == level,
            MemoryDigestRow.is_current.is_(True),
        ]
        if period_keys is not None:
            clauses.append(MemoryDigestRow.period_key.in_(period_keys))
        with self._session_factory() as db:
            rows = db.scalars(select(MemoryDigestRow).where(*clauses).order_by(MemoryDigestRow.period_key)).all()
        return [DigestRecord.model_validate(row, from_attributes=True) for row in rows]

    def digest_history(self, user: str, level: DigestLevel, period_key: str) -> list[DigestRecord]:
        """Non-current digests of a period, newest first."""
        with self._session_factory() as db:
            rows = db.scalars(
                select(MemoryDigestRow)
                .where(
                    MemoryDigestRow.user == user,
                    MemoryDigestRow.level == level,
                    MemoryDigestRow.period_key == period_key,
                    MemoryDigestRow.is_current.is_(False),
                )
                .order_by(MemoryDigestRow.id.desc())
            ).all()
        return [DigestRecord.model_validate(row, from_attributes=True) for row in rows]


_MICRO = Decimal(1_000_000)
_UNBILLED = {"attempts": 0, "billed_input_tokens": 0, "billed_output_tokens": 0, "billed_cost_micro_usd": 0}


def _add_billing(row: MemoryTaskRow, provenance: Provenance, now: datetime) -> None:
    row.billed_input_tokens += provenance.input_tokens
    row.billed_output_tokens += provenance.output_tokens
    if provenance.cost_usd is not None:
        row.billed_cost_micro_usd += int((provenance.cost_usd * _MICRO).to_integral_value(ROUND_HALF_UP))
    row.billed_at = now


def _task(row: MemoryTaskRow) -> MemoryTask:
    return MemoryTask.model_validate(row, from_attributes=True)


def _fact_view_fields(row: MemoryFactRow) -> dict[str, object]:
    return {name: getattr(row, name) for name in FactView.model_fields if name != "session_title"}


def parse_cursor(cursor: str) -> int:
    if not cursor.isdigit():
        raise ValueError(f"invalid cursor {cursor!r}")
    return int(cursor)


def _filter_clauses(task_filter: TaskFilter) -> list[ColumnElement[bool]]:
    clauses: list[ColumnElement[bool]] = []
    if task_filter.status:
        clauses.append(MemoryTaskRow.status.in_([s.value for s in task_filter.status]))
    if task_filter.kind:
        clauses.append(MemoryTaskRow.kind.in_([k.value for k in task_filter.kind]))
    if task_filter.period:
        # Week and month keys never collide (2026-W36 vs 2026-09), so one OR serves both.
        clauses.append(or_(MemoryTaskRow.week_key == task_filter.period, MemoryTaskRow.month_key == task_filter.period))
    if task_filter.model:
        clauses.append(MemoryTaskRow.model == task_filter.model)
    return clauses


def _session_candidate(
    state: SessionState | None,
    title: str | None,
    channel_type: str,
    created_at: datetime,
    week_key: str | None,
    extraction_id: int | None,
    task_id: int | None,
    task_status: str | None,
    blocked_reason: str | None,
) -> SessionCandidate:
    if state is None:
        raise ValueError("session candidates are selected with a state")
    task = None
    if task_id is not None and task_status is not None:
        task = TaskRef(
            id=task_id,
            status=TaskStatus(task_status),
            blocked_reason=BlockedReason(blocked_reason) if blocked_reason is not None else None,
        )
    return SessionCandidate(
        state=state,
        title=title,
        channel_type=channel_type,
        created_at=created_at,
        week_key=week_key,
        extraction_id=extraction_id,
        task=task,
    )


def _session_clauses(
    session_filter: SessionMemoryFilter,
    versions: CurrentVersions,
    week_key: ColumnElement[str],
    task_status: ColumnElement[str | None],
) -> list[ColumnElement[bool]]:
    extraction = MemorySessionExtractionRow
    differs = {
        OutdatedReason.prompt_version: extraction.prompt_version != versions.prompt_version,
        OutdatedReason.model: extraction.model != versions.model,
        OutdatedReason.input_format_version: extraction.input_format_version != versions.input_format_version,
    }
    outdated = or_(*differs.values())
    by_state = {
        ExtractionState.missing: extraction.id.is_(None),
        ExtractionState.current: and_(extraction.id.is_not(None), not_(outdated)),
        ExtractionState.outdated: and_(extraction.id.is_not(None), outdated),
    }
    clauses: list[ColumnElement[bool]] = []
    if session_filter.week:
        clauses.append(week_key == session_filter.week)
    if session_filter.state:
        clauses.append(or_(*(by_state[state] for state in session_filter.state)))
    if session_filter.outdated_reason:
        clauses.append(differs[session_filter.outdated_reason])
    if session_filter.task_status:
        clauses.append(task_status.in_([s.value for s in session_filter.task_status]))
    if session_filter.model:
        clauses.append(extraction.model == session_filter.model)
    if session_filter.channel:
        clauses.append(SessionRow.channel_type == session_filter.channel)
    return clauses


def _fact_clauses(fact_filter: FactFilter) -> list[ColumnElement[bool]]:
    clauses: list[ColumnElement[bool]] = []
    if fact_filter.category:
        clauses.append(MemoryFactRow.category.in_([c.value for c in fact_filter.category]))
    if fact_filter.subject:
        clauses.append(MemoryFactRow.subject == fact_filter.subject)
    if fact_filter.confidence:
        clauses.append(MemoryFactRow.confidence.in_([c.value for c in fact_filter.confidence]))
    if fact_filter.durability:
        clauses.append(MemoryFactRow.durability.in_([d.value for d in fact_filter.durability]))
    if fact_filter.source_kind:
        clauses.append(MemoryFactRow.source_kind.in_([k.value for k in fact_filter.source_kind]))
    if fact_filter.period:
        clauses.append(MemoryFactRow.week_key.in_(period_weeks(fact_filter.period)))
    return clauses


def _selected_ids(db: Session, user: str, selection: TaskSelection, statuses: set[TaskStatus]) -> list[int]:
    clauses = [MemoryTaskRow.user == user, MemoryTaskRow.status.in_([s.value for s in statuses])]
    if selection.ids is not None:
        clauses.append(MemoryTaskRow.id.in_(selection.ids))
    if selection.filter is not None:
        clauses.extend(_filter_clauses(selection.filter))
    query = select(MemoryTaskRow.id).where(*clauses).order_by(*_NEWEST_FIRST)
    if selection.newest is not None:
        query = query.limit(selection.newest)
    return list(db.scalars(query).all())


def _write_extraction(db: Session, user: str, result: ExtractionResult, outcome: TaskOutcome, now: datetime) -> int:
    provenance = outcome.provenance
    if provenance is None:
        raise ValueError("extraction outcomes need provenance")
    db.execute(
        update(MemorySessionExtractionRow)
        .where(
            MemorySessionExtractionRow.session_id == result.session_id,
            MemorySessionExtractionRow.is_current.is_(True),
        )
        .values(is_current=False)
    )
    # Facts project the current extraction only.
    db.execute(delete(MemoryFactRow).where(MemoryFactRow.session_id == result.session_id))
    row = MemorySessionExtractionRow(
        user=user,
        session_id=result.session_id,
        week_key=result.week_key,
        month_key=result.month_key,
        is_current=True,
        input_hash=provenance.input_hash,
        model=provenance.model,
        prompt_version=provenance.prompt_version,
        input_format_version=provenance.input_format_version,
        provenance=provenance,
        extraction=result.extraction,
        created_at=now,
    )
    db.add(row)
    db.flush()
    db.add_all(
        MemoryFactRow(
            user=user,
            extraction_id=row.id,
            session_id=result.session_id,
            category=fact.category.value,
            subject=fact.subject,
            statement=fact.statement,
            source_kind=fact.source_kind.value,
            confidence=fact.confidence.value,
            durability=fact.durability.value,
            valid_until=fact.valid_until,
            source_seqs=fact.source_seqs,
            week_key=result.week_key,
            created_at=now,
        )
        for fact in result.extraction.facts
    )
    return row.id


def _write_digest(db: Session, user: str, result: DigestResult, outcome: TaskOutcome, now: datetime) -> int:
    provenance = outcome.provenance
    if provenance is None:
        raise ValueError("digest outcomes need provenance")
    db.execute(
        update(MemoryDigestRow)
        .where(
            MemoryDigestRow.user == user,
            MemoryDigestRow.level == result.level,
            MemoryDigestRow.period_key == result.period_key,
            MemoryDigestRow.is_current.is_(True),
        )
        .values(is_current=False)
    )
    row = MemoryDigestRow(
        user=user,
        level=result.level.value,
        period_key=result.period_key,
        is_current=True,
        coverage=[entry.model_dump() for entry in result.coverage],
        coverage_hash=result.coverage_hash,
        model=provenance.model,
        prompt_version=provenance.prompt_version,
        input_format_version=provenance.input_format_version,
        provenance=provenance,
        digest=result.digest,
        created_at=now,
    )
    db.add(row)
    db.flush()
    return row.id
