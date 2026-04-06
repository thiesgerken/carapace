from __future__ import annotations

import json
from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, TypedDict

import tiktoken
from pydantic import BaseModel, Field
from pydantic_ai.capabilities.abstract import AbstractCapability
from pydantic_ai.messages import (
    BuiltinToolCallPart,
    BuiltinToolReturnPart,
    FilePart,
    ModelMessage,
    ModelRequest,
    ModelRequestPart,
    ModelResponse,
    ModelResponsePart,
    RetryPromptPart,
    SystemPromptPart,
    TextPart,
    ThinkingPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models import ModelRequestContext
from pydantic_ai.tools import AgentDepsT, RunContext

LlmSource = Literal["agent", "sentinel"]

_llm_request_sink: ContextVar[Callable[[LlmRequestRecord], None] | None] = ContextVar(
    "llm_request_sink",
    default=None,
)


@contextmanager
def llm_request_sink_scope(sink: Callable[[LlmRequestRecord], None] | None) -> Any:
    token = _llm_request_sink.set(sink)
    try:
        yield
    finally:
        _llm_request_sink.reset(token)


class InputShapeRatios(BaseModel):
    """Relative shares of estimated tiktoken mass per bucket (sum ≈ 1). Not billing tokens."""

    system: float = 0.0
    user: float = 0.0
    assistant: float = 0.0
    tool_calls: float = 0.0
    tool_returns: float = 0.0
    other: float = 0.0


class LlmRequestRecord(BaseModel):
    ts: datetime
    source: LlmSource
    model_name: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    usage_details: dict[str, int] = Field(default_factory=dict)
    input_shape: InputShapeRatios | None = None


class LlmRequestLog(BaseModel):
    records: list[LlmRequestRecord] = Field(default_factory=list)


def last_record_for_source(log: LlmRequestLog, source: LlmSource) -> LlmRequestRecord | None:
    for rec in reversed(log.records):
        if rec.source == source:
            return rec
    return None


class _BreakdownPct(TypedDict):
    """Percent of tiktoken mass across prompt buckets only (sum 100). Not derived from API token counts."""

    system: float | None
    user: float | None
    assistant: float | None
    tool_calls: float | None
    tool_returns: float | None
    other: float | None


class UsageLastRequestRow(TypedDict):
    source: LlmSource
    input_tokens: int
    output_tokens: int
    context_size: int
    breakdown_pct: _BreakdownPct


def usage_last_request_row(rec: LlmRequestRecord | None) -> UsageLastRequestRow | None:
    """API fields from provider; breakdown_pct = tiktoken input-shape ratios as percentages (sum 100)."""
    if rec is None:
        return None
    inp, out = rec.input_tokens, rec.output_tokens
    if rec.input_shape is not None:
        s = rec.input_shape
        breakdown_pct: _BreakdownPct = {
            "system": 100.0 * s.system,
            "user": 100.0 * s.user,
            "assistant": 100.0 * s.assistant,
            "tool_calls": 100.0 * s.tool_calls,
            "tool_returns": 100.0 * s.tool_returns,
            "other": 100.0 * s.other,
        }
    else:
        breakdown_pct = {
            "system": None,
            "user": None,
            "assistant": None,
            "tool_calls": None,
            "tool_returns": None,
            "other": None,
        }
    return {
        "source": rec.source,
        "input_tokens": inp,
        "output_tokens": out,
        "context_size": inp + out,
        "breakdown_pct": breakdown_pct,
    }


def gauge_breakdown_pct_dict(rec: LlmRequestRecord | None) -> dict[str, float] | None:
    """Shape percents for the web token gauge (all six keys, sum 100). ``None`` if no tiktoken shape."""
    row = usage_last_request_row(rec)
    if row is None:
        return None
    b = row["breakdown_pct"]
    if all(v is None for v in b.values()):
        return None
    return {k: float(v) for k, v in b.items()}


def _encoding_for_model(model_name: str | None) -> tiktoken.Encoding:
    key = (model_name or "").lower()
    if any(x in key for x in ("gpt-4o", "gpt-5", "o1", "o3", "o4")):
        return tiktoken.get_encoding("o200k_base")
    return tiktoken.get_encoding("cl100k_base")


def _count_text(enc: tiktoken.Encoding, text: str) -> int:
    if not text:
        return 0
    return len(enc.encode(text))


def _blob(x: Any) -> str:
    try:
        return json.dumps(x, sort_keys=True, default=str)
    except TypeError:
        return str(x)


def _user_prompt_blob(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, (list, tuple)):
        parts: list[str] = []
        for item in content:
            parts.append(_blob(item))
        return "\n".join(parts)
    return _blob(content)


def _tool_return_blob(content: Any) -> str:
    return _blob(content)


def _file_part_blob(part: FilePart) -> str:
    try:
        return f"<file {part.content.media_type} bytes={len(part.content.data)}>"
    except Exception:
        return "<file>"


def _accumulate_request_part(part: ModelRequestPart, buckets: dict[str, str]) -> None:
    if isinstance(part, SystemPromptPart):
        buckets["system"] += part.content + "\n"
    elif isinstance(part, UserPromptPart):
        buckets["user"] += _user_prompt_blob(part.content) + "\n"
    elif isinstance(part, ToolReturnPart):
        buckets["tool_returns"] += f"{part.tool_name}\n{_tool_return_blob(part.content)}\n"
    elif isinstance(part, RetryPromptPart):
        buckets["user"] += part.model_response() + "\n"


def _accumulate_response_part(part: ModelResponsePart, buckets: dict[str, str]) -> None:
    if isinstance(part, TextPart | ThinkingPart):
        buckets["assistant"] += part.content + "\n"
    elif isinstance(part, ToolCallPart | BuiltinToolCallPart):
        buckets["tool_calls"] += f"{part.tool_name}\n{part.args_as_json_str()}\n"
    elif isinstance(part, BuiltinToolReturnPart):
        buckets["tool_returns"] += f"{part.tool_name}\n{_tool_return_blob(part.content)}\n"
    elif isinstance(part, FilePart):
        buckets["other"] += _file_part_blob(part) + "\n"
    else:
        buckets["other"] += _blob(part) + "\n"


def input_shape_ratios_from_messages(
    messages: list[ModelMessage],
    *,
    model_name: str | None,
) -> InputShapeRatios | None:
    buckets = {k: "" for k in ("system", "user", "assistant", "tool_calls", "tool_returns", "other")}
    for msg in messages:
        if isinstance(msg, ModelRequest):
            if msg.instructions:
                buckets["system"] += msg.instructions + "\n"
            for p in msg.parts:
                _accumulate_request_part(p, buckets)
        elif isinstance(msg, ModelResponse):
            for p in msg.parts:
                _accumulate_response_part(p, buckets)

    enc = _encoding_for_model(model_name)
    counts = {k: _count_text(enc, v) for k, v in buckets.items()}
    total = sum(counts.values())
    if total <= 0:
        return None
    return InputShapeRatios(
        system=counts["system"] / total,
        user=counts["user"] / total,
        assistant=counts["assistant"] / total,
        tool_calls=counts["tool_calls"] / total,
        tool_returns=counts["tool_returns"] / total,
        other=counts["other"] / total,
    )


@dataclass
class LlmRequestLogCapability(AbstractCapability[AgentDepsT]):
    """Append one persisted record per HTTP model response (via ContextVar sink)."""

    source: LlmSource

    async def after_model_request(
        self,
        ctx: RunContext[AgentDepsT],
        *,
        request_context: ModelRequestContext,
        response: ModelResponse,
    ) -> ModelResponse:
        sink = _llm_request_sink.get()
        if sink is None:
            return response

        usage = response.usage
        details = {k: int(v) for k, v in (usage.details or {}).items() if isinstance(v, int)}
        model_name = response.model_name or request_context.model.model_name
        shape = input_shape_ratios_from_messages(
            request_context.messages,
            model_name=model_name,
        )
        record = LlmRequestRecord(
            ts=datetime.now(tz=UTC),
            source=self.source,
            model_name=model_name,
            input_tokens=usage.input_tokens or 0,
            output_tokens=usage.output_tokens or 0,
            usage_details=details,
            input_shape=shape,
        )
        sink(record)
        return response
