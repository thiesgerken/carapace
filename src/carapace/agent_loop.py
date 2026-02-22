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

from carapace.agent import create_agent
from carapace.models import Deps
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
                    classification=meta.get("classification", {}),
                    triggered_rules=meta.get("triggered_rules", []),
                    descriptions=meta.get("descriptions", []),
                )
            )

        pending_ids = {call.tool_call_id for call in requests.approvals}
        approvals = await collect_approvals(pending_ids)
        for tool_call_id, decision in approvals.items():
            deferred_results.approvals[tool_call_id] = decision

        result = await agent.run(
            deps=deps,
            message_history=messages,
            deferred_tool_results=deferred_results,
        )
        deps.usage_tracker.record(model_name, "agent", result.usage())
        messages = result.all_messages()

    if isinstance(result.output, str):
        return messages, result.output

    output = f"Unexpected agent output type: {type(result.output).__name__}"
    return messages, output
