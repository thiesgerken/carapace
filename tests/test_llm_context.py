"""Capture and persistence of the latest LLM context per session and agent role."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path

import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from carapace.security.context import SessionSecurity
from carapace.security.sentinel import Sentinel
from carapace.session.engine import SessionEngine
from carapace.session.types import ActiveSession
from carapace.usage import LlmRequestLogCapability
from tests.session_helpers import _FakeSubscriber, _make_engine, _patch_sentinel


def _reply(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
    return ModelResponse(parts=[TextPart("pong")])


def _fail(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
    raise RuntimeError("boom")


async def _hang(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
    await asyncio.sleep(10)
    raise AssertionError("unreachable")


def _agent(model: FunctionModel) -> Agent[None, str]:
    agent = Agent(model, instructions="Be terse.", capabilities=[LlmRequestLogCapability(source="agent")])

    @agent.tool_plain
    def lookup(key: str) -> str:
        return key

    return agent


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
    (tmp_path / "skills").mkdir(exist_ok=True)
    sentinel = Sentinel(
        model="test:model",
        user="thies",
        knowledge_dir=tmp_path,
        skills_dir=tmp_path / "skills",
        llm_slots=None,
        timeout=timedelta(seconds=0.05),
        model_factory=lambda _name, *, user: FunctionModel(_hang),
    )

    with engine.llm_request_recording(active):
        verdict = await sentinel.evaluate_tool_call(SessionSecurity("s"), "exec", {"command": "echo hi"})

    context = engine.session_mgr.load_llm_context(active.state.session_id, "sentinel")
    assert context is not None
    assert context.status == "failed"
    assert context.error == verdict.explanation
    assert context.messages


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
        LlmRequestLogCapability(source="compaction")
    with pytest.raises(ValueError):
        LlmRequestLogCapability(source="agent", compaction_target="agent")
