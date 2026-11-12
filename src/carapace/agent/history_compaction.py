"""Compaction inside an agent run, so a long autonomous turn never outgrows the context window."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from pydantic_ai import RunContext
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models import ModelRequestContext

from .deps import Deps

HistoryCompactor = Callable[[list[ModelMessage]], Awaitable[list[ModelMessage] | None]]


@dataclass
class HistoryCompactionCapability(AbstractCapability[Deps]):
    """Before each model request, lets *compact* replace the run's history (None keeps it).

    The replacement goes through ``ctx.messages``, so the rest of the run and the saved turn continue
    from the compacted history, and into the pending request. A failed compaction raises and fails
    the turn through the regular error path. Register it before the request log capability, which
    records the request as it finally goes out.
    """

    compact: HistoryCompactor

    async def before_model_request(
        self, ctx: RunContext[Deps], request_context: ModelRequestContext
    ) -> ModelRequestContext:
        compacted = await self.compact(list(ctx.messages))
        if compacted is None:
            return request_context
        ctx.messages[:] = compacted
        request_context.messages = list(compacted)
        return request_context
