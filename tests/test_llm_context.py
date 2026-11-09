"""Capture and persistence of the latest LLM context per session and agent role."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, DeltaToolCalls, FunctionModel
from pydantic_ai.usage import RequestUsage

from carapace.security.context import SessionSecurity
from carapace.security.sentinel import Sentinel
from carapace.session.engine import SessionEngine
from carapace.session.types import ActiveSession
from carapace.usage import LlmRequestLogCapability, ModelUsage, RequestCost, price_for_usage
from tests.session_helpers import _FakeSubscriber, _make_engine, _patch_sentinel


def _reply(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
    return ModelResponse(parts=[TextPart("pong")])


def _fail(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
    raise RuntimeError("boom")


async def _hang(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
    await asyncio.sleep(10)
    raise AssertionError("unreachable")


async def _overload_mid_stream(_messages: list[ModelMessage], _info: AgentInfo) -> AsyncIterator[str | DeltaToolCalls]:
    yield "Checking the"
    raise RuntimeError("overloaded")


def _agent(model: FunctionModel, model_id: str = "test:model") -> Agent[None, str]:
    agent = Agent(
        model, instructions="Be terse.", capabilities=[LlmRequestLogCapability(source="agent", model_id=model_id)]
    )

    @agent.tool_plain
    def lookup(key: str) -> str:
        return key

    return agent


def _sentinel(tmp_path: Path, model: FunctionModel) -> Sentinel:
    (tmp_path / "skills").mkdir(exist_ok=True)
    return Sentinel(
        model="test:model",
        user="thies",
        knowledge_dir=tmp_path,
        skills_dir=tmp_path / "skills",
        llm_slots=None,
        timeout=timedelta(seconds=0.05),
        model_factory=lambda _name, *, user: model,
    )


def _session(tmp_path: Path, db_factory) -> tuple[SessionEngine, ActiveSession, _FakeSubscriber]:
    with _patch_sentinel():
        engine = _make_engine(tmp_path, session_factory=db_factory)
        state = engine.session_mgr.create_session(user="thies")
        active = engine.get_or_activate(state.session_id)
    subscriber = _FakeSubscriber()
    active.subscribers.append(subscriber)
    return engine, active, subscriber


@pytest.mark.asyncio
async def test_completed_request_persists_what_was_sent_and_the_response(tmp_path: Path, db_factory) -> None:
    engine, active, subscriber = _session(tmp_path, db_factory)

    with engine.llm_request_recording(active):
        await _agent(FunctionModel(_reply)).run("ping")

    context = engine.session_mgr.load_llm_context(active.state.session_id, "agent")
    assert context is not None
    assert context.status == "completed"
    assert [part.content for part in context.instructions] == ["Be terse."]
    assert [tool.name for tool in context.tool_definitions] == ["lookup"]
    assert isinstance(context.messages[-1].parts[0], UserPromptPart)
    assert context.messages[-1].parts[0].content == "ping"
    assert context.response is not None and context.response.parts == [TextPart("pong")]
    assert subscriber.llm_context_updates == [
        ("agent", context.request_id, "running"),
        ("agent", context.request_id, "completed"),
    ]


@pytest.mark.asyncio
async def test_request_record_keeps_cache_and_audio_tokens(tmp_path: Path, db_factory) -> None:
    engine, active, _ = _session(tmp_path, db_factory)
    usage = RequestUsage(input_tokens=1000, output_tokens=20, cache_read_tokens=800, cache_write_tokens=150)

    def reply(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart("pong")], usage=usage)

    with engine.llm_request_recording(active):
        await _agent(FunctionModel(reply)).run("ping")

    [record] = engine.session_mgr.load_llm_request_log(active.state.session_id).records
    assert (record.input_tokens, record.cache_read_tokens, record.cache_write_tokens) == (1000, 800, 150)
    assert (record.input_audio_tokens, record.output_audio_tokens, record.cache_audio_read_tokens) == (0, 0, 0)


@pytest.mark.asyncio
async def test_failed_request_keeps_its_context_with_the_error(tmp_path: Path, db_factory) -> None:
    engine, active, _subscriber = _session(tmp_path, db_factory)

    with engine.llm_request_recording(active), pytest.raises(RuntimeError):
        await _agent(FunctionModel(_fail)).run("ping")

    context = engine.session_mgr.load_llm_context(active.state.session_id, "agent")
    assert context is not None
    assert (context.status, context.error, context.response) == ("failed", "RuntimeError: boom", None)
    assert context.messages


@pytest.mark.asyncio
async def test_sentinel_timeout_marks_its_context_failed(tmp_path: Path, db_factory) -> None:
    engine, active, _subscriber = _session(tmp_path, db_factory)
    sentinel = _sentinel(tmp_path, FunctionModel(_hang))

    with engine.llm_request_recording(active):
        verdict = await sentinel.evaluate_tool_call(SessionSecurity("s"), "exec", {"command": "echo hi"})

    context = engine.session_mgr.load_llm_context(active.state.session_id, "sentinel")
    assert context is not None
    assert context.status == "failed"
    assert context.error == verdict.explanation
    assert context.messages


@pytest.mark.asyncio
async def test_agent_error_mid_stream_marks_its_context_failed(tmp_path: Path, db_factory) -> None:
    """Streamed, the request only sees a cancellation; the turn's error path supplies the error."""
    engine, active, _subscriber = _session(tmp_path, db_factory)

    async def _streaming_turn(user_input: str, *_args: Any, **_kwargs: Any) -> None:
        async def _drain(_ctx: Any, events: AsyncIterator[Any]) -> None:
            async for _event in events:
                pass

        await _agent(FunctionModel(stream_function=_overload_mid_stream)).run(user_input, event_stream_handler=_drain)

    with patch("carapace.session.engine.run_agent_turn", new=_streaming_turn), pytest.raises(RuntimeError):
        await engine._execute_agent_turn(
            active,
            "ping",
            None,  # pyrefly: ignore[bad-argument-type]
            [],
            send_approval_request=lambda _request: asyncio.sleep(0),
            collect_approvals=lambda _ids: asyncio.sleep(0, {}),
            on_messages_snapshot=lambda _messages: None,
            on_assistant_text=lambda _text: asyncio.sleep(0),
        )

    context = engine.session_mgr.load_llm_context(active.state.session_id, "agent")
    assert context is not None
    assert (context.status, context.error) == ("failed", "RuntimeError: overloaded")


@pytest.mark.asyncio
async def test_sentinel_timeout_between_requests_leaves_the_completed_context_alone(tmp_path: Path, db_factory) -> None:
    engine, active, _subscriber = _session(tmp_path, db_factory)

    def _call_slow_tool(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[ToolCallPart("slow_tool", {})])

    sentinel = _sentinel(tmp_path, FunctionModel(_call_slow_tool))

    @sentinel._agent.tool_plain
    async def slow_tool() -> str:
        await asyncio.sleep(10)
        return "unreachable"

    with engine.llm_request_recording(active):
        await sentinel.evaluate_tool_call(SessionSecurity("s"), "exec", {"command": "echo hi"})

    context = engine.session_mgr.load_llm_context(active.state.session_id, "sentinel")
    assert context is not None
    assert (context.status, context.error) == ("completed", None)


@pytest.mark.asyncio
async def test_each_role_keeps_only_its_latest_context(tmp_path: Path, db_factory) -> None:
    engine, active, subscriber = _session(tmp_path, db_factory)

    with engine.llm_request_recording(active):
        await _agent(FunctionModel(_reply)).run("first")
        await _agent(FunctionModel(_reply)).run("second")

    context = engine.session_mgr.load_llm_context(active.state.session_id, "agent")
    assert context is not None
    assert context.request_id == subscriber.llm_context_updates[-1][1]
    assert context.messages[-1].parts[0].content == "second"
    assert engine.session_mgr.load_llm_context(active.state.session_id, "titler") is None


def test_compaction_context_names_what_it_compacted() -> None:
    with pytest.raises(ValueError):
        LlmRequestLogCapability(source="compaction", model_id="test:model")
    with pytest.raises(ValueError):
        LlmRequestLogCapability(source="agent", model_id="test:model", compaction_target="agent")


def _priced_reply(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
    return ModelResponse(
        parts=[TextPart("pong")],
        usage=RequestUsage(input_tokens=10_000, output_tokens=500, cache_read_tokens=2_000),
        provider_details={"cost": 0.01},
    )


@pytest.mark.parametrize(
    ("model_id", "billed"),
    [("anthropic:claude-sonnet-4-6", True), ("openai-codex:gpt-5.5", False)],
)
@pytest.mark.asyncio
async def test_completed_context_is_priced_with_the_carapace_model_id(
    tmp_path: Path, db_factory, model_id: str, billed: bool
) -> None:
    engine, active, _subscriber = _session(tmp_path, db_factory)

    with engine.llm_request_recording(active):
        await _agent(FunctionModel(_priced_reply, model_name="claude-sonnet-4-6-20260101"), model_id).run("ping")

    context = engine.session_mgr.load_llm_context(active.state.session_id, "agent")
    assert context is not None
    assert context.model_name == model_id
    expected = price_for_usage(
        model_id, ModelUsage(input_tokens=10_000, output_tokens=500, cache_read_tokens=2_000, cost_usd=Decimal("0.01"))
    )
    assert expected is not None and expected > Decimal("0.01")
    assert context.cost == RequestCost(
        cost_usd=expected if billed else Decimal(0), equivalent_cost_usd=expected, provider_cost_usd=Decimal("0.01")
    )
    [record] = engine.session_mgr.load_llm_request_log(active.state.session_id).records
    assert record.model_name == model_id and record.cost == context.cost


@pytest.mark.asyncio
async def test_unpriced_or_failed_requests_carry_no_cost(tmp_path: Path, db_factory) -> None:
    engine, active, _subscriber = _session(tmp_path, db_factory)

    with engine.llm_request_recording(active):
        await _agent(FunctionModel(_reply)).run("ping")
    unpriced = engine.session_mgr.load_llm_context(active.state.session_id, "agent")
    with engine.llm_request_recording(active), pytest.raises(RuntimeError):
        await _agent(FunctionModel(_fail), "anthropic:claude-sonnet-4-6").run("ping")
    failed = engine.session_mgr.load_llm_context(active.state.session_id, "agent")

    assert unpriced is not None and unpriced.cost == RequestCost(
        cost_usd=None, equivalent_cost_usd=None, provider_cost_usd=None
    )
    assert failed is not None and failed.cost is None
