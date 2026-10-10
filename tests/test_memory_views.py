from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from carapace.database.models import User
from carapace.jobs import JobsStore
from carapace.memory.coverage import coverage_hash, month_coverage, week_coverage
from carapace.memory.input import INPUT_FORMAT_VERSION
from carapace.memory.models import (
    DigestLevel,
    DigestRecord,
    DigestResult,
    ExtractionResult,
    ExtractionState,
    Fact,
    MemoryTask,
    ModelRole,
    OutdatedReason,
    PeriodDigest,
    Provenance,
    SessionExtraction,
    SessionExtractionOutput,
    SessionMemoryFilter,
    SpawnedBy,
    TaskEstimate,
    TaskKind,
    TaskOutcome,
    TaskSelection,
    TaskStatus,
)
from carapace.memory.prompts import SESSION_EXTRACT
from carapace.memory.service import MemoryService
from carapace.memory.store import MemoryStore
from carapace.models.config import Config
from carapace.models.user import UserConfig
from carapace.session import SessionManager

NOW = datetime(2026, 9, 21, 12, tzinfo=UTC)
CURRENT_PROMPT = SESSION_EXTRACT.version(SessionExtractionOutput)
LOW_MODEL = Config().agent.title_model


class FakeHandler:
    def __init__(self, kind: TaskKind, role: ModelRole) -> None:
        self.kind = kind
        self.model_role = role

    async def estimate(self, user: str, target: str, model: str) -> TaskEstimate:
        return TaskEstimate(model=model, input_tokens=100, output_tokens_cap=10, cost_usd=Decimal("0.01"))

    async def run(self, task: MemoryTask, model: str | None) -> TaskOutcome:
        raise AssertionError("not run in these tests")


@pytest.fixture
def setup(db_factory, tmp_path):
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
    sessions = SessionManager(db_factory, tmp_path)
    store = MemoryStore(db_factory)
    service = MemoryService(
        config=Config(),
        store=store,
        sessions=sessions,
        jobs=JobsStore(db_factory),
        handlers={
            kind: FakeHandler(kind, role)  # type: ignore[dict-item]
            for kind, role in (
                (TaskKind.session_extract, ModelRole.memory_low),
                (TaskKind.week_digest, ModelRole.memory_high),
                (TaskKind.month_digest, ModelRole.memory_high),
            )
        },
        user_config_for=lambda _: UserConfig(),
        users=lambda: ["alice", "bob"],
        is_agent_running=lambda _: False,
        clock=lambda: NOW,
    )
    return service, sessions, store


def _session(
    sessions: SessionManager,
    title: str,
    *,
    user: str = "alice",
    channel: str = "web",
    private: bool = False,
    events: bool = True,
) -> str:
    state = sessions.create_session(channel, user=user, private=private)
    state.title = title
    sessions.save_state(state)
    if events:
        sessions.append_events(
            state.session_id, [{"role": "user", "content": "hi", "timestamp": "2026-09-08T09:00:00+00:00"}]
        )
    return state.session_id


def _provenance(task_id: int, *, model: str = LOW_MODEL, prompt: str = CURRENT_PROMPT) -> Provenance:
    return Provenance(
        carapace_version="0.0.0",
        model=model,
        prompt_version=prompt,
        input_format_version=INPUT_FORMAT_VERSION,
        input_hash=f"hash-{task_id}",
        input_tokens=1200,
        output_tokens=300,
        cost_usd=Decimal("0.004"),
        duration_ms=10,
        task_id=task_id,
        created_at=NOW,
    )


def _run(store: MemoryStore, task: MemoryTask | None) -> MemoryTask:
    assert task is not None
    assert store.run("alice", TaskSelection(ids=[task.id]), None, NOW) == 1
    assert store.claim(task.id, NOW)
    return task


def _extract(store: MemoryStore, session_id: str, *, week: str = "2026-W37", prompt: str = CURRENT_PROMPT) -> None:
    estimate = TaskEstimate(model=LOW_MODEL, input_tokens=1, output_tokens_cap=1, cost_usd=None)
    task = _run(
        store,
        store.spawn(
            "alice",
            TaskKind.session_extract,
            session_id,
            spawned_by=SpawnedBy.auto,
            now=NOW,
            session_week_key=week,
            estimate=estimate,
        ),
    )
    fact = Fact(
        category="social",
        subject="Anna",
        statement="Anna is moving.",
        source_seqs=[0],
        source_kind="user_said",
        confidence="high",
        durability="durable",
    )
    extraction = SessionExtraction(
        abstract=f"about {session_id}", outcomes=[], open_loops=[], on_my_mind=[], facts=[fact], friction=[], tags=[]
    )
    result = ExtractionResult(session_id=session_id, week_key=week, month_key="2026-09", extraction=extraction)
    assert store.record_outcome(
        task.id, TaskOutcome(provenance=_provenance(task.id, prompt=prompt), result=result), NOW
    )


def _digest(store: MemoryStore, level: DigestLevel, key: str, coverage_source: list) -> DigestRecord:
    kind = TaskKind.week_digest if level is DigestLevel.week else TaskKind.month_digest
    estimate = TaskEstimate(model="test:high", input_tokens=1, output_tokens_cap=1, cost_usd=None)
    task = _run(store, store.spawn("alice", kind, key, spawned_by=SpawnedBy.auto, now=NOW, estimate=estimate))
    coverage = week_coverage(coverage_source) if level is DigestLevel.week else month_coverage(coverage_source)
    result = DigestResult(
        level=level,
        period_key=key,
        coverage=coverage,
        coverage_hash=coverage_hash(coverage),
        digest=PeriodDigest(summary=f"digest {key}", on_my_mind=[], highlights=[], open_loops=[], learned=[]),
    )
    assert store.record_outcome(
        task.id, TaskOutcome(provenance=_provenance(task.id, model="test:high"), result=result), NOW
    )
    digest = store.current_digest("alice", level, key)
    assert digest is not None
    return digest


@pytest.fixture
def listed(setup):
    """Four listed sessions in every extraction state, plus sessions the views must leave out."""
    service, sessions, store = setup
    current = _session(sessions, "current")
    outdated = _session(sessions, "outdated")
    pending = _session(sessions, "pending")
    new = _session(sessions, "new")
    _extract(store, current)
    _extract(store, outdated, prompt="old-prompt")
    store.spawn(
        "alice",
        TaskKind.session_extract,
        pending,
        spawned_by=SpawnedBy.auto,
        now=NOW,
        session_week_key="2026-W38",
        estimate=TaskEstimate(model=LOW_MODEL, input_tokens=1, output_tokens_cap=1, cost_usd=None),
    )
    _session(sessions, "private", private=True)
    _session(sessions, "legacy", events=False)
    _session(sessions, "job", channel="job")
    _session(sessions, "bobs", user="bob")
    return service, store, {"current": current, "outdated": outdated, "pending": pending, "new": new}


async def test_sessions_list_only_listed_sessions_with_their_state(listed):
    service, _, ids = listed
    page = await service.list_sessions("alice", SessionMemoryFilter(), None, 10)
    rows = {row.session_id: row for row in page.items}
    assert page.total == 4 and set(rows) == set(ids.values())

    current = rows[ids["current"]]
    assert current.extraction is not None and current.extraction.outdated == []
    assert (current.extraction.abstract, current.week_key) == (f"about {ids['current']}", "2026-W37")
    assert current.extraction.fact_counts.model_dump() == {"user": 0, "social": 1, "surroundings": 0}
    assert current.task is not None and current.task.status is TaskStatus.done

    outdated = rows[ids["outdated"]].extraction
    assert outdated is not None and outdated.outdated == [OutdatedReason.prompt_version]

    pending = rows[ids["pending"]]
    assert pending.extraction is None and pending.week_key == "2026-W38"
    assert pending.task is not None and pending.task.status is TaskStatus.pending

    new = rows[ids["new"]]
    assert (new.extraction, new.task, new.week_key) == (None, None, None)


@pytest.mark.parametrize(
    ("session_filter", "expected"),
    [
        (SessionMemoryFilter(state=[ExtractionState.current]), {"current"}),
        (SessionMemoryFilter(state=[ExtractionState.outdated]), {"outdated"}),
        (SessionMemoryFilter(state=[ExtractionState.missing]), {"pending", "new"}),
        (
            SessionMemoryFilter(state=[ExtractionState.outdated], outdated_reason=OutdatedReason.prompt_version),
            {"outdated"},
        ),
        (SessionMemoryFilter(outdated_reason=OutdatedReason.model), set()),
        (SessionMemoryFilter(week="2026-W38"), {"pending"}),
        (SessionMemoryFilter(week="2026-W37"), {"current", "outdated"}),
        (SessionMemoryFilter(task_status=[TaskStatus.pending]), {"pending"}),
        (SessionMemoryFilter(model=LOW_MODEL), {"current", "outdated"}),
        (SessionMemoryFilter(channel="matrix"), set()),
    ],
)
async def test_session_filters(listed, session_filter: SessionMemoryFilter, expected: set[str]):
    service, _, ids = listed
    names = {session_id: name for name, session_id in ids.items()}
    matching = service.matching_sessions("alice", session_filter)
    assert {names[c.state.session_id] for c in matching} == expected
    listing = await service.list_sessions("alice", session_filter, None, 10)
    assert [row.session_id for row in listing.items] == [c.state.session_id for c in matching]


async def test_sessions_paginate(listed):
    service, _, _ = listed
    first = await service.list_sessions("alice", SessionMemoryFilter(), None, 3)
    assert (len(first.items), first.next_cursor, first.total) == (3, "3", 4)
    second = await service.list_sessions("alice", SessionMemoryFilter(), first.next_cursor, 3)
    assert (len(second.items), second.next_cursor) == (1, None)
    assert {r.session_id for r in first.items}.isdisjoint(r.session_id for r in second.items)


async def test_session_detail_has_history_and_hides_unlisted_sessions(listed, setup):
    service, store, ids = listed
    _, sessions, _ = setup
    _extract(store, ids["current"])
    detail = await service.session_detail("alice", ids["current"])
    assert detail is not None and detail.current is not None
    assert [r.id for r in detail.history] != [] and detail.history[0].id < detail.current.id

    private = _session(sessions, "private too", private=True)
    assert await service.session_detail("alice", private) is None
    assert await service.session_detail("bob", ids["current"]) is None
    assert await service.session_detail("alice", "missing") is None


async def test_period_tree_coverage_and_staleness(listed):
    service, store, ids = listed
    week_sources = store.current_extractions("alice", "2026-W37")
    week = _digest(store, DigestLevel.week, "2026-W37", week_sources)
    _digest(store, DigestLevel.month, "2026-09", [week])

    [month] = (await service.periods("alice")).months
    assert (month.key, month.covered, month.total, month.stale) == ("2026-09", 1, 2, False)
    assert [w.key for w in month.weeks] == ["2026-W37", "2026-W38"]
    w37, w38 = month.weeks
    assert (w37.covered, w37.total, w37.stale) == (2, 2, False)
    assert w37.digest is not None and OutdatedReason.model in w37.digest.outdated
    assert (w38.covered, w38.total, w38.digest, w38.stale) == (0, 1, None, False)
    assert (str(w37.start), str(w37.end)) == ("2026-09-07", "2026-09-13")

    # A re-extraction changes the week's sources: the week digest turns stale, the month does not
    # until the week digest is regenerated.
    _extract(store, ids["current"])
    [month] = (await service.periods("alice")).months
    assert (month.weeks[0].stale, month.stale) == (True, False)


async def test_period_detail(listed):
    service, store, ids = listed
    week = _digest(store, DigestLevel.week, "2026-W37", store.current_extractions("alice", "2026-W37"))
    _digest(store, DigestLevel.week, "2026-W37", store.current_extractions("alice", "2026-W37"))

    detail = await service.period_detail("alice", DigestLevel.week, "2026-W37")
    assert detail is not None and detail.current is not None
    assert [d.id for d in detail.history] == [week.id]
    assert {s.session_id for s in detail.sessions} == {ids["current"], ids["outdated"]}
    assert detail.weeks == []

    month = await service.period_detail("alice", DigestLevel.month, "2026-09")
    assert month is not None and [w.key for w in month.weeks] == ["2026-W37", "2026-W38"]
    assert month.sessions == [] and month.current is None

    assert await service.period_detail("alice", DigestLevel.week, "2026-W40") is None
    assert await service.period_detail("alice", DigestLevel.week, "2026-W99") is None
    assert await service.period_detail("alice", DigestLevel.month, "2026-13") is None
