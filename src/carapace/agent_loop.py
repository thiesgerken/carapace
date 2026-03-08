"""Channel-agnostic agent turn runner.

Separates the core agent/approval loop from transport-specific code
(WebSocket, Matrix, etc.).  Callers inject two async callbacks:

- ``send_approval_request`` — called for each tool call that needs approval,
  passing the structured :class:`~carapace.ws_models.ApprovalRequest`.
- ``collect_approvals`` — called with the set of pending ``tool_call_id``
  strings; must return a mapping of id → ``True`` (approved) or a
  :class:`~pydantic_ai.ToolDenied` instance.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from pydantic_ai import DeferredToolRequests, DeferredToolResults, ToolDenied

import carapace.security as security
from carapace.agent import create_agent
from carapace.models import Deps
from carapace.security.context import (
    AgentResponseEntry,
    ApprovalEntry,
    AuditEntry,
    SentinelVerdict,
    UserMessageEntry,
)
from carapace.ws_models import ApprovalRequest


async def run_agent_turn(
    user_input: str,
    deps: Deps,
    message_history: list[Any],
    send_approval_request: Callable[[ApprovalRequest], Awaitable[None]],
    collect_approvals: Callable[[set[str]], Awaitable[dict[str, bool | ToolDenied]]],
) -> tuple[list[Any], str]:
    """Run one full agent turn, handling approval loops.

    Returns ``(updated_message_history, output_text)``.  The caller is
    responsible for persisting history and delivering the output to the user.
    """
    session_id = deps.session_state.session_id

    security.append_log(session_id, UserMessageEntry(content=user_input))

    agent = create_agent(deps)
    model_name = deps.config.agent.model

    result = await agent.run(
        user_input,
        deps=deps,
        message_history=message_history or None,
    )
    deps.usage_tracker.record(model_name, "agent", result.usage())
    messages = result.all_messages()

    while isinstance(result.output, DeferredToolRequests):
        requests = result.output
        deferred_results = DeferredToolResults()

        for call in requests.approvals:
            assert isinstance(call.args, dict)
            meta = requests.metadata.get(call.tool_call_id, {})
            await send_approval_request(
                ApprovalRequest(
                    tool_call_id=call.tool_call_id,
                    tool=meta.get("tool", call.tool_name),
                    args=call.args,
                    explanation=meta.get("explanation", ""),
                    risk_level=meta.get("risk_level", ""),
                )
            )

        pending_ids = {call.tool_call_id for call in requests.approvals}
        approvals = await collect_approvals(pending_ids)
        for tool_call_id, decision in approvals.items():
            deferred_results.approvals[tool_call_id] = decision

            meta = requests.metadata.get(tool_call_id, {})
            user_decision = "approved" if decision is True else "denied"

            security.append_log(
                session_id,
                ApprovalEntry(
                    tool=meta.get("tool", ""),
                    args_summary=str(meta.get("args", {}))[:200],
                    decision=user_decision,
                ),
            )

            # Write the deferred audit entry now that the user has decided.
            sentinel_verdict = meta.get("sentinel_verdict")
            if isinstance(sentinel_verdict, SentinelVerdict):
                security.write_audit(
                    session_id,
                    AuditEntry(
                        kind="tool_call",
                        tool=meta.get("tool", ""),
                        args_summary=meta.get("args_summary", {}),
                        sentinel_verdict=sentinel_verdict,
                        final_decision="allowed" if decision is True else "denied",
                        explanation=meta.get("explanation", ""),
                    ),
                )

        result = await agent.run(
            deps=deps,
            message_history=messages,
            deferred_tool_results=deferred_results,
        )
        deps.usage_tracker.record(model_name, "agent", result.usage())
        messages = result.all_messages()

    if isinstance(result.output, str):
        token_count = (result.usage().output_tokens or 0) + (result.usage().input_tokens or 0)
        security.append_log(session_id, AgentResponseEntry(token_count=token_count))
        return messages, result.output

    output = f"Unexpected agent output type: {type(result.output).__name__}"
    return messages, output
