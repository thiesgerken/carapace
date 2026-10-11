from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from carapace.database.models import JobRow
from carapace.jobs import JobsScheduler, JobsStore, build_job_run_message
from carapace.models.jobs import JobDefinition


def test_jobs_store_roundtrip(db_factory):
    store = JobsStore(db_factory)
    job = JobDefinition(user="thies", id="daily", name="Daily", prompt="Summarize.")

    store.create_job(job)

    loaded = store.load()
    assert [entry.id for entry in loaded.jobs] == ["daily"]


def test_jobs_store_update_keeps_memory_enabled_projection(db_factory):
    store = JobsStore(db_factory)
    job = JobDefinition(user="thies", id="daily", name="Daily", prompt="Summarize.")
    store.create_job(job)

    store.update_job("daily", job.model_copy(update={"memory_enabled": True}))

    with db_factory() as db:
        assert db.scalar(select(JobRow.memory_enabled).where(JobRow.id == "daily")) is True


def test_archive_previous_sessions_conflicts_with_persistent_session():
    with pytest.raises(ValidationError, match="archive_previous_sessions"):
        JobDefinition(
            user="thies",
            id="daily",
            name="Daily",
            prompt="Summarize.",
            unattended=False,
            persistent_session_id="sess-1",
            archive_previous_sessions=True,
        )


def test_build_job_run_message_includes_trigger_context_and_payload():
    job = JobDefinition(user="thies", id="daily", name="Daily", prompt="Summarize.")

    message = build_job_run_message(
        job,
        trigger_kind="api",
        triggered_at=datetime(2026, 5, 9, 10, 30, tzinfo=UTC),
        payload='{"items":3}',
    )

    assert "daily" in message
    assert "Daily" in message
    assert "Summarize." in message
    assert "triggered via the API" in message
    assert "2026-05-09T10:30:00+00:00" in message
    assert "additional data was supplied" in message
    assert '{"items":3}' in message


def test_build_job_run_message_manual_trigger():
    job = JobDefinition(user="thies", id="report", name="Report", prompt="Generate report.")

    message = build_job_run_message(
        job,
        trigger_kind="manual",
        triggered_at=datetime(2026, 5, 9, 10, 30, tzinfo=UTC),
    )

    assert "report" in message
    assert "Report" in message
    assert "Generate report." in message
    assert "triggered manually" in message
    assert "2026-05-09T10:30:00+00:00" in message


def test_build_job_run_message_cron_trigger():
    job = JobDefinition(user="thies", id="nightly", name="Nightly", prompt="Archive old items.")

    message = build_job_run_message(
        job,
        trigger_kind="cron",
        triggered_at=datetime(2026, 5, 9, 0, 0, tzinfo=UTC),
        cron_expression="0 2 * * *",
        timezone="Europe/Berlin",
    )

    assert "nightly" in message
    assert "Archive old items." in message
    assert "triggered automatically" in message
    assert "0 2 * * *" in message
    # UTC midnight = 02:00 Europe/Berlin (CEST), displayed as ISO with +02:00
    assert "2026-05-09T02:00:00+02:00" in message
    assert "additional data" not in message


def test_jobs_scheduler_skips_first_scan(db_factory):
    store = JobsStore(db_factory)
    store.create_job(
        JobDefinition.model_validate(
            {
                "id": "daily",
                "user": "thies",
                "name": "Daily",
                "prompt": "Summarize.",
                "triggers": [{"expression": "* * * * *"}],
            }
        )
    )
    scheduler = JobsScheduler(store)

    due_runs = scheduler.collect_due_runs(now=datetime(2026, 5, 9, 10, 0, tzinfo=UTC))

    assert due_runs == []


def test_jobs_scheduler_collects_due_runs_once_per_window(db_factory):
    store = JobsStore(db_factory)
    store.create_job(
        JobDefinition.model_validate(
            {
                "id": "daily",
                "user": "thies",
                "name": "Daily",
                "prompt": "Summarize.",
                "triggers": [{"expression": "* * * * *"}],
            }
        )
    )
    scheduler = JobsScheduler(store)

    start = datetime(2026, 5, 9, 10, 0, tzinfo=UTC)
    assert scheduler.collect_due_runs(now=start) == []

    due_runs = scheduler.collect_due_runs(now=start + timedelta(minutes=1, seconds=5))

    assert len(due_runs) == 1
    assert due_runs[0].job.id == "daily"
    assert due_runs[0].scheduled_at == datetime(2026, 5, 9, 10, 1, tzinfo=UTC)

    assert scheduler.collect_due_runs(now=start + timedelta(minutes=1, seconds=30)) == []


def test_jobs_scheduler_collects_due_run_on_exact_now_boundary(db_factory):
    store = JobsStore(db_factory)
    store.create_job(
        JobDefinition.model_validate(
            {
                "id": "daily",
                "user": "thies",
                "name": "Daily",
                "prompt": "Summarize.",
                "triggers": [{"expression": "* * * * *"}],
            }
        )
    )
    scheduler = JobsScheduler(store)

    start = datetime(2026, 5, 9, 10, 0, tzinfo=UTC)
    assert scheduler.collect_due_runs(now=start) == []

    due_runs = scheduler.collect_due_runs(now=start + timedelta(minutes=1))

    assert len(due_runs) == 1
    assert due_runs[0].job.id == "daily"
    assert due_runs[0].scheduled_at == datetime(2026, 5, 9, 10, 1, tzinfo=UTC)


def test_jobs_scheduler_does_not_duplicate_run_near_exact_boundary(db_factory):
    store = JobsStore(db_factory)
    store.create_job(
        JobDefinition.model_validate(
            {
                "id": "daily",
                "user": "thies",
                "name": "Daily",
                "prompt": "Summarize.",
                "triggers": [{"expression": "* * * * *"}],
            }
        )
    )
    scheduler = JobsScheduler(store)

    start = datetime(2026, 5, 9, 10, 0, tzinfo=UTC)
    assert scheduler.collect_due_runs(now=start) == []

    due_runs = scheduler.collect_due_runs(now=datetime(2026, 5, 9, 10, 1, 0, 300000, tzinfo=UTC))

    assert len(due_runs) == 1
    assert due_runs[0].scheduled_at == datetime(2026, 5, 9, 10, 1, tzinfo=UTC)


def test_jobs_scheduler_does_not_regress_checkpoint_when_clock_moves_backwards(db_factory):
    store = JobsStore(db_factory)
    store.create_job(
        JobDefinition.model_validate(
            {
                "id": "daily",
                "user": "thies",
                "name": "Daily",
                "prompt": "Summarize.",
                "triggers": [{"expression": "* * * * *"}],
            }
        )
    )
    scheduler = JobsScheduler(store)

    start = datetime(2026, 5, 9, 10, 0, tzinfo=UTC)
    assert scheduler.collect_due_runs(now=start) == []
    due_runs = scheduler.collect_due_runs(now=start + timedelta(minutes=5))

    assert [run.scheduled_at for run in due_runs] == [
        datetime(2026, 5, 9, 10, 1, tzinfo=UTC),
        datetime(2026, 5, 9, 10, 2, tzinfo=UTC),
        datetime(2026, 5, 9, 10, 3, tzinfo=UTC),
        datetime(2026, 5, 9, 10, 4, tzinfo=UTC),
        datetime(2026, 5, 9, 10, 5, tzinfo=UTC),
    ]

    assert scheduler.collect_due_runs(now=start + timedelta(minutes=4)) == []
    assert scheduler.collect_due_runs(now=start + timedelta(minutes=6)) == [
        due_runs[0].__class__(
            job=due_runs[0].job,
            trigger=due_runs[0].trigger,
            scheduled_at=datetime(2026, 5, 9, 10, 6, tzinfo=UTC),
        )
    ]


def test_jobs_scheduler_honors_trigger_timezone(db_factory):
    store = JobsStore(db_factory)
    store.create_job(
        JobDefinition.model_validate(
            {
                "id": "berlin-morning",
                "user": "thies",
                "name": "Berlin Morning",
                "prompt": "Summarize.",
                "triggers": [{"expression": "0 9 * * *", "timezone": "Europe/Berlin"}],
            }
        )
    )
    scheduler = JobsScheduler(store)

    assert scheduler.collect_due_runs(now=datetime(2026, 5, 9, 6, 55, tzinfo=UTC)) == []

    due_runs = scheduler.collect_due_runs(now=datetime(2026, 5, 9, 7, 5, tzinfo=UTC))

    assert len(due_runs) == 1
    assert due_runs[0].scheduled_at == datetime(2026, 5, 9, 7, 0, tzinfo=UTC)
