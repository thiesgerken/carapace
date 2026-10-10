from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import delete, func, select

from carapace.database.models import MemoryFactRow, MemorySessionExtractionRow, SessionRow, User
from carapace.memory.budget import Spend
from carapace.memory.models import (
    BlockedReason,
    CoverageEntry,
    DigestLevel,
    DigestResult,
    ExtractionResult,
    Fact,
    FactFilter,
    MemoryTask,
    MirrorResult,
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
from carapace.memory.store import MemoryStore
from carapace.models.user import UserConfig

NOW = datetime(2026, 9, 10, 12, tzinfo=UTC)


@pytest.fixture
def store(db_factory) -> MemoryStore:
    with db_factory.begin() as db:
        for name in ("alice", "bob"):
            db.add(
                User(
                    username=name,
                    password_hash="x",
                    config=UserConfig(),
                    created_at=NOW,
                    updated_at=NOW,
                    password_changed_at=NOW,
                )
            )
        db.flush()
        for session_id, user in (("s1", "alice"), ("s2", "alice"), ("s3", "alice"), ("b1", "bob")):
            db.add(
                SessionRow(
                    session_id=session_id,
                    user=user,
                    channel_type="web",
                    title=f"title {session_id}",
                    created_at=NOW,
                    last_active=NOW,
                )
            )
    return MemoryStore(db_factory)


def _get(store: MemoryStore, user: str, task_id: int) -> MemoryTask | None:
    """One task of the user, whatever its status, through the regular selection reader."""
    tasks = store.select_tasks(user, TaskSelection(ids=[task_id]), set(TaskStatus))
    return tasks[0] if tasks else None


def _estimate(cost: str = "0.01", model: str = "test:low") -> TaskEstimate:
    return TaskEstimate(model=model, input_tokens=1000, output_tokens_cap=100, cost_usd=Decimal(cost))


def _spawn_extract(store: MemoryStore, session_id: str, week: str = "2026-W37", user: str = "alice"):
    task = store.spawn(
        user,
        TaskKind.session_extract,
        session_id,
        spawned_by=SpawnedBy.auto,
        now=NOW,
        session_week_key=week,
        estimate=_estimate(),
    )
    assert task is not None
    return task


def _provenance(task_id: int, cost: str | None = "0.02", model: str = "test:low") -> Provenance:
    return Provenance(
        carapace_version="0.0.0",
        model=model,
        prompt_version="p1",
        input_format_version=1,
        input_hash=f"hash-{task_id}",
        input_tokens=1200,
        output_tokens=300,
        cost_usd=Decimal(cost) if cost else None,
        duration_ms=10,
        task_id=task_id,
        created_at=NOW,
    )


def _extraction(*statements: str) -> SessionExtraction:
    facts = [
        Fact(
            category="user",
            statement=s,
            source_seqs=[1],
            source_kind="user_said",
            confidence="high",
            durability="durable",
        )
        for s in statements
    ]
    return SessionExtraction(abstract="a", outcomes=[], open_loops=[], on_my_mind=[], facts=facts, friction=[], tags=[])


def _run_to_running(store: MemoryStore, task_id: int, user: str = "alice") -> None:
    assert store.run(user, TaskSelection(ids=[task_id]), None, NOW) == 1
    assert store.claim(task_id, NOW)


def _finish_extraction(store: MemoryStore, session_id: str, *statements: str, week: str = "2026-W37") -> int:
    task = _spawn_extract(store, session_id, week)
    _run_to_running(store, task.id)
    result = ExtractionResult(
        session_id=session_id, week_key=week, month_key="2026-09", extraction=_extraction(*statements)
    )
    assert store.record_outcome(task.id, TaskOutcome(provenance=_provenance(task.id), result=result), NOW)
    return task.id


def test_spawn_derives_periods_and_replaces_pending(store: MemoryStore):
    first = _spawn_extract(store, "s1", "2026-W40")
    assert (first.week_key, first.month_key, first.model) == ("2026-W40", "2026-10", "test:low")

    again = store.spawn(
        "alice",
        TaskKind.session_extract,
        "s1",
        spawned_by=SpawnedBy.manual,
        now=NOW,
        session_week_key="2026-W40",
        estimate=_estimate(model="test:high"),
        model_override="test:high",
    )
    assert again is not None and again.id == first.id
    assert (again.spawned_by, again.model_override, again.model) == (SpawnedBy.manual, "test:high", "test:high")

    week = store.spawn(
        "alice",
        TaskKind.week_digest,
        "2026-W36",
        spawned_by=SpawnedBy.auto,
        now=NOW,
        estimate=_estimate(model="test:high"),
    )
    month = store.spawn(
        "alice",
        TaskKind.month_digest,
        "2026-09",
        spawned_by=SpawnedBy.auto,
        now=NOW,
        estimate=_estimate(model="test:high"),
    )
    assert week is not None and (week.week_key, week.month_key) == ("2026-W36", "2026-09")
    assert month is not None and (month.week_key, month.month_key) == (None, "2026-09")

    with pytest.raises(ValueError, match="week key"):
        store.spawn("alice", TaskKind.session_extract, "s2", spawned_by=SpawnedBy.auto, now=NOW, estimate=_estimate())
    # LLM tasks never go unestimated (that would bypass the budget gate); mirrors never get one.
    with pytest.raises(ValueError, match="estimate"):
        store.spawn("alice", TaskKind.week_digest, "2026-W37", spawned_by=SpawnedBy.auto, now=NOW)
    with pytest.raises(ValueError, match="estimate"):
        store.spawn("alice", TaskKind.mirror, "alice", spawned_by=SpawnedBy.auto, now=NOW, estimate=_estimate())


def test_spawn_leaves_queued_and_running_tasks_alone(store: MemoryStore):
    def respawn():
        return store.spawn(
            "alice",
            TaskKind.session_extract,
            "s1",
            spawned_by=SpawnedBy.auto,
            now=NOW,
            session_week_key="2026-W37",
            estimate=_estimate(),
        )

    task = _spawn_extract(store, "s1")
    store.run("alice", TaskSelection(ids=[task.id]), None, NOW)
    assert respawn() is None
    store.claim(task.id, NOW)
    assert respawn() is None


def test_spawn_after_finish_creates_a_new_task(store: MemoryStore):
    done_id = _finish_extraction(store, "s1", "likes tea")
    again = _spawn_extract(store, "s1")
    assert again.id != done_id and again.status is TaskStatus.pending


def test_period_filter_resolves_sessions_through_their_week(store: MemoryStore):
    sept = _spawn_extract(store, "s1", "2026-W36")  # Aug 31 to Sep 6: September
    aug = _spawn_extract(store, "s2", "2026-W35")
    digest = store.spawn(
        "alice",
        TaskKind.week_digest,
        "2026-W36",
        spawned_by=SpawnedBy.auto,
        now=NOW,
        estimate=_estimate(model="test:high"),
    )
    assert digest is not None

    september = TaskFilter(period="2026-09")
    assert {t.id for t in store.list_tasks("alice", september, None, 50).items} == {sept.id, digest.id}
    assert {t.id for t in store.list_tasks("alice", TaskFilter(period="2026-W35"), None, 50).items} == {aug.id}
    # Run, cancel and estimate selections resolve the filter identically.
    selection = TaskSelection(filter=september)
    assert {t.id for t in store.select_tasks("alice", selection, {TaskStatus.pending})} == {sept.id, digest.id}
    assert store.run("alice", selection, None, NOW) == 2
    assert store.cancel("alice", selection, NOW) == 2


def test_run_newest_n_and_model_override(store: MemoryStore):
    old = _spawn_extract(store, "s1", "2026-W30")
    new = _spawn_extract(store, "s2", "2026-W37")
    mid = _spawn_extract(store, "s3", "2026-W33")

    assert store.run("alice", TaskSelection(filter=TaskFilter(), newest=2), "test:high", NOW) == 2
    tasks = {t.id: t for t in store.list_tasks("alice", TaskFilter(), None, 50).items}
    assert tasks[old.id].status is TaskStatus.pending
    assert tasks[new.id].status is TaskStatus.queued and tasks[new.id].model == "test:high"
    assert tasks[mid.id].status is TaskStatus.queued and tasks[mid.id].queued_at == NOW


def test_selection_is_scoped_to_the_user(store: MemoryStore):
    bobs = _spawn_extract(store, "b1", user="bob")
    assert store.run("alice", TaskSelection(ids=[bobs.id]), None, NOW) == 0
    assert _get(store, "alice", bobs.id) is None
    assert _get(store, "bob", bobs.id) is not None


def test_list_tasks_paginates_in_run_newest_order(store: MemoryStore):
    mid = _spawn_extract(store, "s1", "2026-W33")
    new = _spawn_extract(store, "s2", "2026-W37")
    old = _spawn_extract(store, "s3", "2026-W30")
    page = store.list_tasks("alice", TaskFilter(), None, 2)
    assert [t.id for t in page.items] == [new.id, mid.id] and page.total == 3 and page.next_cursor is not None
    rest = store.list_tasks("alice", TaskFilter(), page.next_cursor, 2)
    assert [t.id for t in rest.items] == [old.id] and rest.next_cursor is None
    # The top N rows are exactly what "run newest N" queues.
    newest = store.select_tasks("alice", TaskSelection(filter=TaskFilter(), newest=2), {TaskStatus.pending})
    assert [t.id for t in newest] == [t.id for t in page.items]


def test_claim_is_atomic_and_counts_attempts(store: MemoryStore):
    task = _spawn_extract(store, "s1")
    assert not store.claim(task.id, NOW)  # pending, not queued
    store.run("alice", TaskSelection(ids=[task.id]), None, NOW)
    store.set_blocked(task.id, BlockedReason.budget)
    assert store.claim(task.id, NOW)
    assert not store.claim(task.id, NOW)
    claimed = _get(store, "alice", task.id)
    assert claimed is not None
    assert (claimed.status, claimed.attempts, claimed.blocked_reason) == (TaskStatus.running, 1, None)


def test_failure_retry_and_requeue(store: MemoryStore):
    task = _spawn_extract(store, "s1")
    _run_to_running(store, task.id)
    assert store.record_failure(task.id, "input too large", NOW)
    assert not store.record_failure(task.id, "again", NOW)
    failed = _get(store, "alice", task.id)
    assert failed is not None and (failed.status, failed.error) == (TaskStatus.failed, "input too large")

    assert store.retry("alice", [task.id], NOW) == 1
    assert store.claim(task.id, NOW)
    assert store.requeue_running() == 1
    requeued = _get(store, "alice", task.id)
    assert requeued is not None
    assert (requeued.status, requeued.attempts, requeued.error, requeued.started_at) == (
        TaskStatus.queued,
        2,
        None,
        None,
    )


def test_cancelled_running_task_discards_its_result(store: MemoryStore):
    task = _spawn_extract(store, "s1")
    _run_to_running(store, task.id)
    assert store.cancel("alice", TaskSelection(ids=[task.id]), NOW) == 1
    result = ExtractionResult(session_id="s1", week_key="2026-W37", month_key="2026-09", extraction=_extraction())
    assert not store.record_outcome(task.id, TaskOutcome(provenance=_provenance(task.id), result=result), NOW)
    assert store.current_extraction("alice", "s1") is None


def test_re_extraction_keeps_history_and_rewrites_facts(store: MemoryStore):
    first = _finish_extraction(store, "s1", "likes tea", "lives in Hamburg")
    second = _finish_extraction(store, "s1", "likes coffee")

    current = store.current_extraction("alice", "s1")
    assert current is not None and current.provenance.task_id == second
    assert [r.provenance.task_id for r in store.extraction_history("alice", "s1")] == [first]
    assert [f.statement for f in store.facts("alice", FactFilter())] == ["likes coffee"]

    done = _get(store, "alice", second)
    assert done is not None
    assert (done.status, done.result_id, done.model) == (TaskStatus.done, current.id, "test:low")


def test_facts_filters(store: MemoryStore):
    _finish_extraction(store, "s1", "early", week="2026-W36")
    _finish_extraction(store, "s2", "late", week="2026-W39")
    _finish_extraction(store, "s3", "october", week="2026-W40")

    def statements(**kwargs) -> list[str]:
        return [f.statement for f in store.facts("alice", FactFilter(**kwargs))]

    assert statements(period="2026-09") == ["late", "early"]
    assert statements(period="2026-W40") == ["october"]
    assert statements(category=["social"]) == []
    view = store.facts("alice", FactFilter(period="2026-W36"))[0]
    assert (view.session_title, view.source_seqs) == ("title s1", [1])


def test_purge_and_session_delete_cascade(store: MemoryStore, db_factory):
    _finish_extraction(store, "s1", "a")
    _finish_extraction(store, "s2", "b")

    assert store.purge_extractions("s1") == 1
    assert store.current_extraction("alice", "s1") is None
    with db_factory.begin() as db:
        db.execute(delete(SessionRow).where(SessionRow.session_id == "s2"))
    with db_factory() as db:
        assert db.scalar(select(func.count()).select_from(MemorySessionExtractionRow)) == 0
        assert db.scalar(select(func.count()).select_from(MemoryFactRow)) == 0


def test_digest_versions(store: MemoryStore):
    def finish_digest(summary: str) -> int:
        task = store.spawn(
            "alice",
            TaskKind.week_digest,
            "2026-W36",
            spawned_by=SpawnedBy.auto,
            now=NOW,
            estimate=_estimate(model="test:high"),
        )
        assert task is not None
        _run_to_running(store, task.id)
        result = DigestResult(
            level=DigestLevel.week,
            period_key="2026-W36",
            coverage=[CoverageEntry(source_id="s1", source_hash="h1")],
            coverage_hash="c",
            digest=PeriodDigest(summary=summary, on_my_mind=[], highlights=[], open_loops=[], learned=[]),
        )
        assert store.record_outcome(task.id, TaskOutcome(provenance=_provenance(task.id), result=result), NOW)
        return task.id

    finish_digest("first")
    finish_digest("second")
    current = store.current_digest("alice", DigestLevel.week, "2026-W36")
    assert current is not None and current.digest.summary == "second"
    assert current.coverage == [CoverageEntry(source_id="s1", source_hash="h1")]
    assert [d.digest.summary for d in store.digest_history("alice", DigestLevel.week, "2026-W36")] == ["first"]
    assert store.current_digests("alice", DigestLevel.week, ["2026-W37"]) == []


def test_mirror_outcome_has_no_record(store: MemoryStore):
    task = store.spawn("alice", TaskKind.mirror, "alice", spawned_by=SpawnedBy.auto, now=NOW)
    assert task is not None and task.estimate is None
    _run_to_running(store, task.id)
    assert store.record_outcome(task.id, TaskOutcome(provenance=None, result=MirrorResult(commit="abc")), NOW)
    done = _get(store, "alice", task.id)
    assert done is not None and (done.status, done.result_id) == (TaskStatus.done, None)


def test_spend_reserves_running_tasks_and_counts_billed_failures(store: MemoryStore):
    running = _spawn_extract(store, "s1")  # estimate 0.01, 1000 input tokens
    _run_to_running(store, running.id)
    assert store.spend("alice", NOW) == Spend(Decimal("0.01"), 1000)

    failed = _spawn_extract(store, "s2")
    _run_to_running(store, failed.id)
    assert store.record_failure(failed.id, "output validation failed", NOW, _provenance(failed.id, cost="0.03"))
    unbilled = _spawn_extract(store, "s3")
    _run_to_running(store, unbilled.id)
    assert store.record_failure(unbilled.id, "input too large", NOW)
    # Running reservation 0.01 + billed failure 0.03; the unbilled failure costs nothing.
    assert store.spend("alice", NOW) == Spend(Decimal("0.04"), 2200)


def test_retry_keeps_what_earlier_attempts_billed(store: MemoryStore):
    task = _spawn_extract(store, "s1")
    _run_to_running(store, task.id)
    assert store.record_failure(task.id, "output validation failed", NOW, _provenance(task.id, cost="0.03"))
    billed_once = Spend(Decimal("0.03"), 1200)
    assert store.spend("alice", NOW) == billed_once

    assert store.retry("alice", [task.id], NOW) == 1
    assert store.spend("alice", NOW) == billed_once
    assert store.claim(task.id, NOW)
    result = ExtractionResult(session_id="s1", week_key="2026-W37", month_key="2026-09", extraction=_extraction())
    assert store.record_outcome(task.id, TaskOutcome(provenance=_provenance(task.id, cost="0.02"), result=result), NOW)
    assert store.spend("alice", NOW) == Spend(Decimal("0.05"), 2400)


def test_current_extractions_follow_session_order(store: MemoryStore, db_factory):
    with db_factory.begin() as db:
        for session_id, hours in (("s1", 0), ("s2", 1), ("s3", 2)):
            row = db.get(SessionRow, session_id)
            assert row is not None
            row.created_at = NOW + timedelta(hours=hours)
    _finish_extraction(store, "s1", "monday")
    _finish_extraction(store, "s2", "friday")
    _finish_extraction(store, "s1", "monday again")  # a re-extraction must not move s1 behind s2
    assert [r.session_id for r in store.current_extractions("alice", "2026-W37")] == ["s1", "s2"]


def test_spend_counts_finished_tasks_in_window(store: MemoryStore):
    _finish_extraction(store, "s1")  # costs 0.02, finished at NOW
    _finish_extraction(store, "s2")
    assert store.spend("alice", NOW).cost_usd == Decimal("0.04")
    assert store.spend("alice", NOW).input_tokens == 2400
    assert store.spend("alice", NOW + timedelta(seconds=1)).cost_usd == 0
    assert store.spend("bob", NOW).cost_usd == 0


def test_status_counts(store: MemoryStore):
    a = _spawn_extract(store, "s1")
    b = _spawn_extract(store, "s2")
    _spawn_extract(store, "s3")
    store.run("alice", TaskSelection(ids=[a.id, b.id]), None, NOW)
    store.set_blocked(b.id, BlockedReason.budget)
    counts, blocked = store.status_counts("alice")
    assert counts[TaskStatus.pending] == 1 and counts[TaskStatus.queued] == 2 and counts[TaskStatus.done] == 0
    assert blocked == 1


def test_queue_order(store: MemoryStore):
    old = _spawn_extract(store, "s1", "2026-W30")
    month = store.spawn(
        "alice",
        TaskKind.month_digest,
        "2026-09",
        spawned_by=SpawnedBy.auto,
        now=NOW,
        estimate=_estimate(model="test:high"),
    )
    week = store.spawn(
        "alice",
        TaskKind.week_digest,
        "2026-W36",
        spawned_by=SpawnedBy.auto,
        now=NOW,
        estimate=_estimate(model="test:high"),
    )
    new = _spawn_extract(store, "s2", "2026-W37")
    store.spawn("alice", TaskKind.mirror, "alice", spawned_by=SpawnedBy.auto, now=NOW)
    assert month is not None and week is not None

    promotion = [t.id for t in store.pending_for_promotion("alice", 10)]
    assert promotion == [new.id, old.id, week.id, month.id]

    store.run("alice", TaskSelection(ids=[new.id]), None, NOW + timedelta(minutes=1))
    store.run("alice", TaskSelection(ids=[old.id]), None, NOW)
    assert [t.id for t in store.next_queued(10)] == [old.id, new.id]
    assert set(store.open_tasks("alice", TaskKind.session_extract)) == {"s1", "s2"}


def test_extraction_needs_provenance(store: MemoryStore):
    task = _spawn_extract(store, "s1")
    _run_to_running(store, task.id)
    result = ExtractionResult(session_id="s1", week_key="2026-W37", month_key="2026-09", extraction=_extraction())
    with pytest.raises(ValueError, match="provenance"):
        store.record_outcome(task.id, TaskOutcome(provenance=None, result=result), NOW)
    still = _get(store, "alice", task.id)
    assert still is not None and still.status is TaskStatus.running


def test_fact_valid_until_roundtrip(store: MemoryStore):
    task = _spawn_extract(store, "s1")
    _run_to_running(store, task.id)
    fact = Fact(
        category="surroundings",
        statement="cluster migration ongoing",
        source_seqs=[3, 4],
        source_kind="observed",
        confidence="medium",
        durability="dated",
        valid_until=date(2026, 10, 1),
    )
    extraction = _extraction().model_copy(update={"facts": [fact]})
    result = ExtractionResult(session_id="s1", week_key="2026-W37", month_key="2026-09", extraction=extraction)
    store.record_outcome(task.id, TaskOutcome(provenance=_provenance(task.id), result=result), NOW)
    view = store.facts("alice", FactFilter(durability=["dated"]))[0]
    assert (view.valid_until, view.source_seqs, view.source_kind) == (date(2026, 10, 1), [3, 4], "observed")
