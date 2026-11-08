"""Session usage, budget, and LLM activity helpers."""

from __future__ import annotations

import contextlib
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

from ..models.config import Config
from ..models.session import SessionState
from ..usage import (
    BudgetGauge,
    BudgetMetric,
    LlmRequestRecord,
    LlmRequestState,
    LlmSource,
    SessionBudgetExceededError,
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

if TYPE_CHECKING:
    from pydantic_ai.usage import UsageLimits

_DEFAULT_CONTEXT_CAP_TOKENS = 200_000


class SessionUsageBudgetMixin:
    _active: dict[str, ActiveSession]
    _config: Config
    _session_mgr: SessionManager

    if TYPE_CHECKING:

        async def _broadcast(self, active: ActiveSession, method: str, *args: Any, **kwargs: Any) -> None: ...
        def _max_input_tokens_for_model_id(self, model_id: str) -> int | None: ...

    def _usage_last_llm_payload_row(self, active: ActiveSession, source: LlmSource) -> dict[str, Any] | None:
        """``usage_last_request_row`` plus ``context_cap_tokens`` and ``context_used_pct`` for the UI."""
        rec = last_record_for_source(active.llm_request_log, source)
        row = usage_last_request_row(rec)
        if row is None:
            return None
        mid = (
            active.agent_model_name or self._config.agent.model
            if source == "agent"
            else active.sentinel_model_name or self._config.agent.sentinel_model
        )
        cap = self._max_input_tokens_for_model_id(mid)
        if cap is None:
            cap = _DEFAULT_CONTEXT_CAP_TOKENS
        cs = row["context_size"]
        pct = min(100.0, (100.0 * cs / cap)) if cap > 0 else 0.0
        out: dict[str, Any] = dict(row)
        out["context_cap_tokens"] = cap
        out["context_used_pct"] = round(pct, 1)
        return out

    def agent_model_id_for_gauge(self, active: ActiveSession) -> str:
        """Canonical carapace model id (``provider:name``) for UI gauge / config lookup.

        Do not use the provider's raw ``model_name`` from the LLM log — it is often a short
        id without the ``provider:`` prefix, so it would not match ``available_models`` entries.
        """
        return active.agent_model_name or self._config.agent.model

    def agent_context_cap_for_gauge(self, active: ActiveSession) -> int:
        model_id = self.agent_model_id_for_gauge(active)
        return self._max_input_tokens_for_model_id(model_id) or _DEFAULT_CONTEXT_CAP_TOKENS

    def _budget_gauges(self, active: ActiveSession) -> list[BudgetGauge]:
        budget = active.state.budget
        return usage_budget_gauges(
            active.usage_tracker,
            input_tokens_limit=budget.input_tokens,
            output_tokens_limit=budget.output_tokens,
            total_cost_limit=budget.cost_usd,
            tool_calls_limit=budget.tool_calls,
        )

    def _budget_exceeded_error(self, active: ActiveSession) -> SessionBudgetExceededError | None:
        budget = active.state.budget
        return usage_budget_exceeded_error(
            active.usage_tracker,
            input_tokens_limit=budget.input_tokens,
            output_tokens_limit=budget.output_tokens,
            total_cost_limit=budget.cost_usd,
            tool_calls_limit=budget.tool_calls,
        )

    def _assert_llm_budget_available(self, active: ActiveSession) -> None:
        error = self._budget_exceeded_error(active)
        if error is not None:
            raise error

    def _remaining_usage_limits(self, active: ActiveSession) -> UsageLimits | None:
        return usage_limits_for_remaining_budget(
            active.usage_tracker,
            output_tokens_limit=active.state.budget.output_tokens,
        )

    def _remaining_aux_usage_limits(self, active: ActiveSession) -> UsageLimits | None:
        return usage_limits_for_remaining_budget(
            active.usage_tracker,
            output_tokens_limit=active.state.budget.output_tokens,
            request_limit=10,
        )

    def _turn_usage_payload(self, active: ActiveSession) -> TurnUsage | None:
        rec_agent = last_record_for_source(active.llm_request_log, "agent")
        budget_gauges = self._budget_gauges(active)
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

    async def _maybe_promote_llm_request_state(self, active: ActiveSession, state: LlmRequestState | None) -> None:
        if state is None:
            return
        current = active.llm_request_state
        if current is not None and current.phase == state.phase and current.first_text_at == state.first_text_at:
            return
        await self._set_llm_request_state(active, state)

    def _budget_command_payload(self, active: ActiveSession, *, message: str | None = None) -> dict[str, Any]:
        gauges = self._budget_gauges(active)
        usage_hint = (
            "Set budgets with /budget input N, /budget output N, /budget cost N, "
            "or /budget tools N. Use 0 to clear a limit."
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

    async def update_session_budget(self, session_id: str, limits: Mapping[BudgetMetric, str | None]) -> list[str]:
        """Set budget limits from raw ``/budget`` values (``None`` clears one) and return a message per limit.

        Every value is parsed before any is applied, so one invalid limit leaves the whole budget untouched.
        """
        active = self._active.get(session_id)
        state = active.state if active is not None else self._session_mgr.load_state(session_id)
        if state is None:
            raise KeyError(session_id)
        # 0 is the setter's "no limit", exactly like ``/budget input 0``.
        values = {
            metric: 0 if raw is None else self._parse_budget_limit_value(metric, raw) for metric, raw in limits.items()
        }
        messages = [self._set_budget_metric(state, metric, value) for metric, value in values.items()]
        if active is not None:
            await self._broadcast(
                active,
                "on_status",
                agent_running=active.agent_task is not None and not active.agent_task.done(),
                usage=self._turn_usage_payload(active),
                llm_activity=active.llm_request_state,
            )
        return messages

    def _parse_budget_limit_value(self, metric: BudgetMetric, raw: str) -> int | Decimal:
        cleaned = raw.replace(",", "").replace("_", "")
        if metric in ("input", "output", "tool_calls"):
            lowered = cleaned.lower()
            multiplier = 1
            if lowered.endswith("k"):
                multiplier = 1_000
                lowered = lowered[:-1]
            elif lowered.endswith("m"):
                multiplier = 1_000_000
                lowered = lowered[:-1]

            budget_type = "tool call budget" if metric == "tool_calls" else "token budget"
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
            raise ValueError(f"Invalid cost budget: {raw}") from exc
        if value < 0:
            raise ValueError("Budget value must be >= 0")
        return value

    def _set_budget_metric(self, state: SessionState, metric: BudgetMetric, value: int | Decimal) -> str:
        budget = state.budget.model_copy(deep=True)
        if metric == "input":
            budget.input_tokens = int(value)
            if budget.input_tokens == 0:
                budget.input_tokens = None
            state.budget = budget
            self._session_mgr.save_state(state)
            if budget.input_tokens is None:
                return "Cleared input token budget."
            return f"Set input token budget to {budget.input_tokens:,} tokens."
        if metric == "output":
            budget.output_tokens = int(value)
            if budget.output_tokens == 0:
                budget.output_tokens = None
            state.budget = budget
            self._session_mgr.save_state(state)
            if budget.output_tokens is None:
                return "Cleared output token budget."
            return f"Set output token budget to {budget.output_tokens:,} tokens."
        if metric == "tool_calls":
            budget.tool_calls = int(value)
            if budget.tool_calls == 0:
                budget.tool_calls = None
            state.budget = budget
            self._session_mgr.save_state(state)
            if budget.tool_calls is None:
                return "Cleared tool call budget."
            suffix = "call" if budget.tool_calls == 1 else "calls"
            return f"Set tool call budget to {budget.tool_calls:,} tool {suffix}."
        budget.cost_usd = Decimal(value)
        if budget.cost_usd == Decimal(0):
            budget.cost_usd = None
        state.budget = budget
        self._session_mgr.save_state(state)
        if budget.cost_usd is None:
            return "Cleared cost budget."
        return f"Set cost budget to ${budget.cost_usd:.4f}."

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

        with llm_request_sink_scope(Sink()):
            yield
