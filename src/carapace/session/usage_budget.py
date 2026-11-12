"""Session usage, budget, and LLM activity helpers."""

from __future__ import annotations

import contextlib
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.usage import UsageLimits

from ..models.config import Config, is_subscription_model
from ..models.session import SessionBudget
from ..usage import (
    BudgetGauge,
    BudgetMetric,
    LlmContext,
    LlmRequestRecord,
    LlmRequestState,
    LlmSource,
    ModelCost,
    SessionBudgetExceededError,
    SessionUsageDetails,
    UsageContextRow,
    agent_request_limit,
    autonomy_budget_gauge,
    gauge_breakdown_pct_dict,
    last_record_for_source,
    llm_request_sink_scope,
    usage_budget_exceeded_error,
    usage_budget_gauges,
    usage_last_request_row,
    usage_limits_for_remaining_budget,
)
from ..ws_models import TurnUsage, TurnUsageBreakdownPct
from .manager import SessionManager
from .types import ActiveSession

_DEFAULT_CONTEXT_CAP_TOKENS = 200_000

BUDGET_METRIC_FIELDS: dict[BudgetMetric, str] = {
    "input": "input_tokens",
    "output": "output_tokens",
    "cost": "cost_usd",
    "equivalent_cost": "equivalent_cost_usd",
    "tool_calls": "tool_calls",
    "autonomy": "autonomous_tool_calls",
}

_BUDGET_METRIC_NAMES: dict[BudgetMetric, str] = {
    "input": "input token budget",
    "output": "output token budget",
    "cost": "cost budget",
    "equivalent_cost": "equivalent cost budget",
    "tool_calls": "tool call budget",
    "autonomy": "autonomy limit",
}

_USD_METRICS: frozenset[BudgetMetric] = frozenset({"cost", "equivalent_cost"})


def parse_budget_limit(metric: BudgetMetric, raw: str) -> int | Decimal:
    """Parse a limit as typed in ``/budget`` (``100k``, ``2M``, ``1,000``, ``2.50``); 0 means no limit."""
    cleaned = raw.replace(",", "").replace("_", "")
    if metric not in _USD_METRICS:
        lowered = cleaned.lower()
        multiplier = 1
        if lowered.endswith("k"):
            multiplier = 1_000
            lowered = lowered[:-1]
        elif lowered.endswith("m"):
            multiplier = 1_000_000
            lowered = lowered[:-1]

        budget_type = "token budget" if metric in ("input", "output") else _BUDGET_METRIC_NAMES[metric]
        if not lowered:
            raise ValueError(f"Invalid {budget_type}: {raw}")

        try:
            scaled = Decimal(lowered) * multiplier
        except InvalidOperation as exc:
            raise ValueError(f"Invalid {budget_type}: {raw}") from exc

        if scaled != scaled.to_integral_value():
            raise ValueError(f"Invalid {budget_type}: {raw}")

        value = int(scaled)
        if value < 0:
            raise ValueError("Budget value must be >= 0")
        return value
    try:
        value = Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError(f"Invalid {_BUDGET_METRIC_NAMES[metric]}: {raw}") from exc
    if value < 0:
        raise ValueError("Budget value must be >= 0")
    return value


def _budget_limit_message(metric: BudgetMetric, budget: SessionBudget) -> str:
    name = _BUDGET_METRIC_NAMES[metric]
    value = getattr(budget, BUDGET_METRIC_FIELDS[metric])
    if value is None:
        return f"Cleared {name}."
    match metric:
        case "cost" | "equivalent_cost":
            amount = f"${value:.4f}"
        case "tool_calls":
            amount = f"{value:,} tool {'call' if value == 1 else 'calls'}"
        case "autonomy":
            amount = f"{value:,} tool {'call' if value == 1 else 'calls'} without you"
        case _:
            amount = f"{value:,} tokens"
    return f"Set {name} to {amount}."


class SessionUsageBudgetMixin:
    _active: dict[str, ActiveSession]
    _config: Config
    _session_mgr: SessionManager

    if TYPE_CHECKING:

        async def _broadcast(self, active: ActiveSession, method: str, *args: Any, **kwargs: Any) -> None: ...
        def _max_input_tokens_for_model_id(self, model_id: str) -> int | None: ...

    def _usage_last_llm_payload_row(self, active: ActiveSession, source: LlmSource) -> UsageContextRow | None:
        """``usage_last_request_row`` plus ``context_cap_tokens`` and ``context_used_pct`` for the UI."""
        rec = last_record_for_source(active.llm_request_log, source)
        row = usage_last_request_row(rec)
        if row is None:
            return None
        mid = self.agent_model_id_for_gauge(active) if source == "agent" else self.sentinel_model_id(active)
        cap = self._max_input_tokens_for_model_id(mid)
        if cap is None:
            cap = _DEFAULT_CONTEXT_CAP_TOKENS
        cs = row["context_size"]
        pct = min(100.0, (100.0 * cs / cap)) if cap > 0 else 0.0
        return UsageContextRow(**row, context_cap_tokens=cap, context_used_pct=round(pct, 1))

    def agent_model_id_for_gauge(self, active: ActiveSession) -> str:
        """Canonical carapace model id (``provider:name``) for UI gauge / config lookup.

        Do not use the provider's raw ``model_name`` from the LLM log — it is often a short
        id without the ``provider:`` prefix, so it would not match ``available_models`` entries.
        """
        return active.agent_model_name or self._config.agent.model

    def agent_context_cap_for_gauge(self, active: ActiveSession) -> int:
        model_id = self.agent_model_id_for_gauge(active)
        return self._max_input_tokens_for_model_id(model_id) or _DEFAULT_CONTEXT_CAP_TOKENS

    def sentinel_model_id(self, active: ActiveSession) -> str:
        return active.sentinel_model_name or self._config.agent.sentinel_model

    def sentinel_context_cap(self, active: ActiveSession) -> int:
        return self._max_input_tokens_for_model_id(self.sentinel_model_id(active)) or _DEFAULT_CONTEXT_CAP_TOKENS

    def _budget_gauges(self, active: ActiveSession) -> list[BudgetGauge]:
        """Gauges of the session totals, the budgets whose stop message lists the reached ones."""
        return usage_budget_gauges(active.usage_tracker, active.state.budget)

    def _display_budget_gauges(self, active: ActiveSession) -> list[BudgetGauge]:
        """Every gauge the UI shows: the totals plus the autonomy limit, which stops through its own path."""
        gauges = self._budget_gauges(active)
        limit = active.state.budget.autonomous_tool_calls
        if limit is not None:
            gauges.append(autonomy_budget_gauge(active.autonomy.count, limit))
        return gauges

    def _budget_exceeded_error(self, active: ActiveSession) -> SessionBudgetExceededError | None:
        return usage_budget_exceeded_error(active.usage_tracker, active.state.budget)

    def _assert_llm_budget_available(self, active: ActiveSession) -> None:
        error = self._budget_exceeded_error(active)
        if error is not None:
            raise error

    def _remaining_usage_limits(self, active: ActiveSession) -> UsageLimits:
        budget = active.state.budget
        return usage_limits_for_remaining_budget(
            active.usage_tracker,
            output_tokens_limit=budget.output_tokens,
            request_limit=agent_request_limit(budget.autonomous_tool_calls),
        )

    def _agent_request_limit_message(self, active: ActiveSession, error: UsageLimitExceeded) -> str | None:
        """A readable stop message when *error* is the agent request stopgap, else ``None``."""
        limit = active.state.budget.autonomous_tool_calls
        # pydantic-ai reports which limit was hit only in the message text.
        if limit is None or "request_limit" not in str(error):
            return None
        return (
            f"The agent made {agent_request_limit(limit):,} model requests without finishing the turn "
            f"(three times the autonomy limit of {limit:,}). Raise the limit to continue: /budget autonomy N"
        )

    def _remaining_aux_usage_limits(self, active: ActiveSession) -> UsageLimits:
        return usage_limits_for_remaining_budget(
            active.usage_tracker,
            output_tokens_limit=active.state.budget.output_tokens,
            request_limit=10,
        )

    def _turn_usage_payload(self, active: ActiveSession) -> TurnUsage | None:
        rec_agent = last_record_for_source(active.llm_request_log, "agent")
        budget_gauges = self._display_budget_gauges(active)
        if rec_agent is None and not budget_gauges:
            return None
        row = usage_last_request_row(rec_agent) if rec_agent else None
        bd = gauge_breakdown_pct_dict(rec_agent)
        return TurnUsage(
            input_tokens=rec_agent.input_tokens if rec_agent else 0,
            output_tokens=rec_agent.output_tokens if rec_agent else 0,
            breakdown_pct=TurnUsageBreakdownPct.model_validate(bd) if bd else None,
            model=self.agent_model_id_for_gauge(active),
            context_cap_tokens=self.agent_context_cap_for_gauge(active),
            ttft_ms=row["ttft_ms"] if row else None,
            total_duration_ms=row["total_duration_ms"] if row else None,
            reasoning_duration_ms=row["reasoning_duration_ms"] if row else None,
            reasoning_tokens=row["reasoning_tokens"] if row else None,
            started_at=rec_agent.started_at if rec_agent else None,
            first_thinking_at=rec_agent.first_thinking_at if rec_agent else None,
            last_thinking_at=rec_agent.last_thinking_at if rec_agent else None,
            first_text_at=rec_agent.first_text_at if rec_agent else None,
            completed_at=rec_agent.completed_at if rec_agent else None,
            budget_gauges=budget_gauges,
        )

    async def _set_llm_request_state(self, active: ActiveSession, state: LlmRequestState) -> None:
        active.llm_request_state = state.model_copy(deep=True)
        self._session_mgr.save_llm_request_state(active.state.session_id, active.llm_request_state)
        await self._broadcast(active, "on_llm_activity", active.llm_request_state.model_copy(deep=True))

    async def _clear_llm_request_state(self, active: ActiveSession) -> None:
        if active.llm_request_state is None:
            self._session_mgr.clear_llm_request_state(active.state.session_id)
            return
        active.llm_request_state = None
        self._session_mgr.clear_llm_request_state(active.state.session_id)
        await self._broadcast(active, "on_llm_activity", None)

    async def _save_llm_context(self, active: ActiveSession, context: LlmContext) -> None:
        # ponytail: the whole context is rewritten on every status change; split messages out if writes get slow.
        self._session_mgr.save_llm_context(active.state.session_id, context)
        await self._broadcast(active, "on_llm_context", context.role, context.request_id, context.status)

    async def _maybe_promote_llm_request_state(self, active: ActiveSession, state: LlmRequestState | None) -> None:
        if state is None:
            return
        current = active.llm_request_state
        if current is not None and current.phase == state.phase and current.first_text_at == state.first_text_at:
            return
        await self._set_llm_request_state(active, state)

    def usage_details(self, active: ActiveSession) -> SessionUsageDetails:
        """The session's usage breakdown as ``/usage`` and the usage API show it.

        Reads only in-memory state and takes no session lock, so it answers while a turn runs.
        """
        tracker = active.usage_tracker
        return SessionUsageDetails(
            models=tracker.models,
            categories=tracker.categories,
            total_input=tracker.total_input,
            total_output=tracker.total_output,
            total_tool_calls=tracker.tool_calls,
            model_costs={
                model_key: ModelCost(cost=cost.equivalent, subscription=is_subscription_model(model_key))
                for model_key, cost in tracker.cost_by_model().items()
            },
            category_costs=tracker.cost_by_category(),
            total_cost=tracker.total_cost(),
            budget_gauges=self._display_budget_gauges(active),
            last_llm_agent=self._usage_last_llm_payload_row(active, "agent"),
            last_llm_sentinel=self._usage_last_llm_payload_row(active, "sentinel"),
        )

    def _budget_command_payload(self, active: ActiveSession, *, message: str | None = None) -> dict[str, Any]:
        gauges = self._display_budget_gauges(active)
        usage_hint = (
            "Set budgets with /budget input N, /budget output N, /budget cost N (billed per token), "
            "/budget equivalent_cost N (list price, subscription usage included), /budget tools N, "
            "or /budget autonomy N. Use 0 to clear a limit."
        )
        payload: dict[str, Any] = {
            "gauges": [g.model_dump(mode="json") for g in gauges],
            "usage_hint": usage_hint,
        }
        if message is not None:
            payload["message"] = message
        if not gauges and message is None:
            payload["message"] = "No session budgets configured."
        return payload

    async def _broadcast_status(self, active: ActiveSession, *, agent_running: bool) -> None:
        await self._broadcast(
            active,
            "on_status",
            agent_running=agent_running,
            usage=self._turn_usage_payload(active),
            llm_activity=active.llm_request_state,
            budget=active.state.budget,
        )

    async def update_session_budget(
        self, session_id: str, limits: Mapping[BudgetMetric, int | Decimal | None]
    ) -> list[str]:
        """Apply limits parsed by ``parse_budget_limit`` (``None`` or 0 clears one) and return a message per limit."""
        active = self._active.get(session_id)
        state = active.state if active is not None else self._session_mgr.load_state(session_id)
        if state is None:
            raise KeyError(session_id)
        updates = {BUDGET_METRIC_FIELDS[metric]: value for metric, value in limits.items()}
        # Revalidating normalizes 0 to "no limit", which is what ``/budget input 0`` means.
        state.budget = SessionBudget.model_validate(state.budget.model_dump() | updates)
        self._session_mgr.save_state(state)
        if active is not None:
            await self._broadcast_status(
                active, agent_running=active.agent_task is not None and not active.agent_task.done()
            )
        return [_budget_limit_message(metric, state.budget) for metric in limits]

    @contextlib.contextmanager
    def llm_request_recording(self, active: ActiveSession, *, track_activity: bool = True):
        """Record LLM requests for *active* into its request log.

        When *track_activity* is False (e.g. background auto-titling), the recorder still appends
        the audit record but does NOT mutate or broadcast ``active.llm_request_state`` — the
        session never appears busy and a concurrent real turn's activity state is left untouched.
        """
        engine = self
        session_id = active.state.session_id

        class Sink:
            async def on_request_started(self, state: LlmRequestState) -> None:
                active.llm_request_thinking.pop(state.request_id, None)
                if track_activity:
                    await engine._set_llm_request_state(active, state)

            async def on_request_completed(self, record: LlmRequestRecord) -> None:
                if track_activity:
                    thinking_content = active.llm_request_thinking.pop(record.request_id or "", "")
                    if thinking_content:
                        thinking_event: dict[str, Any] = {
                            "role": "thinking",
                            "content": thinking_content,
                        }
                        if record.request_id:
                            thinking_event["request_id"] = record.request_id
                        row = usage_last_request_row(record)
                        if row is not None and row["reasoning_duration_ms"] is not None:
                            thinking_event["reasoning_duration_ms"] = row["reasoning_duration_ms"]
                        if row is not None and row["reasoning_tokens"] is not None:
                            thinking_event["reasoning_tokens"] = row["reasoning_tokens"]
                        engine._session_mgr.append_events(session_id, [thinking_event])
                else:
                    active.llm_request_thinking.pop(record.request_id or "", None)
                active.llm_request_log.records.append(record)
                engine._session_mgr.save_llm_request_log(session_id, active.llm_request_log)
                if track_activity:
                    await engine._clear_llm_request_state(active)

            async def on_context(self, context: LlmContext) -> None:
                await engine._save_llm_context(active, context)

            async def on_context_failed(self, role: LlmSource, error: str) -> None:
                context = engine._session_mgr.load_llm_context(session_id, role)
                # A completed context was not cut by this failure: it finished before it, e.g. a sentinel
                # timeout during a skill file read, or belongs to an earlier evaluation.
                if context is None or context.status not in ("running", "interrupted"):
                    return
                completed_at = context.completed_at or datetime.now(tz=UTC)
                failed = context.model_copy(update={"status": "failed", "error": error, "completed_at": completed_at})
                await engine._save_llm_context(active, failed)

        with llm_request_sink_scope(Sink()):
            yield
