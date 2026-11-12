from __future__ import annotations

import asyncio
import json
import secrets
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, Protocol, TypedDict, assert_never

import tiktoken
from genai_prices import Usage as PriceUsage
from genai_prices import calc_price
from loguru import logger
from pydantic import BaseModel, Field
from pydantic_ai.capabilities.abstract import AbstractCapability, WrapModelRequestHandler
from pydantic_ai.messages import (
    CompactionPart,
    FilePart,
    InstructionPart,
    ModelMessage,
    ModelRequest,
    ModelRequestPart,
    ModelResponse,
    ModelResponsePart,
    NativeToolCallPart,
    NativeToolReturnPart,
    RetryPromptPart,
    SpeechPart,
    SystemPromptPart,
    TextPart,
    ThinkingPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
    post_compaction_window,
)
from pydantic_ai.models import ModelRequestContext
from pydantic_ai.tools import AgentDepsT, RunContext, ToolDefinition
from pydantic_ai.usage import RequestUsage, RunUsage, UsageLimits

from .models.config import is_subscription_model
from .models.session import SessionBudget


class ModelUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    input_audio_tokens: int = 0
    output_audio_tokens: int = 0
    cache_audio_read_tokens: int = 0
    requests: int = 0
    cost_usd: Decimal = Decimal(0)


def price_for_usage(model_key: str, u: ModelUsage) -> Decimal | None:
    provider_cost = u.cost_usd if u.cost_usd else None
    provider_id, _, model_ref = model_key.partition(":")
    if not model_ref:
        model_ref, provider_id = provider_id, None
    try:
        token_cost = calc_price(
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
        return provider_cost
    return max(provider_cost, token_cost) if provider_cost is not None else token_cost


@dataclass(frozen=True)
class CostSplit:
    """USD cost of some usage, split by what is actually billed."""

    # Billed per token: provider-reported cost or list price. Subscription usage adds nothing.
    actual: Decimal = Decimal(0)
    # List price of everything, subscription usage included: what it would have cost on the API.
    equivalent: Decimal = Decimal(0)

    def __add__(self, other: CostSplit) -> CostSplit:
        return CostSplit(actual=self.actual + other.actual, equivalent=self.equivalent + other.equivalent)


def cost_split(model_key: str, equivalent: Decimal) -> CostSplit:
    """Split a list price: a subscription model bills nothing per token, any other model its list price."""
    return CostSplit(actual=Decimal(0) if is_subscription_model(model_key) else equivalent, equivalent=equivalent)


def usage_cost(model_key: str, usage: ModelUsage) -> CostSplit:
    return cost_split(model_key, price_for_usage(model_key, usage) or Decimal(0))


def _merge_run_usage_into_bucket(bucket: ModelUsage, usage: RunUsage | RequestUsage) -> None:
    bucket.input_tokens += usage.input_tokens or 0
    bucket.output_tokens += usage.output_tokens or 0
    bucket.cache_read_tokens += usage.cache_read_tokens or 0
    bucket.cache_write_tokens += usage.cache_write_tokens or 0
    bucket.input_audio_tokens += usage.input_audio_tokens or 0
    bucket.output_audio_tokens += usage.output_audio_tokens or 0
    bucket.cache_audio_read_tokens += usage.cache_audio_read_tokens or 0
    bucket.requests += usage.requests


def _merge_cost_into_bucket(bucket: ModelUsage, cost_usd: Decimal | None) -> None:
    if cost_usd is not None:
        bucket.cost_usd += cost_usd


def _coerce_cost_usd(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int | float | str):
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None
    return None


def provider_cost_usd_from_messages(messages: list[ModelMessage]) -> Decimal | None:
    total = Decimal(0)
    found = False
    for message in messages:
        if not isinstance(message, ModelResponse) or message.provider_details is None:
            continue
        cost = _coerce_cost_usd(message.provider_details.get("cost"))
        if cost is None:
            continue
        total += cost
        found = True
    return total if found else None


def split_provider_compaction_usage(usage: RunUsage) -> tuple[RunUsage, RunUsage | None]:
    """*usage* split into the turn's own share and what provider-side compaction spent inside it.

    Anthropic reports compaction iterations separately, and pydantic-ai adds them back into the
    request totals (keeping them in ``details`` as ``compaction_*``); carapace counts them under the
    ``compaction`` category like its own summaries. Providers that report nothing stay whole.
    """
    details = usage.details
    if not details.get("compaction_iterations"):
        return usage, None
    cache_write = details.get("compaction_cache_creation_input_tokens", 0)
    cache_read = details.get("compaction_cache_read_input_tokens", 0)
    compaction = RunUsage(
        input_tokens=details.get("compaction_input_tokens", 0) + cache_write + cache_read,
        cache_write_tokens=cache_write,
        cache_read_tokens=cache_read,
        output_tokens=details.get("compaction_output_tokens", 0),
    )
    own = replace(
        usage,
        input_tokens=usage.input_tokens - compaction.input_tokens,
        cache_write_tokens=usage.cache_write_tokens - cache_write,
        cache_read_tokens=usage.cache_read_tokens - cache_read,
        output_tokens=usage.output_tokens - compaction.output_tokens,
        details={k: v for k, v in details.items() if not k.startswith("compaction_")},
    )
    return own, compaction


@dataclass
class ProviderCostCapability(AbstractCapability[Any]):
    """Sums the provider-reported cost of every response of one run.

    Counting responses as they arrive, not from the run's messages afterwards: compaction inside the
    run may have folded some of them away by then.
    """

    total_usd: Decimal | None = None

    async def after_model_request(
        self, ctx: RunContext[Any], *, request_context: ModelRequestContext, response: ModelResponse
    ) -> ModelResponse:
        if (cost := provider_cost_usd_from_messages([response])) is not None:
            self.total_usd = (self.total_usd or Decimal(0)) + cost
        return response


class RequestCost(BaseModel):
    """What a single model request cost, in the terms of CostSplit."""

    # Both None when the model has no known pricing and the provider reported no cost.
    cost_usd: Decimal | None
    equivalent_cost_usd: Decimal | None
    # What the provider itself reported, if it did (OpenRouter, for example).
    provider_cost_usd: Decimal | None


def request_cost(model_id: str, response: ModelResponse) -> RequestCost:
    """Price one response; *model_id* is the carapace model id (provider:model), not the API model name."""
    provider_cost = provider_cost_usd_from_messages([response])
    usage = ModelUsage()
    _merge_run_usage_into_bucket(usage, response.usage)
    _merge_cost_into_bucket(usage, provider_cost)
    equivalent = price_for_usage(model_id, usage)
    return RequestCost(
        cost_usd=None if equivalent is None else cost_split(model_id, equivalent).actual,
        equivalent_cost_usd=equivalent,
        provider_cost_usd=provider_cost,
    )


class UsageTracker(BaseModel):
    models: dict[str, ModelUsage] = {}
    categories: dict[str, ModelUsage] = {}
    category_by_model: dict[str, dict[str, ModelUsage]] = {}
    tool_calls: int = 0

    def record(self, model: str, category: str, usage: RunUsage, *, cost_usd: Decimal | None = None) -> None:
        for bucket in (
            self.models.setdefault(model, ModelUsage()),
            self.categories.setdefault(category, ModelUsage()),
        ):
            _merge_run_usage_into_bucket(bucket, usage)
            _merge_cost_into_bucket(bucket, cost_usd)
        cm = self.category_by_model.setdefault(category, {})
        m_bucket = cm.setdefault(model, ModelUsage())
        _merge_run_usage_into_bucket(m_bucket, usage)
        _merge_cost_into_bucket(m_bucket, cost_usd)

    def record_tool_call(self) -> None:
        self.tool_calls += 1

    @property
    def total_input(self) -> int:
        return sum(m.input_tokens for m in self.models.values())

    @property
    def total_output(self) -> int:
        return sum(m.output_tokens for m in self.models.values())

    @property
    def has_subscription_usage(self) -> bool:
        return any(is_subscription_model(model_key) for model_key in self.models)

    def cost_by_model(self) -> dict[str, CostSplit]:
        return {model_key: usage_cost(model_key, u) for model_key, u in self.models.items()}

    def cost_by_category(self) -> dict[str, CostSplit]:
        """Cost per usage category, priced per model since a category can span several."""
        return {
            category: sum((usage_cost(model_key, u) for model_key, u in by_model.items()), CostSplit())
            for category, by_model in self.category_by_model.items()
        }

    def total_cost(self) -> CostSplit:
        return sum(self.cost_by_model().values(), CostSplit())


BudgetMetric = Literal["input", "output", "cost", "equivalent_cost", "tool_calls", "autonomy"]


class BudgetGauge(BaseModel):
    key: BudgetMetric
    label: str
    current_value: str
    current_amount: float | None = None
    # None for a gauge shown without a limit (the equivalent cost of subscription usage).
    limit_value: str | None
    remaining_value: str | None = None
    fill_pct: float
    reached: bool
    unavailable_reason: str | None = None


class SessionBudgetExceededError(RuntimeError):
    """Raised when at least one of *gauges* has reached its limit."""

    def __init__(self, gauges: list[BudgetGauge]) -> None:
        reached = [gauge for gauge in gauges if gauge.reached]
        if not reached:
            raise ValueError("SessionBudgetExceededError needs at least one reached budget gauge")
        super().__init__(_budget_exceeded_message(reached))
        self.gauges = gauges


def _budget_exceeded_message(reached: list[BudgetGauge]) -> str:
    usage = "; ".join(
        f"{gauge.label.lower()}: {gauge.unavailable_reason}"
        if gauge.unavailable_reason
        else f"{gauge.label.lower()} {gauge.current_value} / {gauge.limit_value}"
        for gauge in reached
    )
    # Every metric key is itself an accepted ``/budget`` argument.
    commands = ", ".join(f"/budget {gauge.key} N" for gauge in reached)
    return f"Session budget reached: {usage}. Raise the limit to continue: {commands}"


def _format_token_count(value: int) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M tokens"
    if value >= 1_000:
        return f"{value / 1_000:.1f}k tokens"
    return f"{value} tokens"


def _format_usd(value: Decimal) -> str:
    return f"${value:.4f}"


def _format_tool_calls(value: int) -> str:
    suffix = "call" if value == 1 else "calls"
    return f"{value:,} tool {suffix}"


def usage_budget_gauges(tracker: UsageTracker, budget: SessionBudget) -> list[BudgetGauge]:
    """Gauges of the session totals: one per set limit, plus the equivalent cost of subscription usage."""
    gauges: list[BudgetGauge] = []
    input_tokens_limit = budget.input_tokens
    output_tokens_limit = budget.output_tokens
    cost_limit = budget.cost_usd
    equivalent_cost_limit = budget.equivalent_cost_usd
    tool_calls_limit = budget.tool_calls

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

    show_equivalent_cost = equivalent_cost_limit is not None or tracker.has_subscription_usage
    if cost_limit is not None or show_equivalent_cost:
        cost = tracker.total_cost()
        if cost_limit is not None:
            gauges.append(_cost_gauge("cost", "Cost", cost.actual, cost_limit))
        # Subscription usage has no actual cost, so its equivalent cost shows even without a limit.
        if show_equivalent_cost:
            gauges.append(_cost_gauge("equivalent_cost", "Equivalent cost", cost.equivalent, equivalent_cost_limit))

    if tool_calls_limit is not None:
        current = tracker.tool_calls
        remaining = max(0, tool_calls_limit - current)
        fill_pct = min(100.0, (100.0 * current / tool_calls_limit)) if tool_calls_limit > 0 else 0.0
        gauges.append(
            BudgetGauge(
                key="tool_calls",
                label="Tool Calls",
                current_value=_format_tool_calls(current),
                current_amount=float(current),
                limit_value=_format_tool_calls(tool_calls_limit),
                remaining_value=_format_tool_calls(remaining),
                fill_pct=round(fill_pct, 1),
                reached=current >= tool_calls_limit,
            )
        )

    return gauges


def _cost_gauge(key: BudgetMetric, label: str, current: Decimal, limit: Decimal | None) -> BudgetGauge:
    return BudgetGauge(
        key=key,
        label=label,
        current_value=_format_usd(current),
        current_amount=float(current),
        limit_value=None if limit is None else _format_usd(limit),
        remaining_value=None if limit is None else _format_usd(max(Decimal(0), limit - current)),
        fill_pct=0.0 if limit is None else round(min(100.0, float(Decimal(100) * current / limit)), 1),
        reached=limit is not None and current >= limit,
    )


def autonomy_budget_gauge(streak: int, limit: int) -> BudgetGauge:
    """Gauge for the autonomy limit. Display only: unlike the other budgets it never blocks an LLM call."""
    return BudgetGauge(
        key="autonomy",
        label="Autonomy",
        current_value=_format_tool_calls(streak),
        current_amount=float(streak),
        limit_value=_format_tool_calls(limit),
        remaining_value=_format_tool_calls(max(0, limit - streak)),
        fill_pct=round(min(100.0, 100.0 * streak / limit), 1),
        reached=streak >= limit,
    )


def usage_budget_exceeded_error(tracker: UsageTracker, budget: SessionBudget) -> SessionBudgetExceededError | None:
    gauges = usage_budget_gauges(tracker, budget)
    return SessionBudgetExceededError(gauges) if any(gauge.reached for gauge in gauges) else None


def agent_request_limit(autonomy_limit: int | None) -> int | None:
    """Model requests one agent run may make; ``None`` (no autonomy limit) turns loop protection off."""
    # Stopgap for model loops the per-tool-call autonomy streak doesn't catch, e.g. calls that fail
    # argument validation and never reach a tool. It replaces pydantic-ai's implicit limit of 50.
    return None if autonomy_limit is None else 3 * autonomy_limit


def usage_limits_for_remaining_budget(
    tracker: UsageTracker,
    *,
    output_tokens_limit: int | None,
    request_limit: int | None,
) -> UsageLimits:
    """Translate the remaining session output budget into PydanticAI usage limits.

    Always explicit: without limits pydantic-ai would apply its own default request limit.
    """
    remaining_output = None if output_tokens_limit is None else max(0, output_tokens_limit - tracker.total_output)
    return UsageLimits(output_tokens_limit=remaining_output, request_limit=request_limit)


LlmSource = Literal["agent", "sentinel", "titler", "compaction", "memory"]
LlmRequestPhase = Literal["processing_prompt", "thinking", "generating"]
LlmRequestOutcome = Literal["completed", "interrupted"]
LlmContextStatus = Literal["running", "completed", "failed", "interrupted"]
CompactionTarget = Literal["agent", "sentinel"]

_llm_request_sink: ContextVar[LlmRequestObserver | None] = ContextVar(
    "llm_request_sink",
    default=None,
)
_current_llm_request_state: ContextVar[LlmRequestState | None] = ContextVar(
    "current_llm_request_state",
    default=None,
)
_current_llm_context: ContextVar[LlmContext | None] = ContextVar("current_llm_context", default=None)


class LlmRequestState(BaseModel):
    request_id: str
    source: LlmSource
    model_name: str | None = None
    started_at: datetime
    phase: LlmRequestPhase = "processing_prompt"
    first_thinking_at: datetime | None = None
    last_thinking_at: datetime | None = None
    first_text_at: datetime | None = None


class LlmContext(BaseModel):
    """One request to a model as it was sent, plus its outcome (see GLOSSARY.md: LLM Context)."""

    request_id: str
    role: LlmSource
    # Only for the compaction role: whose model history or shadow conversation was compacted.
    compaction_target: CompactionTarget | None = None
    # The carapace model id (provider:model) the request was priced with, not the API model name.
    model_name: str
    status: LlmContextStatus
    started_at: datetime
    completed_at: datetime | None = None
    instructions: list[InstructionPart]
    messages: list[ModelMessage]
    tool_definitions: list[ToolDefinition]
    response: ModelResponse | None = None
    error: str | None = None
    # Priced when the response arrives, like the usage tracker prices at record time.
    cost: RequestCost | None = None


class LlmRequestObserver(Protocol):
    async def on_request_started(self, state: LlmRequestState) -> None: ...

    async def on_request_completed(self, record: LlmRequestRecord) -> None: ...

    async def on_context(self, context: LlmContext) -> None: ...

    async def on_context_failed(self, role: LlmSource, error: str) -> None: ...


@contextmanager
def llm_request_sink_scope(sink: LlmRequestObserver | None) -> Any:
    token = _llm_request_sink.set(sink)
    try:
        yield
    finally:
        _llm_request_sink.reset(token)


async def fail_llm_context(role: LlmSource, error: str) -> None:
    """Mark *role*'s latest LLM context failed if the failure cut it short.

    For failures the request itself only sees as a cancellation: a timeout around the run, or a
    streamed request, whose provider errors surface in the stream consumer while pydantic-ai cancels
    the request task.
    """
    sink = _llm_request_sink.get()
    if sink is not None:
        await sink.on_context_failed(role, error)


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
    outcome: LlmRequestOutcome = "completed"
    input_tokens: int = 0
    output_tokens: int = 0
    # None on records written before these counts were kept: unknown, not zero.
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
    # None on interrupted requests and on records written before costs were kept.
    cost: RequestCost | None = None
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


def interrupted_request_record(state: LlmRequestState, *, ts: datetime | None = None) -> LlmRequestRecord:
    when = ts or datetime.now(tz=UTC)
    return LlmRequestRecord(
        ts=when,
        request_id=state.request_id,
        source=state.source,
        model_name=state.model_name,
        outcome="interrupted",
        started_at=state.started_at,
        first_thinking_at=state.first_thinking_at,
        last_thinking_at=state.last_thinking_at,
        first_text_at=state.first_text_at,
    )


def last_record_for_source(
    log: LlmRequestLog,
    source: LlmSource,
    *,
    include_interrupted: bool = False,
) -> LlmRequestRecord | None:
    for rec in reversed(log.records):
        if rec.source != source:
            continue
        if include_interrupted:
            return rec
        if rec.outcome == "completed":
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


class UsageContextRow(UsageLastRequestRow):
    """A last-request row with the context window it was measured against."""

    context_cap_tokens: int
    context_used_pct: float


class ModelCost(BaseModel):
    """A model's cost as one number: subscription models show their list price, marked as such."""

    cost: Decimal
    subscription: bool


class SessionUsageDetails(BaseModel):
    """The session's usage breakdown, as ``/usage`` and ``GET /api/sessions/{id}/usage`` show it."""

    models: dict[str, ModelUsage]
    categories: dict[str, ModelUsage]
    total_input: int
    total_output: int
    total_tool_calls: int
    model_costs: dict[str, ModelCost]
    category_costs: dict[str, CostSplit]
    total_cost: CostSplit
    budget_gauges: list[BudgetGauge]
    last_llm_agent: UsageContextRow | None
    last_llm_sentinel: UsageContextRow | None


def _duration_ms(start: datetime | None, end: datetime | None) -> int | None:
    if start is None or end is None:
        return None
    return max(0, int((end - start).total_seconds() * 1000))


class TurnGenerationStats(TypedDict):
    input_tokens: int
    output_tokens: int
    ttft_ms: int | None
    generation_ms: int | None


def aggregate_turn_generation(records: list[LlmRequestRecord]) -> TurnGenerationStats:
    """Turn-level generation stats over the turn's completed agent requests (all provider-reported).

    Token totals are summed across requests (the model bills each round's input + output). ``ttft_ms``
    is the turn's first request's prompt→first-token wait. ``generation_ms`` sums each request's decode
    window (first token → completion); the gaps between requests are tool execution and are excluded,
    so a tok/s derived from it reflects decode speed, not how long tools ran.
    """
    agent = [r for r in records if r.source == "agent" and r.outcome == "completed"]
    input_tokens = sum(r.input_tokens for r in agent)
    output_tokens = sum(r.output_tokens for r in agent)
    ttft_ms = _duration_ms(agent[0].started_at, agent[0].first_text_at) if agent else None
    generation_ms: int | None = None
    for rec in agent:
        decode = _duration_ms(rec.first_text_at, rec.completed_at)
        if decode is not None:
            generation_ms = (generation_ms or 0) + decode
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "ttft_ms": ttft_ms,
        "generation_ms": generation_ms,
    }


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
    elif isinstance(part, CompactionPart):
        if part.content:
            buckets["assistant"] += part.content + "\n"
    elif isinstance(part, ToolCallPart | NativeToolCallPart):
        buckets["tool_calls"] += f"{part.tool_name}\n{part.args_as_json_str()}\n"
    elif isinstance(part, NativeToolReturnPart):
        buckets["tool_returns"] += f"{part.tool_name}\n{_tool_return_blob(part.content)}\n"
    elif isinstance(part, FilePart):
        buckets["other"] += _file_part_blob(part) + "\n"
    elif isinstance(part, SpeechPart):
        buckets["assistant"] += (part.transcript or "") + "\n"
    else:
        assert_never(part)


def _message_text_buckets(messages: list[ModelMessage]) -> dict[str, str]:
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
    return buckets


def count_text_tokens(text: str, *, model_name: str | None = None) -> int:
    """Token estimate for a raw string, using the model's tiktoken encoding."""
    return _count_text(_encoding_for_model(model_name), text)


def count_message_tokens(messages: list[ModelMessage], *, model_name: str | None = None) -> int:
    """Token estimate for a slice of pydantic-ai history (approximate; tiktoken-based)."""
    enc = _encoding_for_model(model_name)
    return sum(_count_text(enc, v) for v in _message_text_buckets(messages).values())


def input_shape_ratios_from_messages(
    messages: list[ModelMessage],
    *,
    model_name: str | None,
) -> InputShapeRatios | None:
    buckets = _message_text_buckets(messages)
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


def _request_llm_context(
    request_context: ModelRequestContext,
    *,
    state: LlmRequestState,
    model_id: str,
    compaction_target: CompactionTarget | None,
) -> LlmContext:
    params = request_context.model_request_parameters
    return LlmContext(
        request_id=state.request_id,
        role=state.source,
        compaction_target=compaction_target,
        model_name=model_id,
        status="running",
        started_at=state.started_at,
        instructions=list(params.instruction_parts or []),
        # What the provider receives: the history before its latest compaction stays behind.
        messages=post_compaction_window(request_context.messages),
        tool_definitions=[*params.function_tools, *params.output_tools],
    )


@dataclass
class LlmRequestLogCapability(AbstractCapability[AgentDepsT]):
    """Report every model request to the session sink: activity, usage record and LLM context."""

    source: LlmSource
    # The carapace model id (provider:model): pricing and subscription checks key on it, and the
    # provider's API model name is often a short or dated alias of it.
    model_id: str
    compaction_target: CompactionTarget | None = None

    def __post_init__(self) -> None:
        if (self.source == "compaction") != (self.compaction_target is not None):
            raise ValueError("compaction_target is required for the compaction role and only for it")

    async def wrap_model_request(
        self,
        ctx: RunContext[AgentDepsT],
        *,
        request_context: ModelRequestContext,
        handler: WrapModelRequestHandler,
    ) -> ModelResponse:
        try:
            return await handler(request_context)
        except asyncio.CancelledError:
            await self._finish_context("interrupted", error=None)
            raise
        except Exception as exc:
            await self._finish_context("failed", error=f"{type(exc).__name__}: {exc}")
            raise

    async def _finish_context(self, status: LlmContextStatus, *, error: str | None) -> None:
        context = _current_llm_context.get()
        if context is None or context.status != "running":
            return
        context = context.model_copy(update={"status": status, "error": error, "completed_at": datetime.now(tz=UTC)})
        _current_llm_context.set(context)
        if (sink := _llm_request_sink.get()) is not None:
            await sink.on_context(context)

    async def before_model_request(
        self,
        ctx: RunContext[AgentDepsT],
        request_context: ModelRequestContext,
    ) -> ModelRequestContext:
        sink = _llm_request_sink.get()
        state = LlmRequestState(
            request_id=secrets.token_hex(8),
            source=self.source,
            model_name=self.model_id,
            started_at=datetime.now(tz=UTC),
        )
        _current_llm_request_state.set(state)
        context = _request_llm_context(
            request_context, state=state, model_id=self.model_id, compaction_target=self.compaction_target
        )
        _current_llm_context.set(context)
        if sink is not None:
            await sink.on_request_started(state.model_copy(deep=True))
            await sink.on_context(context)
        return request_context

    async def after_model_request(
        self,
        ctx: RunContext[AgentDepsT],
        *,
        request_context: ModelRequestContext,
        response: ModelResponse,
    ) -> ModelResponse:
        sink = _llm_request_sink.get()
        state = _current_llm_request_state.get()
        usage = response.usage
        details = {k: v for k, v in (usage.details or {}).items() if isinstance(v, int)}
        api_model_name = response.model_name or request_context.model.model_name
        # The provider receives nothing before its latest compaction, though the history keeps it.
        shape = input_shape_ratios_from_messages(
            post_compaction_window(request_context.messages),
            model_name=api_model_name,
        )
        completed_at = datetime.now(tz=UTC)
        if state is None:
            state = LlmRequestState(
                request_id=secrets.token_hex(8),
                source=self.source,
                model_name=self.model_id,
                started_at=completed_at,
            )
        cost = request_cost(self.model_id, response)
        record = LlmRequestRecord(
            ts=completed_at,
            request_id=state.request_id,
            source=self.source,
            model_name=self.model_id,
            input_tokens=usage.input_tokens or 0,
            output_tokens=usage.output_tokens or 0,
            cache_read_tokens=usage.cache_read_tokens,
            cache_write_tokens=usage.cache_write_tokens,
            cost=cost,
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
        if (context := _current_llm_context.get()) is not None:
            context = context.model_copy(
                update={
                    "status": "completed",
                    "response": response,
                    "completed_at": completed_at,
                    "cost": cost,
                }
            )
            _current_llm_context.set(context)
            if sink is not None:
                await sink.on_context(context)
        return response
