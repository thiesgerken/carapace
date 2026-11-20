from __future__ import annotations

from dataclasses import dataclass

from pydantic_ai import RunContext
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.messages import SystemPromptPart
from pydantic_ai.models import ModelRequestContext

from .deps import Deps


@dataclass
class SentinelCommentCapability(AbstractCapability[Deps]):
    """Hands the agent the sentinel's comments on allowed operations as system messages.

    The comments go into the request that carries the tool results, in the system voice: tool output
    is untrusted and could forge a comment, and a user prompt part would read as the user speaking.
    """

    async def before_model_request(
        self, ctx: RunContext[Deps], request_context: ModelRequestContext
    ) -> ModelRequestContext:
        for comment in ctx.deps.security.take_comments_for_agent():
            ctx.enqueue(SystemPromptPart(comment))
        return request_context
