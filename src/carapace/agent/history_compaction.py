"""Compaction inside an agent run, so a long autonomous turn never outgrows the context window."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pydantic_ai import RunContext
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.messages import CompactionPart, ModelMessage, ModelResponse
from pydantic_ai.models import ModelRequestContext
from pydantic_ai.tools import AgentDepsT

HistoryCompactor = Callable[[list[ModelMessage]], Awaitable[list[ModelMessage] | None]]


@dataclass
class HistoryCompactionCapability(AbstractCapability[AgentDepsT]):
    """Before each model request, lets *compact* replace the run's history (None keeps it).

    The replacement goes through ``ctx.messages``, so the rest of the run and the saved turn continue
    from the compacted history, and into the pending request. A failed compaction raises and fails
    the turn through the regular error path. Register it before the request log capability, which
    records the request as it finally goes out.
    """

    compact: HistoryCompactor

    async def before_model_request(
        self, ctx: RunContext[AgentDepsT], request_context: ModelRequestContext
    ) -> ModelRequestContext:
        compacted = await self.compact(list(ctx.messages))
        if compacted is None:
            return request_context
        ctx.messages[:] = compacted
        request_context.messages = list(compacted)
        return request_context


@dataclass
class ProviderCompactionMarkerCapability(AbstractCapability[AgentDepsT]):
    """Records a ``compaction`` event when a response carries a provider's ``CompactionPart``.

    The part itself stays in the model history; the event marks the spot in the transcript for the UI.
    A response may carry several parts (OpenAI can compact before and after its answer); the newest one
    supersedes the others, so one marker shows that one.
    """

    append_events: Callable[[list[dict[str, Any]]], None]

    async def after_model_request(
        self, ctx: RunContext[AgentDepsT], *, request_context: ModelRequestContext, response: ModelResponse
    ) -> ModelResponse:
        if parts := [part for part in response.parts if isinstance(part, CompactionPart)]:
            newest = parts[-1]
            self.append_events([{"role": "compaction", "provider": newest.provider_name, "summary": newest.content}])
        return response
