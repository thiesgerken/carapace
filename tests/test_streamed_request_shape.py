"""Streaming every role must not change what its requests send: prefix caching depends on it."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from pydantic_ai.capabilities.abstract import AbstractCapability
from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    TextPart,
    ThinkingPart,
    ToolCallPart,
    UserPromptPart,
)
from pydantic_ai.models import Model, ModelRequestParameters, StreamedResponse
from pydantic_ai.models.function import AgentInfo
from pydantic_ai.settings import ModelSettings
from pydantic_ai.tools import RunContext

from carapace.security.context import SENTINEL_VERDICT_TOOL, SessionSecurity
from carapace.security.sentinel import Sentinel
from carapace.session.compaction_summarizer import summary_agent
from carapace.session.titler import title_agent
from carapace.usage import LlmRequestLogCapability

from .streaming_model import ReplayStreamModel

# Differ between any two runs, streamed or not.
_VOLATILE_KEYS = {"timestamp", "run_id", "conversation_id"}


class _RecordingModel(ReplayStreamModel):
    def __init__(self) -> None:
        super().__init__(self._respond)
        self.requests: list[dict[str, Any]] = []
        self.streamed: list[bool] = []

    def _respond(self, messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        self.requests.append(_shape(messages, info))
        if info.output_tools:
            verdict = {"decision": "allow", "explanation": "x"}
            return ModelResponse(parts=[ToolCallPart(SENTINEL_VERDICT_TOOL, verdict, tool_call_id="v1")])
        return ModelResponse(parts=[TextPart("ok")])

    async def request(self, *args: Any, **kwargs: Any) -> ModelResponse:
        self.streamed.append(False)
        return await super().request(*args, **kwargs)

    @asynccontextmanager
    async def request_stream(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
        run_context: RunContext[Any] | None = None,
    ) -> AsyncIterator[StreamedResponse]:
        async with super().request_stream(messages, model_settings, model_request_parameters, run_context) as stream:
            self.streamed[-1] = True
            yield stream


def _shape(messages: list[ModelMessage], info: AgentInfo) -> dict[str, Any]:
    return {
        "instructions": info.instructions,
        "model_settings": info.model_settings,
        # Tools, output mode and native tools: everything besides the messages that reaches the provider.
        "parameters": info.model_request_parameters,
        "messages": _without_volatile(ModelMessagesTypeAdapter.dump_python(messages, mode="json")),
    }


def _without_volatile(value: Any) -> Any:
    match value:
        case dict():
            return {key: _without_volatile(item) for key, item in value.items() if key not in _VOLATILE_KEYS}
        case list():
            return [_without_volatile(item) for item in value]
        case _:
            return value


def _history() -> list[ModelMessage]:
    return [
        ModelRequest(parts=[UserPromptPart("earlier question")]),
        ModelResponse(parts=[ThinkingPart("weighing"), TextPart("earlier answer")]),
    ]


async def _titler(model: Model, _tmp_path: Path) -> None:
    agent = title_agent(model, model_id="test:model", model_settings=None)
    await agent.run("User: hi", message_history=_history())


async def _compaction(model: Model, _tmp_path: Path) -> None:
    agent = summary_agent(
        "Summarize.",
        prompt_prefix="Shared prefix.",
        model=model,
        model_id="test:model",
        model_settings=None,
        compaction_target="agent",
    )
    await agent.run("the text to fold", message_history=_history())


async def _sentinel(model: Model, tmp_path: Path) -> None:
    (tmp_path / "skills").mkdir(parents=True)
    sentinel = Sentinel(
        model="test:model",
        user="thies",
        knowledge_dir=tmp_path,
        skills_dir=tmp_path / "skills",
        llm_slots=None,
        model_factory=lambda _name, *, user: model,
    )
    session = SessionSecurity("s")
    # The second evaluation carries the first in its shadow conversation.
    await sentinel.evaluate_domain_access(session, ["example.com"], "ls", follow_up=False)
    await sentinel.evaluate_domain_access(session, ["example.com"], "pwd", follow_up=False)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("run_role", "requests"), [(_titler, 1), (_compaction, 1), (_sentinel, 2)], ids=["titler", "compaction", "sentinel"]
)
async def test_streaming_sends_the_same_requests(
    run_role: Callable[[Model, Path], Awaitable[None]],
    requests: int,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    streamed = _RecordingModel()
    await run_role(streamed, tmp_path / "streamed")

    # Without the on_event hook, pydantic-ai runs the role unstreamed again.
    monkeypatch.setattr(LlmRequestLogCapability, "on_event", AbstractCapability.on_event)
    unstreamed = _RecordingModel()
    await run_role(unstreamed, tmp_path / "unstreamed")

    assert streamed.streamed == [True] * requests and unstreamed.streamed == [False] * requests
    assert streamed.requests == unstreamed.requests
