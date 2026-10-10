"""Render a session's event transcript into the text a memory extraction model reads.

Pure and deterministic: the same events always render to the same text, so ``input_hash``
identifies the input and decides whether a session needs re-extraction.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict

from ..usage import count_text_tokens

# Bump whenever the rendered text changes for the same events.
INPUT_FORMAT_VERSION = 1

_CLAMP_HEAD = 600
_CLAMP_TAIL = 400


class ExtractionInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str
    input_hash: str
    token_estimate: int
    input_format_version: int


def render_extraction_input(events: list[dict[str, Any]]) -> ExtractionInput:
    """Render *events* (``SessionManager.load_events`` order) starting at the first user message.

    An event's list index is its ``seq``: session events are stored with contiguous seqs from 0.
    """
    start = next((seq for seq, event in enumerate(events) if _is_user_message(event)), len(events))
    blocks = [block for seq in range(start, len(events)) if (block := _render_event(seq, events[seq])) is not None]
    text = "\n\n".join(blocks)
    return ExtractionInput(
        text=text,
        input_hash=hashlib.sha256(text.encode()).hexdigest(),
        token_estimate=count_text_tokens(text),
        input_format_version=INPUT_FORMAT_VERSION,
    )


def _is_user_message(event: dict[str, Any]) -> bool:
    content = event.get("content")
    return event.get("role") == "user" and isinstance(content, str) and not content.startswith("/")


def _render_event(seq: int, event: dict[str, Any]) -> str | None:
    match event.get("role"):
        case "user":
            if not _is_user_message(event):
                return None
            content = event["content"]
            lines = [_attachment_line(a) for a in event.get("attachments") or []]
            return _block(f"#{seq} user", "\n".join([*lines, content] if content else lines))
        case "assistant":
            content = event.get("content")
            return _block(f"#{seq} assistant", content) if isinstance(content, str) and content else None
        case "tool_call":
            args = json.dumps(event.get("args") or {}, ensure_ascii=False, sort_keys=True, default=str)
            return _block(f"#{seq} tool_call {event.get('tool')}", clamp(args))
        case "tool_result":
            exit_code = event.get("exit_code")
            exit_suffix = f" exit={exit_code}" if exit_code else ""
            result = event.get("result")
            text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, default=str)
            return _block(f"#{seq} tool_result {event.get('tool')}{exit_suffix}", clamp(text))
        case _:
            return None


def _block(label: str, body: str) -> str:
    return f"[{label}]\n{body}"


def _attachment_line(attachment: dict[str, Any]) -> str:
    name = attachment["name"]
    mime = attachment.get("mime")
    return f"[attachment: {mime}, {name}]" if mime else f"[attachment: {name}]"


def clamp(text: str) -> str:
    """Keep head and tail of *text*: errors and exit codes sit at the end of tool outputs."""
    if len(text) <= _CLAMP_HEAD + _CLAMP_TAIL:
        return text
    elided = len(text) - _CLAMP_HEAD - _CLAMP_TAIL
    return f"{text[:_CLAMP_HEAD]}\n[… {elided:,} chars elided …]\n{text[-_CLAMP_TAIL:]}"
