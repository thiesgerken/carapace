"""The whole memory pipeline against a real database, real handlers and a scripted model.

Per-module tests fake their neighbours; this one wires store, spawner, worker, the extraction,
digest and mirror handlers and git together, so the seams between them are exercised too.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.usage import RequestUsage

from carapace.database.models import User
from carapace.git.store import GitStore
from carapace.jobs import JobsStore
from carapace.knowledge import KnowledgeRepoHandle
from carapace.memory.coverage import coverage_hash, month_coverage, week_coverage
from carapace.memory.handlers import DigestHandler, MirrorHandler, SessionExtractHandler
from carapace.memory.input import INPUT_FORMAT_VERSION, render_extraction_input
from carapace.memory.models import (
    DigestLevel,
    FactFilter,
    MemoryTask,
    TaskFilter,
    TaskKind,
    TaskRunRequest,
    TaskSelection,
    TaskStatus,
)
from carapace.memory.service import MemoryService
from carapace.memory.store import MemoryStore
from carapace.memory.worker import WorkerTiming
from carapace.models.config import Config
from carapace.models.jobs import JobDefinition
from carapace.models.session import SessionJobRunContext
from carapace.models.user import MemoryBudget, UserConfig, UserMemoryConfig
from carapace.session import SessionManager
from carapace.skills import SkillRegistry

NOW = datetime(2026, 10, 6, 10, tzinfo=UTC)  # Tuesday of W41: September and its weeks have ended
LONG_AGO = datetime(2026, 9, 25, tzinfo=UTC)
BILLED_INPUT_TOKENS = 2000

EXTRACTION = {
    "abstract": "The user talked about tea and their NAS.",
    "outcomes": ["Decided on green tea."],
    "open_loops": [],
    "on_my_mind": ["tea"],
    "facts": [
        {
            "category": "user",
            "statement": "The user likes green tea.",
            "source_seqs": [0],
            "source_kind": "user_said",
            "confidence": "high",
            "durability": "durable",
        },
        {
            "category": "surroundings",
            "statement": "The NAS is a Synology DS920+.",
            "subject": "NAS",
            "source_seqs": [1],
            "source_kind": "observed",
            "confidence": "medium",
            "durability": "durable",
        },
    ],
    "friction": [],
    "tags": ["tea"],
}
DIGEST = {
    "summary": "Tea and storage.",
    "on_my_mind": [{"theme": "tea", "refs": []}],
    "highlights": ["Settled on green tea."],
    "open_loops": [],
    "learned": [
        {
            "category": "user",
            "statement": "The user likes green tea.",
            "source_kind": "user_said",
            "confidence": "high",
            "durability": "durable",
            "refs": [],
        }
    ],
}


def _scripted_model(calls: list[str]) -> FunctionModel:
    """Answers extraction and digest calls by their output schema, billing fixed usage."""

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        tool = info.output_tools[0]
        is_extraction = "abstract" in tool.parameters_json_schema.get("properties", {})
        calls.append("extract" if is_extraction else "digest")
        return ModelResponse(
            parts=[ToolCallPart(tool.name, EXTRACTION if is_extraction else DIGEST)],
            usage=RequestUsage(input_tokens=BILLED_INPUT_TOKENS, output_tokens=200),
            provider_details={"cost": 0.01},
        )

    return FunctionModel(respond)


class Pipeline:
    def __init__(self, db_factory, tmp_path: Path) -> None:
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
        self.now = NOW
        self.config = Config()
        self.sessions = SessionManager(db_factory, tmp_path / "data")
        self.jobs = JobsStore(db_factory)
        self.store = MemoryStore(db_factory)
        self.user_configs = {
            "alice": UserConfig(timezone="Europe/Berlin"),
            "bob": UserConfig(timezone="Europe/Berlin", memory=UserMemoryConfig(auto_mode=True)),
        }
        self.calls: list[str] = []
        self.repos = {user: self._repo(tmp_path / f"knowledge-{user}", user) for user in self.user_configs}
        model = _scripted_model(self.calls)

        def model_factory(name: str, *, user: str) -> FunctionModel:
            return model

        async def push_if_configured(user: str) -> None:
            return None

        def digest_handler(level: DigestLevel) -> DigestHandler:
            return DigestHandler(
                level=level,
                config=self.config,
                current_extractions=self.store.current_extractions,
                current_digests=self.store.current_digests,
                model_factory=model_factory,
            )

        self.service = MemoryService(
            config=self.config,
            store=self.store,
            sessions=self.sessions,
            jobs=self.jobs,
            handlers={
                TaskKind.session_extract: SessionExtractHandler(
                    config=self.config,
                    load_events=self.sessions.load_events,
                    user_config_for=self.user_configs.__getitem__,
                    model_factory=model_factory,
                ),
                TaskKind.week_digest: digest_handler(DigestLevel.week),
                TaskKind.month_digest: digest_handler(DigestLevel.month),
                TaskKind.mirror: MirrorHandler(
                    current_extractions=self.store.current_extractions,
                    current_digests=self.store.current_digests,
                    knowledge_repo_for_user=self.repos.__getitem__,
                    push_if_configured=push_if_configured,
                ),
            },
            user_config_for=self.user_configs.__getitem__,
            users=lambda: list(self.user_configs),
            is_agent_running=lambda _: False,
            # Sweep on every tick and mirror as soon as the queue allows.
            timing=WorkerTiming(sweep_interval=timedelta(0), mirror_debounce=timedelta(0)),
            clock=lambda: self.now,
        )

    @staticmethod
    def _repo(knowledge_dir: Path, user: str) -> KnowledgeRepoHandle:
        return KnowledgeRepoHandle(
            owner=user,
            knowledge_dir=knowledge_dir,
            git_store=GitStore(knowledge_dir),
            skill_registry=SkillRegistry(knowledge_dir / "skills"),
        )

    def session(self, user: str, first_message_at: str, *, private: bool = False, job_id: str | None = None) -> str:
        state = self.sessions.create_session("job" if job_id else "web", user=user, private=private)
        state.title = f"chat {first_message_at}"
        state.last_active = LONG_AGO
        state.attributes.archived = True
        if job_id is not None:
            state.latest_job_run = SessionJobRunContext(job_id=job_id, trigger_kind="cron", triggered_at=LONG_AGO)
        self.sessions.save_state(state)
        self.sessions.append_events(
            state.session_id,
            [
                {"role": "user", "content": "I like green tea. What NAS do I have?", "timestamp": first_message_at},
                {"role": "tool_call", "tool": "exec", "args": {"command": "nas-info"}, "tool_id": "t1"},
                {"role": "tool_result", "tool": "exec", "result": "Synology DS920+", "exit_code": 0, "tool_id": "t1"},
                {"role": "assistant", "content": "Noted. You have a Synology DS920+."},
            ],
        )
        return state.session_id

    async def settle(self, rounds: int = 8) -> None:
        for _ in range(rounds):
            await self.service.worker.tick()
            await self.service.worker.drain()

    def tasks(self, user: str, kind: TaskKind) -> list[MemoryTask]:
        return self.store.list_tasks(user, TaskFilter(kind=[kind]), None, 100).items

    async def run(self, user: str, kind: TaskKind) -> None:
        selection = TaskSelection(filter=TaskFilter(kind=[kind], status=[TaskStatus.pending]))
        await self.service.run_tasks(user, TaskRunRequest(selection=selection))

    def mirror_files(self, user: str) -> list[str]:
        root = self.repos[user].knowledge_dir / "memory"
        return sorted(p.relative_to(root).as_posix() for p in root.rglob("*.md"))

    async def commits(self, user: str) -> list[str]:
        code, out = await self.repos[user].git_store._run("log", "--format=%s", "--", "memory")
        assert code == 0, out
        return out.splitlines()


@pytest.fixture
def pipeline(db_factory, tmp_path: Path) -> Pipeline:
    return Pipeline(db_factory, tmp_path)


def _by_target(tasks: list[MemoryTask]) -> dict[str, MemoryTask]:
    return {t.target: t for t in tasks}


async def test_memory_pipeline_end_to_end(pipeline: Pipeline) -> None:
    p = pipeline
    p.jobs.create_job(JobDefinition(user="alice", id="nightly", name="Nightly", prompt="p"))  # no memory opt-in
    # Sunday 23:30 vs Monday 00:30 in Berlin, both on Sunday in UTC: the week boundary is the user's.
    sunday = p.session("alice", "2026-09-13T21:30:00+00:00")
    wednesday = p.session("alice", "2026-09-09T10:00:00+00:00")
    monday = p.session("alice", "2026-09-13T22:30:00+00:00")
    private = p.session("alice", "2026-09-10T10:00:00+00:00", private=True)
    job = p.session("alice", "2026-09-10T11:00:00+00:00", job_id="nightly")
    bobs = p.session("bob", "2026-09-10T09:00:00+00:00")

    # --- Sweep: pending extractions, periods in the user's timezone, nothing for ineligible sessions.
    alice = p.user_configs["alice"]
    alice.memory.budget = MemoryBudget(cost_usd_per_day=None, cost_usd_per_month=None)
    await p.settle(1)
    extracts = _by_target(p.tasks("alice", TaskKind.session_extract))
    assert set(extracts) == {sunday, wednesday, monday}
    assert {s: t.week_key for s, t in extracts.items()} == {
        sunday: "2026-W37",
        wednesday: "2026-W37",
        monday: "2026-W38",
    }
    assert all(t.status is TaskStatus.pending and t.estimate is not None for t in extracts.values())
    assert private not in extracts and job not in extracts
    # Alice is in manual mode: none of hers ran (the one call is Bob's, in auto mode), and no
    # digest exists while her weeks still have open extractions.
    assert p.calls == ["extract"] and p.tasks("alice", TaskKind.week_digest) == []

    # --- Budget gate: a token limit that admits one estimate at a time.
    largest = max(t.estimate.input_tokens for t in extracts.values() if t.estimate is not None)
    alice.memory.budget.input_tokens_per_day = largest + 1
    await p.run("alice", TaskKind.session_extract)
    await p.settle(2)
    statuses = sorted(t.status for t in p.tasks("alice", TaskKind.session_extract))
    assert statuses == [TaskStatus.done, TaskStatus.queued, TaskStatus.queued]
    blocked = [t for t in p.tasks("alice", TaskKind.session_extract) if t.status is TaskStatus.queued]
    assert all(t.blocked_reason == "budget" for t in blocked)
    assert p.store.spend("alice", LONG_AGO).input_tokens == BILLED_INPUT_TOKENS

    alice.memory.budget.input_tokens_per_day = None
    await p.settle(3)
    assert {t.status for t in p.tasks("alice", TaskKind.session_extract)} == {TaskStatus.done}
    assert p.store.spend("alice", LONG_AGO).input_tokens == 3 * BILLED_INPUT_TOKENS

    # --- Extractions, provenance and facts.
    record = p.store.current_extraction("alice", sunday)
    assert record is not None
    rendered = render_extraction_input(p.sessions.load_events(sunday))
    assert (record.input_hash, record.provenance.input_hash) == (rendered.input_hash, rendered.input_hash)
    assert record.provenance.input_format_version == INPUT_FORMAT_VERSION
    assert record.provenance.model == p.config.agent.title_model  # memory_low falls back to the title model
    assert record.provenance.input_tokens == BILLED_INPUT_TOKENS and record.provenance.cost_usd is not None
    sunday_task = extracts[sunday]
    assert record.provenance.task_id == sunday_task.id
    assert (record.week_key, record.month_key) == ("2026-W37", "2026-09")
    facts = await p.service.facts("alice", FactFilter())
    assert len(facts.items) == 6 and {f.category for f in facts.items} == {"user", "surroundings"}
    assert {f.session_id for f in (await p.service.facts("alice", FactFilter(period="2026-W38"))).items} == {monday}
    assert all(f.session_id == bobs for f in (await p.service.facts("bob", FactFilter())).items)

    # --- Week digests, once their weeks are settled; coverage names the consumed records.
    weeks = _by_target(p.tasks("alice", TaskKind.week_digest))
    assert set(weeks) == {"2026-W37", "2026-W38"}
    await p.run("alice", TaskKind.week_digest)
    await p.settle(2)
    w37 = p.store.current_digest("alice", DigestLevel.week, "2026-W37")
    assert w37 is not None
    w37_sources = p.store.current_extractions("alice", "2026-W37")
    assert {s.session_id for s in w37_sources} == {sunday, wednesday}
    assert w37.coverage == week_coverage(w37_sources)
    assert w37.coverage_hash == coverage_hash(week_coverage(w37_sources))

    # --- Month digest over the weeks whose Thursday is in September.
    [month_task] = p.tasks("alice", TaskKind.month_digest)
    assert month_task.target == "2026-09"
    await p.run("alice", TaskKind.month_digest)
    await p.settle(2)
    september = p.store.current_digest("alice", DigestLevel.month, "2026-09")
    assert september is not None
    assert september.coverage == month_coverage(p.store.current_digests("alice", DigestLevel.week))

    # Bob's auto mode ran his whole pyramid without a single manual step.
    assert {t.status for t in p.tasks("bob", TaskKind.session_extract)} == {TaskStatus.done}
    assert p.store.current_digest("bob", DigestLevel.month, "2026-09") is not None
    assert p.calls.count("extract") == 4 and p.calls.count("digest") == 5  # alice 2 weeks + 1 month, bob 1 + 1

    # --- Mirror: one tree per user, committed to their knowledge repo.
    alice_files = p.mirror_files("alice")
    assert sum(f.startswith("sessions/") for f in alice_files) == 3
    assert sum(f.startswith("weeks/") for f in alice_files) == 2
    assert sum(f.startswith("months/") for f in alice_files) == 1
    assert any(sunday in f for f in alice_files)
    assert not any(private in f or job in f for f in alice_files)
    assert await p.commits("alice")
    assert not any(sunday in f for f in p.mirror_files("bob"))

    # --- Privacy: the session's memory disappears, its week goes stale and is redone.
    state = p.sessions.load_state(sunday)
    assert state is not None
    state.attributes.private = True
    p.sessions.save_state(state)
    p.now += timedelta(hours=1)
    await p.settle(2)

    assert p.store.current_extraction("alice", sunday) is None
    assert sunday not in {f.session_id for f in (await p.service.facts("alice", FactFilter())).items}
    stale = p.store.current_digest("alice", DigestLevel.week, "2026-W37")
    assert stale is not None
    remaining = week_coverage(p.store.current_extractions("alice", "2026-W37"))
    assert stale.coverage_hash != coverage_hash(remaining)
    redo = [t for t in p.tasks("alice", TaskKind.week_digest) if t.status is TaskStatus.pending]
    assert [t.target for t in redo] == ["2026-W37"]
    assert not any(sunday in f for f in p.mirror_files("alice"))

    # Ineligible sessions never got a task of any kind.
    every_target = {t.target for kind in TaskKind for t in p.tasks("alice", kind)}
    assert private not in every_target and job not in every_target
