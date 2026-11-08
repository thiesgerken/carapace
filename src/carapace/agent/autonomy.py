"""Autonomy limit: caps the tool calls the agent attempts since the last human interaction.

This is loop protection, not security, so it applies in YOLO mode too. The streak lives in memory
on the active session; a server restart resets it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic_ai import ApprovalRequired, ToolDenied
from pydantic_ai.capabilities.abstract import AbstractCapability, ValidatedToolArgs, WrapToolExecuteHandler
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.tools import AgentDepsT, RunContext, ToolDefinition

from ..models.session import SessionState
from ..models.tooling import ToolCallCallback
from ..usage import SessionBudgetExceededError, autonomy_budget_gauge

AUTONOMY_WRAP_UP = "Autonomy limit reached. Stop calling tools and report what you have."

# Marks approval requests raised by the autonomy limit in the deferred tool metadata.
AUTONOMY_LIMIT_METADATA_KEY = "autonomy_limit"


class AutonomyLimitReachedError(SessionBudgetExceededError):
    """The agent kept calling tools after its over-limit calls were denied; ends the turn."""


@dataclass
class AutonomyStreak:
    """Tool call attempts since the last human interaction."""

    count: int = 0
    # The calls whose over-limit attempts were denied. Any other call after them ends the turn.
    stopped_batch: frozenset[str] | None = None

    def reset(self) -> None:
        self.count = 0
        self.stopped_batch = None

    def stop_after(self, batch: frozenset[str]) -> None:
        self.stopped_batch = batch

    def count_attempt(self, tool_call_id: str, limit: int | None) -> bool:
        """Count one attempt and return whether it is over *limit*.

        Raises ``AutonomyLimitReachedError`` for a call outside the stopped batch.
        """
        if self.stopped_batch is not None and tool_call_id not in self.stopped_batch:
            if limit is not None and self.count >= limit:
                raise AutonomyLimitReachedError([autonomy_budget_gauge(self.count, limit)])
            # The limit was raised or cleared since the stop.
            self.stopped_batch = None
        self.count += 1
        return limit is not None and self.count > limit


def resolve_user_approvals(
    streak: AutonomyStreak,
    decisions: dict[str, bool | ToolDenied],
    autonomy_call_ids: set[str],
) -> dict[str, bool | ToolDenied]:
    """Apply the streak reset rules to one batch of user decisions.

    Any allow, or a deny of anything but an autonomy-limit approval, is a human interaction and
    resets the streak. If the user denied every autonomy-limit approval and nothing else, the next
    tool call ends the turn. Denied autonomy-limit calls tell the model to wrap up.
    """
    autonomy_decisions = {call_id: d for call_id, d in decisions.items() if call_id in autonomy_call_ids}
    other_decisions = [d for call_id, d in decisions.items() if call_id not in autonomy_call_ids]
    if other_decisions or any(d is True for d in autonomy_decisions.values()):
        streak.reset()
    elif autonomy_decisions:
        streak.stop_after(frozenset(autonomy_decisions))
    return {
        call_id: ToolDenied(f"{d.message} {AUTONOMY_WRAP_UP}")
        if isinstance(d, ToolDenied) and call_id in autonomy_call_ids
        else d
        for call_id, d in decisions.items()
    }


def _batch_tool_call_ids(messages: list[ModelMessage]) -> frozenset[str]:
    """Tool call ids of the model response whose calls are running now (the last one in the history)."""
    response = next(message for message in reversed(messages) if isinstance(message, ModelResponse))
    return frozenset(part.tool_call_id for part in response.parts if isinstance(part, ToolCallPart))


@dataclass
class AutonomyLimitCapability(AbstractCapability[AgentDepsT]):
    """Counts every tool call attempt and holds back the ones over the autonomy limit.

    Attended sessions ask the user (one approval per call); unattended sessions deny with a
    wrap-up instruction, and the next call after that ends the turn.
    """

    streak: AutonomyStreak
    # Read live, so a limit changed during the turn applies to the next call.
    session_state: SessionState
    tool_call_callback: ToolCallCallback | None

    async def wrap_tool_execute(
        self,
        ctx: RunContext[AgentDepsT],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: ValidatedToolArgs,
        handler: WrapToolExecuteHandler,
    ) -> Any:
        # Output tools are the answer, not an action. An approved call was counted when it asked.
        if tool_def.kind != "function" or ctx.tool_call_approved:
            return await handler(args)
        limit = self.session_state.budget.autonomous_tool_calls
        if not self.streak.count_attempt(call.tool_call_id, limit):
            return await handler(args)
        reason = f"Autonomy limit reached ({limit} tool calls without you)"
        if not self.session_state.attributes.unattended:
            raise ApprovalRequired(
                metadata={
                    "tool": call.tool_name,
                    "args": args,
                    "explanation": reason,
                    AUTONOMY_LIMIT_METADATA_KEY: True,
                }
            )
        self.streak.stop_after(_batch_tool_call_ids(ctx.messages))
        if self.tool_call_callback is not None:
            self.tool_call_callback(call.tool_name, args, f"[autonomy] {reason}", "autonomy", "deny", reason)
        return ToolDenied(AUTONOMY_WRAP_UP)
