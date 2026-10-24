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

import json
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic_ai import DeferredToolRequests, DeferredToolResults, ToolDenied
from pydantic_ai.messages import (
    PartDeltaEvent,
    PartStartEvent,
    TextPart,
    TextPartDelta,
    ThinkingPart,
    ThinkingPartDelta,
    ToolCallPart,
)
from pydantic_ai.usage import UsageLimits

from ..security.context import (
    AgentResponseEntry,
    ApprovalEntry,
    AuditEntry,
    SentinelVerdict,
    UserMessageEntry,
)
from ..usage import provider_cost_usd_from_messages
from ..ws_models import ApprovalRequest, FinalStatus
from .deps import Deps, TaskDone, TaskFailed
from .tools import create_agent


async def run_agent_turn(
    user_input: str,
    deps: Deps,
    message_history: list[Any],
    send_approval_request: Callable[[ApprovalRequest], Awaitable[None]],
    collect_approvals: Callable[[set[str]], Awaitable[dict[str, bool | ToolDenied]]],
    on_token: Callable[[str], Awaitable[None]] | None = None,
    on_thinking_token: Callable[[str], Awaitable[None]] | None = None,
    on_assistant_text: Callable[[str], Awaitable[None]] | None = None,
    on_messages_snapshot: Callable[[list[Any]], None] | None = None,
    before_llm_call: Callable[[], None] | None = None,
    get_usage_limits: Callable[[], UsageLimits | None] | None = None,
) -> tuple[list[Any], str, str, FinalStatus | None]:
    """Run one full agent turn, handling approval loops.

    Returns ``(updated_message_history, output_text, thinking_text, final_status)``.
    The caller is responsible for persisting history and delivering the output
    to the user.
    """
    deps.security.append(UserMessageEntry(content=user_input))

    agent = create_agent(deps)
    usage_model_key = deps.agent_model_id
    current_thinking_parts: list[str] = []
    # Text the model emits before a tool call is intermediate narration; we flush it as its own
    # assistant segment so it persists at its real position (between tool groups), not lumped into
    # the final answer at turn end. Trailing text (no tool after it) is the final output and is
    # handled by the caller — it is never flushed here.
    current_text_parts: list[str] = []
    last_thinking = ""

    async def _flush_text_segment() -> None:
        if not current_text_parts:
            return
        segment = "".join(current_text_parts)
        current_text_parts.clear()
        if segment.strip() and on_assistant_text is not None:
            await on_assistant_text(segment)

    async def _stream_handler(_ctx: Any, events: Any) -> None:
        async for event in events:
            if isinstance(event, PartStartEvent) and isinstance(event.part, ToolCallPart):
                await _flush_text_segment()
            elif isinstance(event, PartStartEvent) and isinstance(event.part, ThinkingPart) and event.part.content:
                current_thinking_parts.append(event.part.content)
                if on_thinking_token is not None:
                    await on_thinking_token(event.part.content)
            elif (
                isinstance(event, PartDeltaEvent)
                and isinstance(event.delta, ThinkingPartDelta)
                and event.delta.content_delta
            ):
                current_thinking_parts.append(event.delta.content_delta)
                if on_thinking_token is not None:
                    await on_thinking_token(event.delta.content_delta)
            elif isinstance(event, PartStartEvent) and isinstance(event.part, TextPart) and event.part.content:
                current_text_parts.append(event.part.content)
                if on_token is not None:
                    await on_token(event.part.content)
            elif isinstance(event, PartDeltaEvent) and isinstance(event.delta, TextPartDelta):
                current_text_parts.append(event.delta.content_delta)
                if on_token is not None:
                    await on_token(event.delta.content_delta)

    if before_llm_call is not None:
        before_llm_call()
    current_thinking_parts.clear()
    current_text_parts.clear()
    usage_limits = get_usage_limits() if get_usage_limits is not None else None
    result = await agent.run(
        user_input,
        deps=deps,
        message_history=message_history or None,
        event_stream_handler=_stream_handler,
        usage_limits=usage_limits,
    )
    last_thinking = "".join(current_thinking_parts)
    deps.usage_tracker.record(
        usage_model_key,
        "agent",
        result.usage,
        cost_usd=provider_cost_usd_from_messages(result.new_messages()),
    )
    messages = result.all_messages()
    if on_messages_snapshot is not None:
        on_messages_snapshot(list(messages))

    while isinstance(result.output, DeferredToolRequests):
        requests = result.output
        deferred_results = DeferredToolResults()

        for call in requests.approvals:
            args = call.args if isinstance(call.args, dict) else json.loads(call.args or "{}")
            meta = requests.metadata.get(call.tool_call_id, {})
            await send_approval_request(
                ApprovalRequest(
                    tool_call_id=call.tool_call_id,
                    tool=meta.get("tool", call.tool_name),
                    args=args,
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

            deps.security.append(
                ApprovalEntry(
                    tool=meta["tool"],
                    args=meta["args"],
                    decision=user_decision,
                ),
            )

            # Write the deferred audit entry now that the user has decided.
            sentinel_verdict = meta.get("sentinel_verdict")
            if isinstance(sentinel_verdict, SentinelVerdict):
                deps.security.write_audit(
                    AuditEntry.now(
                        kind="tool_call",
                        tool=meta.get("tool"),
                        args_summary=meta.get("args_summary", {}),
                        sentinel_verdict=sentinel_verdict,
                        final_decision="allowed" if decision is True else "denied",
                        explanation=meta.get("explanation"),
                    ),
                )

        if before_llm_call is not None:
            before_llm_call()
        current_thinking_parts.clear()
        # The just-finished sub-run ended in a deferred-tool request, not the final answer, so any
        # text it buffered is intermediate narration (e.g. emitted after its last tool call) — flush
        # it before the next run instead of dropping it.
        await _flush_text_segment()
        usage_limits = get_usage_limits() if get_usage_limits is not None else None
        result = await agent.run(
            deps=deps,
            message_history=messages,
            deferred_tool_results=deferred_results,
            event_stream_handler=_stream_handler,
            usage_limits=usage_limits,
        )
        last_thinking = "".join(current_thinking_parts)
        deps.usage_tracker.record(
            usage_model_key,
            "agent",
            result.usage,
            cost_usd=provider_cost_usd_from_messages(result.new_messages()),
        )
        messages = result.all_messages()
        if on_messages_snapshot is not None:
            on_messages_snapshot(list(messages))

    output_text: str | None = None
    final_status: FinalStatus | None = None
    if isinstance(result.output, str):
        output_text = result.output
    elif isinstance(result.output, TaskDone):
        output_text = result.output.result
        final_status = "success"
    elif isinstance(result.output, TaskFailed):
        output_text = result.output.problem
        final_status = "warning"

    if output_text is not None:
        last_usage = result.usage
        token_count = (last_usage.output_tokens or 0) + (last_usage.input_tokens or 0)
        deps.security.append(AgentResponseEntry(token_count=token_count))
        return messages, output_text, last_thinking, final_status

    output = f"Unexpected agent output type: {type(result.output).__name__}"
    return messages, output, last_thinking, None
