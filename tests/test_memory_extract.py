from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.profiles.anthropic import ANTHROPIC_THINKING_BUDGET_MAP
from pydantic_ai.usage import RequestUsage

from carapace.memory.budget import estimate_cost
from carapace.memory.handlers import SESSION_EXTRACT_OUTPUT_CAP, SessionExtractHandler, TaskRunError
from carapace.memory.input import render_extraction_input
from carapace.memory.llm import InputTooLargeError, LlmCallError, capped_model_settings
from carapace.memory.models import (
    ExtractionResult,
    MemoryTask,
    SessionExtraction,
    SpawnedBy,
    TaskKind,
    TaskStatus,
)
from carapace.memory.prompts import SESSION_EXTRACT
from carapace.models.config import AgentConfig, AvailableModelEntry, Config
from carapace.models.user import UserConfig
from carapace.usage import count_text_tokens

MODEL = "anthropic:claude-haiku-4-5"

# Sunday 22:30 UTC is already Monday in Berlin: the session belongs to the next ISO week.
EVENTS: list[dict[str, Any]] = [
    {"role": "user", "content": "/model haiku", "timestamp": "2026-09-01T08:00:00+00:00"},
    {"role": "command", "command": "model", "data": {}, "timestamp": "2026-09-01T08:00:00+00:00"},
    {"role": "user", "content": "My sister Anna moves to Lisbon.", "timestamp": "2026-09-06T22:30:00+00:00"},
    {"role": "assistant", "content": "Noted.", "timestamp": "2026-09-06T22:30:05+00:00"},
]

EXTRACTION: dict[str, Any] = {
    "abstract": "The user mentioned their sister's move.",
    "outcomes": [],
    "open_loops": [],
    "on_my_mind": ["the sister's move to Lisbon"],
    "facts": [
        {
            "category": "social",
            "statement": "The user's sister Anna is moving to Lisbon.",
            "subject": "Anna",
            "source_seqs": [2],
            "source_kind": "user_said",
            "confidence": "high",
            "durability": "dated",
        }
    ],
    "friction": [],
    "tags": ["family"],
}


def _task(target: str = "s1") -> MemoryTask:
    return MemoryTask(
        id=7,
        user="alice",
        kind=TaskKind.session_extract,
        target=target,
        status=TaskStatus.running,
        spawned_by=SpawnedBy.manual,
        created_at=datetime(2026, 9, 8, tzinfo=UTC),
    )


class _Recorder:
    def __init__(self, response_usage: RequestUsage | None = None) -> None:
        self.messages: list[ModelMessage] = []
        self.info: AgentInfo | None = None
        self._usage = response_usage or RequestUsage(input_tokens=1200, output_tokens=300)

    def __call__(self, messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        self.messages, self.info = messages, info
        return ModelResponse(
            parts=[ToolCallPart(info.output_tools[0].name, EXTRACTION)],
            usage=self._usage,
            provider_details={"cost": 0.0123},
        )

    def user_prompt(self) -> str:
        request = self.messages[0]
        assert isinstance(request, ModelRequest)
        part = next(p for p in request.parts if isinstance(p, UserPromptPart))
        assert isinstance(part.content, str)
        return part.content


def _handler(
    recorder: _Recorder, *, events: list[dict[str, Any]] = EVENTS, config: Config | None = None
) -> SessionExtractHandler:
    return SessionExtractHandler(
        config=config or Config(),
        load_events=lambda session_id: events if session_id == "s1" else [],
        user_config_for=lambda user: UserConfig(timezone="Europe/Berlin"),
        model_factory=lambda name, *, user: FunctionModel(recorder),
    )


async def test_run_returns_extraction_with_provenance() -> None:
    recorder = _Recorder()

    outcome = await _handler(recorder).run(_task(), MODEL)

    assert outcome.result == ExtractionResult(
        session_id="s1",
        week_key="2026-W37",
        month_key="2026-09",
        extraction=SessionExtraction.model_validate(EXTRACTION),
    )
    provenance = outcome.provenance
    assert provenance is not None
    rendered = render_extraction_input(EVENTS)
    assert provenance.model == MODEL
    assert provenance.prompt_version == SESSION_EXTRACT.version(SessionExtraction)
    assert provenance.input_hash == rendered.input_hash
    assert provenance.input_format_version == rendered.input_format_version
    assert (provenance.input_tokens, provenance.output_tokens) == (1200, 300)
    assert provenance.cost_usd is not None and provenance.cost_usd >= Decimal("0.0123")
    assert provenance.task_id == 7
    assert provenance.duration_ms >= 0


async def test_run_sends_sandwich_prompt_in_user_timezone() -> None:
    recorder = _Recorder()

    await _handler(recorder).run(_task(), MODEL)

    assert recorder.user_prompt() == SESSION_EXTRACT.user_prompt(
        render_extraction_input(EVENTS).text, session_date="2026-09-07"
    )
    assert recorder.info is not None
    assert recorder.info.instructions == SESSION_EXTRACT.system
    assert recorder.info.model_settings is not None
    assert recorder.info.model_settings.get("max_tokens") == SESSION_EXTRACT_OUTPUT_CAP


async def test_exceeded_output_cap_fails_with_billed_usage() -> None:
    recorder = _Recorder(RequestUsage(input_tokens=1200, output_tokens=SESSION_EXTRACT_OUTPUT_CAP + 1))

    with pytest.raises(TaskRunError) as failed:
        await _handler(recorder).run(_task(), MODEL)

    provenance = failed.value.provenance
    assert (provenance.input_tokens, provenance.output_tokens) == (1200, SESSION_EXTRACT_OUTPUT_CAP + 1)
    assert provenance.cost_usd is not None and provenance.cost_usd >= Decimal("0.0123")
    assert provenance.task_id == 7
    assert provenance.input_hash == render_extraction_input(EVENTS).input_hash
    assert isinstance(failed.value.__cause__, LlmCallError)


async def test_rejected_outputs_count_every_billed_attempt() -> None:
    invalid = {**EXTRACTION, "facts": [{**EXTRACTION["facts"][0], "subject": None}]}  # social fact without subject
    calls = 0

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal calls
        calls += 1
        return ModelResponse(
            parts=[ToolCallPart(info.output_tools[0].name, invalid)],
            usage=RequestUsage(input_tokens=1000, output_tokens=100),
            provider_details={"cost": 0.01},
        )

    handler = SessionExtractHandler(
        config=Config(),
        load_events=lambda session_id: EVENTS,
        user_config_for=lambda user: UserConfig(),
        model_factory=lambda name, *, user: FunctionModel(respond),
    )

    with pytest.raises(TaskRunError) as failed:
        await handler.run(_task(), MODEL)

    assert calls == 3  # first attempt plus two output retries
    provenance = failed.value.provenance
    assert (provenance.input_tokens, provenance.output_tokens) == (3000, 300)
    assert provenance.cost_usd is not None and provenance.cost_usd >= Decimal("0.03")


async def test_run_requires_a_model() -> None:
    with pytest.raises(ValueError, match="needs a model"):
        await _handler(_Recorder()).run(_task(), None)


async def test_estimate_counts_prompt_and_caps_output() -> None:
    handler = _handler(_Recorder())

    estimate = await handler.estimate("alice", "s1", MODEL)

    user_prompt = SESSION_EXTRACT.user_prompt(render_extraction_input(EVENTS).text, session_date="2026-09-07")
    expected_input = count_text_tokens(f"{SESSION_EXTRACT.system}\n\n{user_prompt}", model_name=MODEL)
    assert estimate.model == MODEL
    assert estimate.input_tokens == expected_input
    assert estimate.output_tokens_cap == SESSION_EXTRACT_OUTPUT_CAP
    assert estimate.cost_usd is not None
    assert estimate.cost_usd == estimate_cost(MODEL, expected_input, SESSION_EXTRACT_OUTPUT_CAP)


async def test_session_without_user_message_fails_loudly() -> None:
    handler = _handler(_Recorder(), events=EVENTS[:2])

    with pytest.raises(ValueError, match="no user message"):
        await handler.estimate("alice", "s1", MODEL)
    with pytest.raises(ValueError, match="no user message"):
        await handler.run(_task(), MODEL)


def test_thinking_model_raises_the_cap() -> None:
    entry = AvailableModelEntry(provider="anthropic", name="claude-haiku-4-5", thinking="high")
    config = Config(agent=AgentConfig(model=MODEL, sentinel_model=MODEL, title_model=MODEL, available_models=[entry]))

    settings = capped_model_settings(config, MODEL, SESSION_EXTRACT_OUTPUT_CAP)

    assert settings.get("max_tokens") == ANTHROPIC_THINKING_BUDGET_MAP["high"] + 8192
    assert settings.get("thinking") == "high"


async def test_run_fails_before_calling_the_model_when_input_exceeds_context() -> None:
    entry = AvailableModelEntry(provider="anthropic", name="claude-haiku-4-5", max_input_tokens=100)
    config = Config(agent=AgentConfig(model=MODEL, sentinel_model=MODEL, title_model=MODEL, available_models=[entry]))
    recorder = _Recorder()

    with pytest.raises(InputTooLargeError, match="input too large"):
        await _handler(recorder, config=config).run(_task(), MODEL)
    assert recorder.messages == []

    estimate = await _handler(recorder, config=config).estimate("alice", "s1", MODEL)
    assert estimate.input_tokens > 100
