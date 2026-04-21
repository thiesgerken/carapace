from __future__ import annotations

import json
import secrets
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal, Protocol, TypedDict, assert_never

import tiktoken
from genai_prices import Usage as PriceUsage
from genai_prices import calc_price
from loguru import logger
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
from pydantic_ai.usage import RunUsage


class ModelUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    input_audio_tokens: int = 0
    output_audio_tokens: int = 0
    cache_audio_read_tokens: int = 0
    requests: int = 0


def _price_for_usage(model_key: str, u: ModelUsage) -> Decimal | None:
    provider_id, _, model_ref = model_key.partition(":")
    if not model_ref:
        model_ref, provider_id = provider_id, None
    try:
        return calc_price(
            PriceUsage(
                input_tokens=u.input_tokens,
                output_tokens=u.output_tokens,
                cache_read_tokens=u.cache_read_tokens,
                cache_write_tokens=u.cache_write_tokens,
                input_audio_tokens=u.input_audio_tokens,
                output_audio_tokens=u.output_audio_tokens,
                cache_audio_read_tokens=u.cache_audio_read_tokens,
            ),
            model_ref=model_ref,
            provider_id=provider_id,
        ).total_price
    except LookupError:
        logger.debug(f"No pricing data for model {model_key}")
        return None


def _merge_run_usage_into_bucket(bucket: ModelUsage, usage: RunUsage) -> None:
    bucket.input_tokens += usage.input_tokens or 0
    bucket.output_tokens += usage.output_tokens or 0
    bucket.cache_read_tokens += usage.cache_read_tokens or 0
    bucket.cache_write_tokens += usage.cache_write_tokens or 0
    bucket.input_audio_tokens += usage.input_audio_tokens or 0
    bucket.output_audio_tokens += usage.output_audio_tokens or 0
    bucket.cache_audio_read_tokens += usage.cache_audio_read_tokens or 0
    bucket.requests += usage.requests


class UsageTracker(BaseModel):
    models: dict[str, ModelUsage] = {}
    categories: dict[str, ModelUsage] = {}
    category_by_model: dict[str, dict[str, ModelUsage]] = {}

    def record(self, model: str, category: str, usage: RunUsage) -> None:
        for bucket in (
            self.models.setdefault(model, ModelUsage()),
            self.categories.setdefault(category, ModelUsage()),
        ):
            _merge_run_usage_into_bucket(bucket, usage)
        cm = self.category_by_model.setdefault(category, {})
        m_bucket = cm.setdefault(model, ModelUsage())
        _merge_run_usage_into_bucket(m_bucket, usage)

    @property
    def total_input(self) -> int:
        return sum(m.input_tokens for m in self.models.values())

    @property
    def total_output(self) -> int:
        return sum(m.output_tokens for m in self.models.values())

    def estimated_cost(self) -> dict[str, Decimal]:
        """Return estimated USD cost per model and total. Keys: model names + 'total'."""
        costs: dict[str, Decimal] = {}
        total = Decimal(0)
        for model_key, u in self.models.items():
            p = _price_for_usage(model_key, u)
            if p is not None:
                costs[model_key] = p
                total += p
        costs["total"] = total
        return costs

    def estimated_category_cost(self) -> dict[str, Decimal]:
        """Return estimated USD cost per usage category (tokens attributed per model)."""
        costs: dict[str, Decimal] = {}
        for category, by_model in self.category_by_model.items():
            cat_total = Decimal(0)
            for model_key, u in by_model.items():
                p = _price_for_usage(model_key, u)
                if p is not None:
                    cat_total += p
            costs[category] = cat_total
        return costs


class BudgetGauge(BaseModel):
    key: Literal["input", "output", "cost"]
    label: str
    current_value: str
    current_amount: float | None = None
    limit_value: str
    remaining_value: str | None = None
    fill_pct: float
    reached: bool
    unavailable_reason: str | None = None


class SessionBudgetExceededError(RuntimeError):
    def __init__(self, message: str, *, gauges: list[BudgetGauge]) -> None:
        super().__init__(message)
        self.gauges = gauges


def _format_token_count(value: int) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M tokens"
    if value >= 1_000:
        return f"{value / 1_000:.1f}k tokens"
    return f"{value} tokens"


def _format_usd(value: Decimal) -> str:
    return f"${value:.4f}"


def usage_budget_gauges(
    tracker: UsageTracker,
    *,
    input_tokens_limit: int | None = None,
    output_tokens_limit: int | None = None,
    total_cost_limit: Decimal | None = None,
) -> list[BudgetGauge]:
    gauges: list[BudgetGauge] = []

    if input_tokens_limit is not None:
        current = tracker.total_input
        remaining = max(0, input_tokens_limit - current)
        fill_pct = min(100.0, (100.0 * current / input_tokens_limit)) if input_tokens_limit > 0 else 0.0
        gauges.append(
            BudgetGauge(
                key="input",
                label="Input",
                current_value=_format_token_count(current),
                current_amount=float(current),
                limit_value=_format_token_count(input_tokens_limit),
                remaining_value=_format_token_count(remaining),
                fill_pct=round(fill_pct, 1),
                reached=current >= input_tokens_limit,
            )
        )

    if output_tokens_limit is not None:
        current = tracker.total_output
        remaining = max(0, output_tokens_limit - current)
        fill_pct = min(100.0, (100.0 * current / output_tokens_limit)) if output_tokens_limit > 0 else 0.0
        gauges.append(
            BudgetGauge(
                key="output",
                label="Output",
                current_value=_format_token_count(current),
                current_amount=float(current),
                limit_value=_format_token_count(output_tokens_limit),
                remaining_value=_format_token_count(remaining),
                fill_pct=round(fill_pct, 1),
                reached=current >= output_tokens_limit,
            )
        )

    if total_cost_limit is not None:
        total_cost = tracker.estimated_cost().get("total", Decimal(0))
        remaining = max(Decimal(0), total_cost_limit - total_cost)
        fill_pct = min(100.0, float(Decimal(100) * total_cost / total_cost_limit)) if total_cost_limit > 0 else 0.0
        gauges.append(
            BudgetGauge(
                key="cost",
                label="Cost",
                current_value=_format_usd(total_cost),
                current_amount=float(total_cost),
                limit_value=_format_usd(total_cost_limit),
                remaining_value=_format_usd(remaining),
                fill_pct=round(fill_pct, 1),
                reached=total_cost >= total_cost_limit,
            )
        )

    return gauges


def usage_budget_exceeded_error(
    tracker: UsageTracker,
    *,
    input_tokens_limit: int | None = None,
    output_tokens_limit: int | None = None,
    total_cost_limit: Decimal | None = None,
) -> SessionBudgetExceededError | None:
    gauges = usage_budget_gauges(
        tracker,
        input_tokens_limit=input_tokens_limit,
        output_tokens_limit=output_tokens_limit,
        total_cost_limit=total_cost_limit,
    )
    offenders = [gauge for gauge in gauges if gauge.reached]
    if not offenders:
        return None
    parts: list[str] = []
    for gauge in offenders:
        if gauge.unavailable_reason:
            parts.append(f"{gauge.label.lower()}: {gauge.unavailable_reason}")
        else:
            parts.append(f"{gauge.label.lower()} {gauge.current_value} / {gauge.limit_value}")
    return SessionBudgetExceededError(
        "Session budget reached: " + "; ".join(parts),
        gauges=gauges,
    )


LlmSource = Literal["agent", "sentinel"]
LlmRequestPhase = Literal["processing_prompt", "thinking", "generating"]

_llm_request_sink: ContextVar[LlmRequestObserver | None] = ContextVar(
    "llm_request_sink",
    default=None,
)
_current_llm_request_state: ContextVar[LlmRequestState | None] = ContextVar(
    "current_llm_request_state",
    default=None,
)


class LlmRequestState(BaseModel):
    request_id: str
    source: LlmSource
    model_name: str | None = None
    started_at: datetime
    phase: LlmRequestPhase = "processing_prompt"
    first_thinking_at: datetime | None = None
    last_thinking_at: datetime | None = None
    first_text_at: datetime | None = None


class LlmRequestObserver(Protocol):
    async def on_request_started(self, state: LlmRequestState) -> None: ...

    async def on_request_completed(self, record: LlmRequestRecord) -> None: ...


@contextmanager
def llm_request_sink_scope(sink: LlmRequestObserver | None) -> Any:
    token = _llm_request_sink.set(sink)
    try:
        yield
    finally:
        _llm_request_sink.reset(token)


def note_llm_request_thinking(ts: datetime | None = None) -> LlmRequestState | None:
    state = _current_llm_request_state.get()
    if state is None:
        return None
    when = ts or datetime.now(tz=UTC)
    if state.first_thinking_at is None:
        state.first_thinking_at = when
    state.last_thinking_at = when
    state.phase = "thinking"
    return state


def note_llm_request_text(ts: datetime | None = None) -> LlmRequestState | None:
    state = _current_llm_request_state.get()
    if state is None:
        return None
    when = ts or datetime.now(tz=UTC)
    if state.first_text_at is None:
        state.first_text_at = when
    state.phase = "generating"
    return state


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
    request_id: str | None = None
    source: LlmSource
    model_name: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    started_at: datetime | None = None
    first_thinking_at: datetime | None = None
    last_thinking_at: datetime | None = None
    first_text_at: datetime | None = None
    completed_at: datetime | None = None
    reasoning_tokens: int | None = None
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
    ttft_ms: int | None
    total_duration_ms: int | None
    reasoning_duration_ms: int | None
    reasoning_tokens: int | None
    breakdown_pct: _BreakdownPct


def _duration_ms(start: datetime | None, end: datetime | None) -> int | None:
    if start is None or end is None:
        return None
    return max(0, int((end - start).total_seconds() * 1000))


def _normalize_reasoning_tokens(details: dict[str, int]) -> int | None:
    exact = details.get("reasoning_tokens")
    if isinstance(exact, int):
        return exact
    for key in sorted(details):
        value = details[key]
        if not isinstance(value, int):
            continue
        normalized = key.lower().replace(".", "_")
        if "reasoning" in normalized and "token" in normalized:
            return value
    return None


def usage_last_request_row(rec: LlmRequestRecord | None) -> UsageLastRequestRow | None:
    """API fields from provider; breakdown_pct = tiktoken input-shape ratios as percentages (sum 100)."""
    if rec is None:
        return None
    inp, out = rec.input_tokens, rec.output_tokens
    reasoning_end = rec.first_text_at or rec.completed_at
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
        "ttft_ms": _duration_ms(rec.started_at, rec.first_text_at),
        "total_duration_ms": _duration_ms(rec.started_at, rec.completed_at),
        "reasoning_duration_ms": _duration_ms(rec.first_thinking_at, reasoning_end),
        "reasoning_tokens": rec.reasoning_tokens,
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
    return {k: float(v) for k, v in b.items() if isinstance(v, (int, float))}


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
        assert_never(part, f"unexpected response part of type {type(part)}")


def input_shape_ratios_from_messages(
    messages: list[ModelMessage],
    *,
    model_name: str | None,
) -> InputShapeRatios | None:
    buckets = {k: "" for k in ("system", "user", "assistant", "tool_calls", "tool_returns", "other")}
    for msg in messages:
        if isinstance(msg, ModelRequest):
            for p in msg.parts:
                _accumulate_request_part(p, buckets)
            if not buckets["system"] and msg.instructions:
                buckets["system"] += msg.instructions + "\n"
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

    async def before_model_request(
        self,
        ctx: RunContext[AgentDepsT],
        request_context: ModelRequestContext,
    ) -> ModelRequestContext:
        sink = _llm_request_sink.get()
        api_model_name = request_context.model.model_name
        carapace_id = getattr(ctx.deps, "agent_model_id", None)
        stored_model_name = carapace_id if isinstance(carapace_id, str) and carapace_id else api_model_name
        state = LlmRequestState(
            request_id=secrets.token_hex(8),
            source=self.source,
            model_name=stored_model_name,
            started_at=datetime.now(tz=UTC),
        )
        _current_llm_request_state.set(state)
        if sink is not None:
            await sink.on_request_started(state.model_copy(deep=True))
        return request_context

    async def after_model_request(
        self,
        ctx: RunContext[AgentDepsT],
        request_context: ModelRequestContext,
        response: ModelResponse,
    ) -> ModelResponse:
        sink = _llm_request_sink.get()
        state = _current_llm_request_state.get()
        usage = response.usage
        details = {k: int(v) for k, v in (usage.details or {}).items() if isinstance(v, int)}
        api_model_name = response.model_name or request_context.model.model_name
        shape = input_shape_ratios_from_messages(
            request_context.messages,
            model_name=api_model_name,
        )
        carapace_id = getattr(ctx.deps, "agent_model_id", None)
        stored_model_name = carapace_id if isinstance(carapace_id, str) and carapace_id else api_model_name
        completed_at = datetime.now(tz=UTC)
        if state is None:
            state = LlmRequestState(
                request_id=secrets.token_hex(8),
                source=self.source,
                model_name=stored_model_name,
                started_at=completed_at,
            )
        record = LlmRequestRecord(
            ts=completed_at,
            request_id=state.request_id,
            source=self.source,
            model_name=state.model_name or stored_model_name,
            input_tokens=usage.input_tokens or 0,
            output_tokens=usage.output_tokens or 0,
            started_at=state.started_at,
            first_thinking_at=state.first_thinking_at,
            last_thinking_at=state.last_thinking_at,
            first_text_at=state.first_text_at,
            completed_at=completed_at,
            reasoning_tokens=_normalize_reasoning_tokens(details),
            usage_details=details,
            input_shape=shape,
        )
        _current_llm_request_state.set(None)
        if sink is not None:
            await sink.on_request_completed(record)
        return response
