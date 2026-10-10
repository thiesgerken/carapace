from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.usage import RequestUsage

from carapace.memory.coverage import coverage_hash, month_coverage, week_coverage
from carapace.memory.digest_input import DIGEST_INPUT_FORMAT_VERSION, render_month_input, render_week_input
from carapace.memory.handlers import DIGEST_OUTPUT_CAP, DigestHandler, TaskHandler, TaskRunError
from carapace.memory.models import (
    DigestLevel,
    DigestRecord,
    DigestResult,
    ExtractionRecord,
    MemoryTask,
    ModelRole,
    PeriodDigest,
    SpawnedBy,
    TaskKind,
    TaskStatus,
)
from carapace.memory.prompts import MONTH_DIGEST, WEEK_DIGEST
from carapace.models.config import Config
from tests.memory_fixtures import EXTRACTION, WEEK

MODEL = "anthropic:claude-sonnet-4-6"

DIGEST: dict[str, Any] = {
    "summary": "A homelab week.",
    "on_my_mind": [{"theme": "Talos upgrade", "refs": ["s-talos"]}],
    "highlights": [],
    "open_loops": ["Back up etcd."],
    "learned": [
        {
            "category": "user",
            "statement": "The user prefers upgrading on weekends.",
            "source_kind": "user_said",
            "confidence": "medium",
            "durability": "durable",
            "refs": ["s-talos"],
        }
    ],
}


def _task(kind: TaskKind, target: str) -> MemoryTask:
    return MemoryTask(
        id=21,
        user="alice",
        kind=kind,
        target=target,
        status=TaskStatus.running,
        spawned_by=SpawnedBy.manual,
        created_at=datetime(2026, 10, 1, tzinfo=UTC),
    )


class _Model:
    def __init__(self, output: dict[str, Any] = DIGEST, output_tokens: int = 500) -> None:
        self.output = output
        self.output_tokens = output_tokens
        self.prompts: list[str] = []
        self.instructions: list[str | None] = []

    def __call__(self, messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        request = messages[0]
        assert isinstance(request, ModelRequest)
        part = next(p for p in request.parts if isinstance(p, UserPromptPart))
        assert isinstance(part.content, str)
        self.prompts.append(part.content)
        self.instructions.append(info.instructions)
        return ModelResponse(
            parts=[ToolCallPart(info.output_tools[0].name, self.output)],
            usage=RequestUsage(input_tokens=3000, output_tokens=self.output_tokens),
            provider_details={"cost": 0.05},
        )


class _Sources:
    def __init__(self, extractions: list[ExtractionRecord], weeks: list[DigestRecord]) -> None:
        self.extractions = extractions
        self.weeks = weeks
        self.calls: list[tuple[Any, ...]] = []

    def current_extractions(self, user: str, week_key: str) -> list[ExtractionRecord]:
        self.calls.append(("extractions", user, week_key))
        return self.extractions

    def current_digests(self, user: str, level: DigestLevel, period_keys: list[str]) -> list[DigestRecord]:
        self.calls.append(("digests", user, level, period_keys))
        return self.weeks


def _handler(level: DigestLevel, model: _Model, sources: _Sources) -> DigestHandler:
    return DigestHandler(
        level=level,
        config=Config(),
        current_extractions=sources.current_extractions,
        current_digests=sources.current_digests,
        model_factory=lambda name, *, user: FunctionModel(model),
    )


async def test_week_digest_from_the_weeks_extractions() -> None:
    model, sources = _Model(), _Sources([EXTRACTION], [])

    outcome = await _handler(DigestLevel.week, model, sources).run(_task(TaskKind.week_digest, "2026-W36"), MODEL)

    coverage = week_coverage([EXTRACTION])
    assert outcome.result == DigestResult(
        level=DigestLevel.week,
        period_key="2026-W36",
        coverage=coverage,
        coverage_hash=coverage_hash(coverage),
        digest=PeriodDigest.model_validate(DIGEST),
    )
    assert sources.calls == [("extractions", "alice", "2026-W36")]
    rendered = render_week_input([EXTRACTION])
    assert model.prompts == [
        WEEK_DIGEST.user_prompt(rendered.text, period_key="2026-W36", first_day="2026-08-31", last_day="2026-09-06")
    ]
    assert model.instructions == [WEEK_DIGEST.system]
    provenance = outcome.provenance
    assert provenance is not None
    assert provenance.prompt_version == WEEK_DIGEST.version(PeriodDigest)
    assert provenance.input_hash == rendered.input_hash
    assert provenance.input_format_version == DIGEST_INPUT_FORMAT_VERSION
    assert (provenance.input_tokens, provenance.output_tokens, provenance.task_id) == (3000, 500, 21)


async def test_month_digest_from_the_digests_of_its_weeks() -> None:
    model, sources = _Model(), _Sources([], [WEEK])

    outcome = await _handler(DigestLevel.month, model, sources).run(_task(TaskKind.month_digest, "2026-09"), MODEL)

    # 2026-W40 starts on Sep 28, but its Thursday is Oct 1: it belongs to October.
    assert sources.calls == [("digests", "alice", DigestLevel.week, ["2026-W36", "2026-W37", "2026-W38", "2026-W39"])]
    assert isinstance(outcome.result, DigestResult)
    assert outcome.result.level is DigestLevel.month
    assert outcome.result.coverage == month_coverage([WEEK])
    assert model.prompts == [MONTH_DIGEST.user_prompt(render_month_input([WEEK]).text, period_key="2026-09")]
    assert outcome.provenance is not None
    assert outcome.provenance.prompt_version == MONTH_DIGEST.version(PeriodDigest)


@pytest.mark.parametrize(
    ("level", "kind", "target"),
    [
        (DigestLevel.week, TaskKind.week_digest, "2026-W36"),
        (DigestLevel.month, TaskKind.month_digest, "2026-09"),
    ],
)
async def test_period_without_sources_fails_loudly(level: DigestLevel, kind: TaskKind, target: str) -> None:
    handler = _handler(level, _Model(), _Sources([], []))

    with pytest.raises(ValueError, match="no current sources"):
        await handler.estimate("alice", target, MODEL)
    with pytest.raises(ValueError, match="no current sources"):
        await handler.run(_task(kind, target), MODEL)


async def test_estimate_uses_the_digest_output_cap() -> None:
    estimate = await _handler(DigestLevel.week, _Model(), _Sources([EXTRACTION], [])).estimate(
        "alice", "2026-W36", MODEL
    )

    assert estimate.output_tokens_cap == DIGEST_OUTPUT_CAP
    assert estimate.input_tokens > render_week_input([EXTRACTION]).token_estimate
    assert estimate.cost_usd is not None


async def test_billed_failure_carries_provenance() -> None:
    model = _Model(output_tokens=DIGEST_OUTPUT_CAP + 1)

    with pytest.raises(TaskRunError) as failed:
        await _handler(DigestLevel.week, model, _Sources([EXTRACTION], [])).run(
            _task(TaskKind.week_digest, "2026-W36"), MODEL
        )

    assert failed.value.provenance.output_tokens == DIGEST_OUTPUT_CAP + 1
    assert failed.value.provenance.prompt_version == WEEK_DIGEST.version(PeriodDigest)


async def test_digest_needs_a_model() -> None:
    with pytest.raises(ValueError, match="need a model"):
        await _handler(DigestLevel.week, _Model(), _Sources([EXTRACTION], [])).run(
            _task(TaskKind.week_digest, "2026-W36"), None
        )


def test_one_handler_per_level_satisfies_the_protocol() -> None:
    sources = _Sources([], [])
    handlers: dict[TaskKind, TaskHandler] = {
        handler.kind: handler for handler in (_handler(level, _Model(), sources) for level in DigestLevel)
    }

    assert set(handlers) == {TaskKind.week_digest, TaskKind.month_digest}
    assert {h.model_role for h in handlers.values()} == {ModelRole.memory_high}
