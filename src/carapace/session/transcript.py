"""Transcript and model-history helpers for session branching."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ThinkingPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from ..security.context import SENTINEL_VERDICT_TOOL
from ..ws_models import Attachment
from .attachments import augment_prompt

# Proxy, git push and credential decisions are recorded as ``tool_call`` events so they render as
# tool calls (nested under the agent tool that triggered them, when there is one), but nothing ever
# answers them with a ``tool_result``.
_ACCESS_DECISION_TOOLS = frozenset({"proxy_domain", "git_push", "credential_access"})


@dataclass(frozen=True, slots=True)
class CompletedEventTurn:
    start_event_index: int
    end_event_index: int
    user_content: str


def awaits_tool_result(event: dict[str, Any]) -> bool:
    """Whether *event* is a tool call that stays open until a ``tool_result`` answers it.

    Access decisions are never answered, and denied calls never run, so a turn ending early
    leaves neither of them unfinished.
    """
    return (
        event.get("role") == "tool_call"
        and event.get("tool") not in _ACCESS_DECISION_TOOLS
        and event.get("approval_verdict") != "deny"
    )


def is_turn_prompt_event(event: dict[str, Any]) -> bool:
    """A turn starts at a user message; slash commands start none."""
    content = event.get("content")
    return event.get("role") == "user" and isinstance(content, str) and not content.startswith("/")


def is_turn_terminal_event(event: dict[str, Any]) -> bool:
    """A turn ends at its final assistant answer or at the error that ended it early.

    Partial assistant events are intermediate narration inside a turn, never its end.
    """
    match event.get("role"):
        case "error":
            return True
        case "assistant":
            return not event.get("partial")
        case _:
            return False


def completed_event_turns(events: list[dict[str, Any]]) -> list[CompletedEventTurn]:
    turns: list[CompletedEventTurn] = []
    start_event_index: int | None = None
    user_content: str | None = None

    for index, event in enumerate(events):
        if is_turn_prompt_event(event):
            start_event_index = index
            user_content = event["content"]
        elif is_turn_terminal_event(event) and start_event_index is not None and user_content is not None:
            turns.append(
                CompletedEventTurn(
                    start_event_index=start_event_index,
                    end_event_index=index,
                    user_content=user_content,
                )
            )
            start_event_index = None
            user_content = None

    return turns


def completed_model_turn_end_indexes(messages: list[ModelMessage]) -> list[int]:
    turn_end_indexes: list[int] = []
    current_turn_start: int | None = None

    for index, message in enumerate(messages):
        has_user_prompt = isinstance(message, ModelRequest) and any(
            isinstance(part, UserPromptPart) and isinstance(part.content, str) for part in message.parts
        )
        if not has_user_prompt:
            continue
        if (
            current_turn_start is not None
            and index - 1 > current_turn_start
            and is_terminal_history_message(messages[index - 1])
        ):
            turn_end_indexes.append(index - 1)
        current_turn_start = index

    if (
        current_turn_start is not None
        and len(messages) - 1 > current_turn_start
        and is_terminal_history_message(messages[-1])
    ):
        turn_end_indexes.append(len(messages) - 1)

    return turn_end_indexes


def is_terminal_history_message(message: ModelMessage) -> bool:
    if isinstance(message, ModelResponse):
        return True
    if not isinstance(message, ModelRequest):
        return False
    # Output tool returns end a turn: the unattended agent's task_done/task_failed and, in the
    # sentinel's shadow conversation, the verdict that ends an evaluation.
    return any(
        isinstance(part, ToolReturnPart) and part.tool_name in {"task_done", "task_failed", SENTINEL_VERDICT_TOOL}
        for part in message.parts
    )


def history_for_completed_turn_count(messages: list[ModelMessage], turn_count: int) -> list[ModelMessage]:
    if turn_count <= 0:
        return []

    turn_end_indexes = completed_model_turn_end_indexes(messages)
    if not turn_end_indexes:
        return []

    capped_turn_count = min(turn_count, len(turn_end_indexes))
    return messages[: turn_end_indexes[capped_turn_count - 1] + 1]


def rebuild_model_history_from_events(events: list[dict[str, Any]]) -> list[ModelMessage]:
    """Reconstruct an uncompacted model history from the (append-only) event transcript.

    The inverse of the message→event projection, used by ``/uncompact``. Faithful in content and
    order, pairing tool calls to returns by ``tool_id``. Lossy only where events do not record the
    detail: thinking parts are dropped (events never stored them; compaction drops them anyway) and
    each part becomes its own message rather than regrouping into the original turn. Slash-command
    user lines and non-conversational events (approvals, commands, …) are skipped.
    """
    paired_tool_ids = {e.get("tool_id") for e in events if e.get("role") == "tool_result"}
    # Provider tool-call ids ride only on tool_result events; map them back onto the paired call so
    # both the call and the return carry the model's id (not the carapace UUID), keeping tool pairing
    # intact on the next agent turn after /uncompact.
    provider_id_by_tool = {
        e["tool_id"]: e["model_tool_call_id"]
        for e in events
        if e.get("role") == "tool_result" and e.get("tool_id") and e.get("model_tool_call_id")
    }
    messages: list[ModelMessage] = []
    for event in events:
        role = event.get("role")
        if role == "user":
            content = event.get("content")
            if isinstance(content, str) and not content.startswith("/"):
                # Live history feeds the model the augmented prompt (attachment preamble + text);
                # the event stores only the raw text, so re-augment from persisted attachments.
                attachments = event.get("attachments")
                if isinstance(attachments, list) and attachments:
                    content = augment_prompt(content, [Attachment.model_validate(a) for a in attachments])
                messages.append(ModelRequest(parts=[UserPromptPart(content=content)]))
        elif role in {"assistant", "error"}:
            # A failed turn's error is part of the model history too (as the turn's final response),
            # so the model knows on the next turn that the previous one did not complete.
            content = event.get("content")
            if isinstance(content, str) and content:
                messages.append(ModelResponse(parts=[TextPart(content=content)]))
        elif role == "tool_call":
            tool_id = event.get("tool_id")
            if not isinstance(tool_id, str) or tool_id not in paired_tool_ids:
                continue  # unpaired (denied / incomplete) call — skip to keep call/return matched
            args = event.get("args") if isinstance(event.get("args"), dict) else {}
            call_id = provider_id_by_tool.get(tool_id, tool_id)
            messages.append(
                ModelResponse(parts=[ToolCallPart(tool_name=event.get("tool") or "", args=args, tool_call_id=call_id)])
            )
        elif role == "tool_result":
            tool_id = event.get("tool_id")
            if not isinstance(tool_id, str):
                continue
            result = event.get("result")
            call_id = provider_id_by_tool.get(tool_id, tool_id)
            messages.append(
                ModelRequest(
                    parts=[
                        ToolReturnPart(
                            tool_name=event.get("tool") or "",
                            content=result if isinstance(result, str) else str(result),
                            tool_call_id=call_id,
                        )
                    ]
                )
            )
    return messages


def normalize_unattended_output_history(messages: list[ModelMessage]) -> list[ModelMessage]:
    """Rewrite unattended task output tools into plain assistant text for attended forks."""
    normalized: list[ModelMessage] = []
    index = 0

    while index < len(messages):
        current = messages[index]
        next_message = messages[index + 1] if index + 1 < len(messages) else None

        if isinstance(current, ModelResponse):
            tool_call_parts = [part for part in current.parts if isinstance(part, ToolCallPart)]
            other_parts = [part for part in current.parts if not isinstance(part, ToolCallPart | ThinkingPart)]
            if (
                len(tool_call_parts) == 1
                and not other_parts
                and tool_call_parts[0].tool_name in {"task_done", "task_failed"}
                and isinstance(next_message, ModelRequest)
                and any(
                    isinstance(part, ToolReturnPart)
                    and part.tool_name == tool_call_parts[0].tool_name
                    and part.tool_call_id == tool_call_parts[0].tool_call_id
                    for part in next_message.parts
                )
            ):
                content = task_output_text(tool_call_parts[0])
                if content is not None:
                    normalized.append(replace(current, parts=[TextPart(content=content)]))
                    index += 2
                    continue

        normalized.append(current)
        index += 1

    return normalized


def task_output_text(part: ToolCallPart) -> str | None:
    args = part.args if isinstance(part.args, dict) else None
    if args is None:
        return None
    if part.tool_name == "task_done":
        value = args.get("result")
    elif part.tool_name == "task_failed":
        value = args.get("problem")
    else:
        return None
    return value if isinstance(value, str) and value else None
