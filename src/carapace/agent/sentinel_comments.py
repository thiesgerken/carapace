from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from pydantic_ai import RunContext
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.capabilities.abstract import ValidatedToolArgs
from pydantic_ai.messages import ToolCallPart, ToolReturn
from pydantic_ai.tools import ToolDefinition

from ..security.context import format_sentinel_comment
from .deps import Deps


@dataclass
class SentinelCommentCapability(AbstractCapability[Deps]):
    """Hands the agent the sentinel's comment on an allowed call together with the call's result.

    The comment travels in the tool result rather than as an extra prompt part: a ``UserPromptPart``
    would read as a user message, to the model and to the session history alike.
    """

    async def after_tool_execute(
        self,
        ctx: RunContext[Deps],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: ValidatedToolArgs,
        result: Any,
    ) -> Any:
        comment = ctx.deps.sentinel_comments.pop(call.tool_call_id, None)
        return result if comment is None else with_sentinel_comment(result, format_sentinel_comment(comment))


def with_sentinel_comment(result: Any, comment: str) -> Any:
    match result:
        case str():
            return f"{result}\n\n{comment}"
        case ToolReturn():
            return replace(result, return_value=with_sentinel_comment(result.return_value, comment))
        case _:
            # ponytail: structured MCP results get the comment as a second item; fold it in if models trip over it
            return [result, comment]
