from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from croniter import croniter
from sqlalchemy import delete, select, update

from .database.engine import SessionFactory
from .database.models import JobRow
from .models.jobs import JobCronTrigger, JobDefinition, JobsFile

JobTriggerKind = Literal["api", "cron", "manual"]


@dataclass(frozen=True, slots=True)
class ScheduledJobRun:
    job: JobDefinition
    trigger: JobCronTrigger
    scheduled_at: datetime


def build_job_run_message(
    job: JobDefinition,
    *,
    trigger_kind: JobTriggerKind,
    triggered_at: datetime,
    payload: str | None = None,
    cron_expression: str | None = None,
    timezone: str | None = None,
) -> str:
    title = job.name if job.name else job.id
    tz = ZoneInfo(timezone) if timezone else UTC
    iso_time = triggered_at.astimezone(tz).isoformat()

    match trigger_kind:
        case "cron":
            trigger_sentence = (
                f"The job was triggered automatically at {iso_time} due to cron rule `{cron_expression}` on the job."
            )
        case "manual":
            trigger_sentence = f"The job was triggered manually at {iso_time}."
        case "api":
            trigger_sentence = f"The job was triggered via the API at {iso_time}."
        case _:
            trigger_sentence = f"The job was triggered at {iso_time}."

    sections = [
        f"This is an invocation of job `{job.id}` ({title}).",
        "",
        f"Job instructions: {job.prompt.rstrip()}",
        "",
        trigger_sentence,
    ]

    if payload:
        sections.append(f"\nThe following additional data was supplied for this invocation:\n\n{payload}")

    return "\n".join(sections).strip()


def _job_columns(job: JobDefinition) -> dict[str, object]:
    """Column values for a job row: the full definition plus its queryable projections."""
    return {
        "id": job.id,
        "user": job.user,
        "enabled": job.enabled,
        "name": job.name,
        "prompt": job.prompt,
        "memory_enabled": job.memory_enabled,
        "data": job,
    }


def _job_to_row(job: JobDefinition) -> JobRow:
    return JobRow(**_job_columns(job))


def _row_to_job(row: JobRow) -> JobDefinition:
    return row.data


class JobsStore:
    def __init__(self, session_factory: SessionFactory):
        self._session_factory = session_factory

    def load(self) -> JobsFile:
        return JobsFile(jobs=self.list_jobs())

    def save(self, jobs_file: JobsFile) -> JobsFile:
        """Replace the full job set (bulk operations)."""
        with self._session_factory.begin() as db:
            db.execute(delete(JobRow))
            db.add_all(_job_to_row(job) for job in jobs_file.jobs)
        return jobs_file

    def list_jobs(self) -> list[JobDefinition]:
        with self._session_factory() as db:
            rows = db.scalars(select(JobRow).order_by(JobRow.id)).all()
        return [_row_to_job(row) for row in rows]

    def list_jobs_for_user(self, user: str) -> list[JobDefinition]:
        with self._session_factory() as db:
            rows = db.scalars(select(JobRow).where(JobRow.user == user).order_by(JobRow.id)).all()
        return [_row_to_job(row) for row in rows]

    def get_job(self, job_id: str) -> JobDefinition | None:
        with self._session_factory() as db:
            row = db.get(JobRow, job_id)
            return _row_to_job(row) if row is not None else None

    def get_job_for_user(self, job_id: str, user: str) -> JobDefinition | None:
        job = self.get_job(job_id)
        if job is None or job.user != user:
            return None
        return job

    def create_job(self, job: JobDefinition) -> JobDefinition:
        with self._session_factory.begin() as db:
            if db.get(JobRow, job.id) is not None:
                raise ValueError(f"Job {job.id!r} already exists")
            db.add(_job_to_row(job))
        return job

    def update_job(self, job_id: str, job: JobDefinition) -> JobDefinition:
        with self._session_factory.begin() as db:
            result = db.execute(update(JobRow).where(JobRow.id == job_id).values(**_job_columns(job)))
            if result.rowcount == 0:  # type: ignore[missing-attribute]
                raise KeyError(job_id)
        return job

    def delete_job(self, job_id: str) -> bool:
        with self._session_factory.begin() as db:
            result = db.execute(delete(JobRow).where(JobRow.id == job_id))
            return result.rowcount > 0  # type: ignore[missing-attribute]


class JobsScheduler:
    def __init__(self, store: JobsStore, *, max_trigger_backfill: int = 100):
        self._store = store
        self._max_trigger_backfill = max_trigger_backfill
        self._last_checked_at: datetime | None = None

    @property
    def last_checked_at(self) -> datetime | None:
        return self._last_checked_at

    def collect_due_runs(self, *, now: datetime | None = None) -> list[ScheduledJobRun]:
        now = now or datetime.now(tz=UTC)
        if self._last_checked_at is None:
            self._last_checked_at = now
            return []
        if now <= self._last_checked_at:
            return []

        due_runs: list[ScheduledJobRun] = []
        for job in self._store.list_jobs():
            if not job.enabled:
                continue
            for trigger in job.triggers:
                due_runs.extend(
                    self._collect_due_runs_for_trigger(
                        job,
                        trigger,
                        since=self._last_checked_at,
                        now=now,
                    )
                )

        self._last_checked_at = now
        return sorted(due_runs, key=lambda run: run.scheduled_at)

    def _collect_due_runs_for_trigger(
        self,
        job: JobDefinition,
        trigger: JobCronTrigger,
        *,
        since: datetime,
        now: datetime,
    ) -> list[ScheduledJobRun]:
        timezone = ZoneInfo(trigger.timezone or "UTC")
        since_local = since.astimezone(timezone)
        now_local = now.astimezone(timezone)
        if now_local <= since_local:
            return []

        due_runs: list[ScheduledJobRun] = []
        if (
            now_local.microsecond == 0
            and croniter.match(trigger.expression, now_local, precision_in_seconds=1)
            and now_local > since_local
        ):
            due_runs.append(
                ScheduledJobRun(
                    job=job,
                    trigger=trigger,
                    scheduled_at=now_local.astimezone(UTC),
                )
            )

        iterator = croniter(trigger.expression, now_local)
        for _ in range(self._max_trigger_backfill):
            scheduled_local = iterator.get_prev(datetime)
            if scheduled_local <= since_local:
                break
            due_runs.append(
                ScheduledJobRun(
                    job=job,
                    trigger=trigger,
                    scheduled_at=scheduled_local.astimezone(UTC),
                )
            )

        due_runs.reverse()
        return due_runs
