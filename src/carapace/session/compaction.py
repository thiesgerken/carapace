"""Pure compaction strategies over pydantic-ai model history.

No I/O and no LLM calls live here: planning functions locate compaction *candidates* and
return the text to summarize; apply functions take already-produced summaries and rewrite
history + the compaction tree. The engine (see ``session/turns`` wiring) injects the real
compaction model. This keeps every strategy deterministically unit-testable.

Regions:
- Recent turns (kept verbatim): only tool-return compaction shrinks large outputs in place.
- Older history: message-fold collapses it into a summary. ``/compact`` cuts at a turn boundary;
  automatic compaction inside a run cuts at a step boundary (a model response plus its tool
  returns), so a single long turn can be folded too.

Representations in the model history:
- Folds roll: the history holds at most one fold, a synthetic ``ModelRequest`` with a single
  ``UserPromptPart`` whose text starts with ``FOLD_MARKER`` (provider-safe: it starts a turn with a
  user message). A new fold summarizes the previous fold together with the newly folded region.
- A compacted tool return keeps its ``ToolReturnPart`` (same ``tool_call_id`` → pairing intact);
  only ``content`` shrinks and ``metadata`` is stamped so it is never compacted twice.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    NativeToolCallPart,
    TextPart,
    ThinkingPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from ..models.compaction import FOLD_MARKER
from ..security.context import SENTINEL_VERDICT_TOOL
from ..usage import count_message_tokens, count_text_tokens
from .transcript import completed_model_turn_end_indexes

# Namespaced key stashed in ``ToolReturnPart.metadata`` to mark + describe a compacted output.
_META_KEY = "carapace_compaction"

_FOLD_HEADER = f"{FOLD_MARKER} Summary of earlier conversation, compacted to save context:\n\n"

_TOOL_MARKER = "[tool output summarized to save context; re-run the tool for the full result]\n"


# --------------------------------------------------------------------------- thinking-drop


def apply_thinking_drop(messages: list[ModelMessage]) -> tuple[list[ModelMessage], int]:
    """Drop ``ThinkingPart``s from every response except the newest turn's.

    Old thinking is dead weight in history (providers do not need it back) yet it is cheap to
    keep the most recent turn's reasoning for continuity.
    """
    # Keep thinking only inside the most recent completed turn (it starts after the
    # second-to-last turn boundary). With ≤1 completed turn, keep everything.
    turn_ends = completed_model_turn_end_indexes(messages)
    last_boundary = turn_ends[-2] if len(turn_ends) >= 2 else -1
    out: list[ModelMessage] = []
    dropped = 0
    for index, msg in enumerate(messages):
        if index > last_boundary or not isinstance(msg, ModelResponse):
            out.append(msg)
            continue
        kept_parts = [p for p in msg.parts if not isinstance(p, ThinkingPart)]
        dropped += len(msg.parts) - len(kept_parts)
        if not kept_parts:
            # A response that was nothing but thinking — drop the whole message.
            continue
        out.append(msg if len(kept_parts) == len(msg.parts) else replace(msg, parts=kept_parts))
    return out, dropped


# ---------------------------------------------------------------------- tool-return compaction


@dataclass(frozen=True, slots=True)
class ToolReturnCandidate:
    message_index: int
    part_index: int
    tool_name: str
    tool_call_id: str
    content: Any
    tokens: int


@dataclass(frozen=True, slots=True)
class AppliedToolReturn:
    """A produced replacement for one tool return (summary text + bookkeeping)."""

    new_content: str
    orig_tokens: int
    summary_tokens: int


def tool_return_compaction_info(part: ToolReturnPart) -> dict[str, Any] | None:
    """The stamped compaction record on a tool return, or None if not compacted."""
    meta = part.metadata
    if isinstance(meta, dict) and isinstance(info := meta.get(_META_KEY), dict):
        return info
    return None


def tool_return_is_compacted(part: ToolReturnPart) -> bool:
    return tool_return_compaction_info(part) is not None


def find_tool_return_candidates(
    messages: list[ModelMessage],
    *,
    floor_tokens: int,
    model_name: str | None = None,
    within_indexes: set[int] | None = None,
) -> list[ToolReturnCandidate]:
    """Large, not-yet-compacted tool returns, largest first.

    ``within_indexes`` restricts to message indexes in the kept (verbatim) region so we never
    touch outputs that a fold is about to absorb.
    """
    candidates: list[ToolReturnCandidate] = []
    for mi, msg in enumerate(messages):
        if within_indexes is not None and mi not in within_indexes:
            continue
        if not isinstance(msg, ModelRequest):
            continue
        for pi, part in enumerate(msg.parts):
            # Exact type only — capability-return subclasses narrow ``content`` and must not be compacted.
            if type(part) is not ToolReturnPart or tool_return_is_compacted(part):
                continue
            tokens = count_text_tokens(_tool_content_text(part.content), model_name=model_name)
            if tokens < floor_tokens:
                continue
            candidates.append(
                ToolReturnCandidate(
                    message_index=mi,
                    part_index=pi,
                    tool_name=part.tool_name,
                    tool_call_id=part.tool_call_id,
                    content=part.content,
                    tokens=tokens,
                )
            )
    candidates.sort(key=lambda c: c.tokens, reverse=True)
    return candidates


def tool_return_compaction_region(messages: list[ModelMessage], *, verbatim_turns: int) -> set[int]:
    """Message indexes whose tool returns may be compacted.

    Only the kept region (never inside a fold block) and never the verbatim hot zone: the newest
    *verbatim_turns* completed turns, so the latest work keeps exact fidelity. 0 disables the hot zone.
    """
    _lead, rest = split_lead_folds(messages)
    offset = len(messages) - len(rest)
    turn_ends = completed_model_turn_end_indexes(rest)
    if verbatim_turns <= 0:
        cut = len(rest)
    elif len(turn_ends) <= verbatim_turns:
        return set()
    else:
        cut = turn_ends[len(turn_ends) - verbatim_turns - 1] + 1
    return set(range(offset, offset + cut))


def apply_tool_return_compaction(
    messages: list[ModelMessage],
    applied: dict[str, AppliedToolReturn],
) -> list[ModelMessage]:
    """Replace tool-return content with summaries, keyed by ``tool_call_id``; stamp metadata."""
    if not applied:
        return messages
    out: list[ModelMessage] = []
    for msg in messages:
        if not isinstance(msg, ModelRequest):
            out.append(msg)
            continue
        changed = False
        new_parts: list[Any] = []
        for part in msg.parts:
            if type(part) is ToolReturnPart and part.tool_call_id in applied and not tool_return_is_compacted(part):
                rep = applied[part.tool_call_id]
                meta = dict(part.metadata) if isinstance(part.metadata, dict) else {}
                meta[_META_KEY] = {
                    "compacted": True,
                    "orig_tokens": rep.orig_tokens,
                    "summary_tokens": rep.summary_tokens,
                }
                # Rebuild as a base ToolReturnPart (str content) — never a capability subclass.
                new_parts.append(
                    ToolReturnPart(
                        tool_name=part.tool_name,
                        content=_TOOL_MARKER + rep.new_content,
                        tool_call_id=part.tool_call_id,
                        metadata=meta,
                        timestamp=part.timestamp,
                    )
                )
                changed = True
            else:
                new_parts.append(part)
        out.append(replace(msg, parts=new_parts) if changed else msg)
    return out


def truncate_tool_output(content: Any, *, head_lines: int = 12, tail_lines: int = 12, max_chars: int = 4000) -> str:
    """Deterministic (no-LLM) cut: keep head + tail lines, then head + tail characters, elide the middle.

    The character cap catches what the line cut cannot: minified JSON and other single-line dumps.
    """
    text = _tool_content_text(content)
    lines = text.splitlines()
    if len(lines) > head_lines + tail_lines:
        elided = len(lines) - head_lines - tail_lines
        text = "\n".join([*lines[:head_lines], f"… [{elided} lines elided] …", *lines[-tail_lines:]])
    if len(text) > max_chars:
        half = max_chars // 2
        text = f"{text[:half]}… [{len(text) - 2 * half} characters elided] …{text[-half:]}"
    return text


# -------------------------------------------------------------------------------- message-fold


@dataclass(frozen=True, slots=True)
class FoldPlan:
    """Fold ``lead_folds`` (the earlier summary, if any) and ``foldable`` into one summary; keep ``kept``."""

    lead_folds: list[ModelMessage]
    foldable: list[ModelMessage]
    kept: list[ModelMessage]
    # Tokens of the newly folded region only; the earlier summary's originals are counted in its node.
    orig_tokens: int


def is_fold_message(msg: ModelMessage) -> bool:
    return (
        isinstance(msg, ModelRequest)
        and len(msg.parts) == 1
        and isinstance(msg.parts[0], UserPromptPart)
        and isinstance(msg.parts[0].content, str)
        and msg.parts[0].content.startswith(FOLD_MARKER)
    )


def split_lead_folds(messages: list[ModelMessage]) -> tuple[list[ModelMessage], list[ModelMessage]]:
    i = 0
    while i < len(messages) and is_fold_message(messages[i]):
        i += 1
    return messages[:i], messages[i:]


def slice_compacted_history(
    messages: list[ModelMessage], *, tail_turns: int, keep_split_turn: bool
) -> list[ModelMessage]:
    """Slice a folded history to its fold plus *tail_turns* verbatim turns.

    Fold-aware counterpart to ``history_for_completed_turn_count``, used by reset/fork when the
    history's fold survives the cut. The fold is atomic and stays. The verbatim steps right after it
    that finish a turn the fold cut in two (they come before the first user prompt) stay when that
    turn does: always below kept verbatim turns, otherwise as *keep_split_turn* says.
    """
    lead, rest = split_lead_folds(messages)
    ends = completed_model_turn_end_indexes(rest)
    if tail_turns <= 0 or not ends:
        first_prompt = next((i for i, m in enumerate(rest) if _has_user_prompt(m)), len(rest))
        return lead + rest[:first_prompt] if keep_split_turn else lead
    return lead + rest[: ends[min(tail_turns, len(ends)) - 1] + 1]


def make_fold_message(summary: str) -> ModelRequest:
    return ModelRequest(parts=[UserPromptPart(content=_FOLD_HEADER + summary)])


def plan_fold(messages: list[ModelMessage], *, keep_turns: int, model_name: str | None = None) -> FoldPlan | None:
    """Plan folding everything older than the last ``keep_turns`` completed turns.

    Returns ``None`` when there is nothing to fold (too few completed turns).
    """
    lead_folds, rest = split_lead_folds(messages)
    turn_ends = completed_model_turn_end_indexes(rest)
    keep_turns = max(1, keep_turns)
    if len(turn_ends) <= keep_turns:
        return None
    return _fold_plan(lead_folds, rest, turn_ends[-keep_turns - 1] + 1, model_name=model_name)


def plan_step_fold(messages: list[ModelMessage], *, keep_tokens: int, model_name: str | None = None) -> FoldPlan | None:
    """Plan folding everything but the newest steps that together fit *keep_tokens*.

    A step starts at a model response and runs through its tool returns, so a cut before a response
    never separates a tool call from its return. The newest step always stays, however large: the
    model is mid-way through it. Returns ``None`` when there is no older step to fold.
    """
    lead_folds, rest = split_lead_folds(messages)
    step_starts = [i for i, m in enumerate(rest) if isinstance(m, ModelResponse)]
    if not step_starts:
        return None
    sizes = [count_message_tokens([m], model_name=model_name) for m in rest]
    cut = step_starts[-1]
    for start in reversed(step_starts[:-1]):
        if sum(sizes[start:]) > keep_tokens:
            break
        cut = start
    return _fold_plan(lead_folds, rest, cut, model_name=model_name) if cut > 0 else None


def _fold_plan(
    lead_folds: list[ModelMessage], rest: list[ModelMessage], cut: int, *, model_name: str | None
) -> FoldPlan:
    foldable = rest[:cut]
    return FoldPlan(
        lead_folds=lead_folds,
        foldable=foldable,
        kept=rest[cut:],
        orig_tokens=count_message_tokens(foldable, model_name=model_name),
    )


def apply_fold(plan: FoldPlan, summary: str) -> list[ModelMessage]:
    """Build the new history: the rolled-up summary, then the kept verbatim region."""
    return [make_fold_message(summary), *plan.kept]


def fold_render_text(messages: list[ModelMessage]) -> str:
    """Flatten an earlier fold plus a foldable region to plain text for the summarizer prompt.

    Tool calls keep their arguments (the paths, commands and URLs the summary must name). Arguments
    and tool returns are cut head/tail, so a few huge outputs cannot push the region past the
    compaction model's context window.
    """
    lines: list[str] = []
    for msg in messages:
        if is_fold_message(msg):
            lines.append(f"Earlier summary: {fold_summary_text(msg)}")
            continue
        for part in msg.parts:
            match part:
                case UserPromptPart(content=str() as content):
                    lines.append(f"User: {content}")
                case ToolReturnPart(tool_name=tool_name):
                    lines.append(f"Tool[{tool_name}] result: {truncate_tool_output(part.content)}")
                case TextPart(content=content):
                    lines.append(f"Assistant: {content}")
                case ToolCallPart() | NativeToolCallPart():
                    lines.append(f"Assistant called {part.tool_name}({truncate_tool_output(part.args_as_json_str())})")
                case _:
                    pass
    return "\n".join(lines)


def split_merged_requests(messages: list[ModelMessage]) -> list[ModelMessage]:
    """Undo pydantic-ai's merge of consecutive requests: tool returns, then one request per prompt.

    Every run merges consecutive ``ModelRequest``s of its history and persists the result, so an
    output tool's return (the sentinel's verdict, the unattended agent's ``task_done``) absorbs the
    next prompt, and a fold message absorbs the prompt after it. Turn boundaries and fold detection
    need them apart again; a fold cut inside a merged request would also keep a tool return whose
    call was folded away.
    """
    out: list[ModelMessage] = []
    for msg in messages:
        if not isinstance(msg, ModelRequest) or len(msg.parts) == 1:
            out.append(msg)
            continue
        others = [p for p in msg.parts if not isinstance(p, UserPromptPart)]
        prompts = [p for p in msg.parts if isinstance(p, UserPromptPart)]
        groups = ([others] if others else []) + [[p] for p in prompts]
        out += [replace(msg, parts=group) for group in groups]
    return out


def sentinel_fold_render_text(messages: list[ModelMessage]) -> str:
    """Flatten folded sentinel evaluations for the summarizer.

    Unlike ``fold_render_text`` it never cuts tool-call arguments: the verdict lives in them.
    """
    lines: list[str] = []
    for msg in messages:
        if is_fold_message(msg):
            lines.append(f"Earlier summary: {fold_summary_text(msg)}")
            continue
        for part in msg.parts:
            match part:
                case UserPromptPart(content=str() as content):
                    lines.append(f"Evaluation request: {content}")
                case ToolReturnPart(tool_name=tool_name) if tool_name != SENTINEL_VERDICT_TOOL:
                    lines.append(f"Tool[{tool_name}] result: {_tool_content_text(part.content)}")
                case TextPart(content=content):
                    lines.append(f"Sentinel: {content}")
                case ToolCallPart(tool_name=tool_name) if tool_name == SENTINEL_VERDICT_TOOL:
                    lines.append(f"Sentinel verdict: {part.args_as_json_str()}")
                case ToolCallPart(tool_name=tool_name):
                    lines.append(f"Sentinel called {tool_name}({part.args_as_json_str()})")
                case _:
                    pass
    return "\n".join(lines)


def strip_thinking(messages: list[ModelMessage]) -> list[ModelMessage]:
    """*messages* without any ``ThinkingPart`` (for token estimates, not for the model)."""
    return [
        replace(m, parts=[p for p in m.parts if not isinstance(p, ThinkingPart)]) if isinstance(m, ModelResponse) else m
        for m in messages
    ]


def user_prompt_count(messages: list[ModelMessage]) -> int:
    """How many turns start in *messages* (fold messages are no turns)."""
    return sum(_has_user_prompt(m) and not is_fold_message(m) for m in messages)


def last_request_input_tokens(messages: list[ModelMessage]) -> int:
    """Provider-reported input tokens of the newest model response's request (0 if none reported)."""
    response = next((m for m in reversed(messages) if isinstance(m, ModelResponse)), None)
    return response.usage.input_tokens if response is not None else 0


def fold_summary_text(fold: ModelMessage) -> str:
    content = fold.parts[0].content if isinstance(fold.parts[0], UserPromptPart) else ""
    return content.removeprefix(_FOLD_HEADER).strip() if isinstance(content, str) else ""


# ---------------------------------------------------------------------------------------- utils


def _has_user_prompt(msg: ModelMessage) -> bool:
    return isinstance(msg, ModelRequest) and any(
        isinstance(p, UserPromptPart) and isinstance(p.content, str) for p in msg.parts
    )


def _tool_content_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, (list, tuple)):
        return "\n".join(_tool_content_text(item) for item in content)
    return str(content)
