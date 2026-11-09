from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from pydantic_ai.messages import ModelRequest, ModelResponse
from pydantic_ai.usage import RunUsage

from carapace.models.session import SessionBudget
from carapace.usage import (
    CostSplit,
    SessionBudgetExceededError,
    UsageTracker,
    agent_request_limit,
    price_for_usage,
    provider_cost_usd_from_messages,
    usage_budget_exceeded_error,
    usage_budget_gauges,
    usage_limits_for_remaining_budget,
)


def test_record_accumulates_tokens_across_events() -> None:
    t = UsageTracker()
    t.record(
        "m",
        "agent",
        RunUsage(input_tokens=100, output_tokens=50, requests=1),
    )
    assert t.categories["agent"].input_tokens == 100
    assert t.categories["agent"].output_tokens == 50
    t.record("m", "agent", RunUsage(input_tokens=10, output_tokens=5, requests=1))
    assert t.categories["agent"].input_tokens == 110
    assert t.categories["agent"].output_tokens == 55


def test_record_tool_call_increments_counter() -> None:
    tracker = UsageTracker()

    tracker.record_tool_call()
    tracker.record_tool_call()

    assert tracker.tool_calls == 2


def test_category_by_model_splits_per_category() -> None:
    t = UsageTracker()
    t.record(
        "anthropic:claude-haiku-4-5",
        "agent",
        RunUsage(input_tokens=100, output_tokens=50, requests=2),
    )
    t.record(
        "anthropic:claude-haiku-4-5",
        "title",
        RunUsage(input_tokens=10, output_tokens=5, requests=1),
    )
    assert t.models["anthropic:claude-haiku-4-5"].input_tokens == 110
    assert t.category_by_model["agent"]["anthropic:claude-haiku-4-5"].input_tokens == 100
    assert t.category_by_model["title"]["anthropic:claude-haiku-4-5"].input_tokens == 10


def test_provider_cost_usd_from_messages_sums_response_costs() -> None:
    messages = [
        ModelRequest(parts=[]),
        ModelResponse(parts=[], provider_details={"cost": 0.0012}),
        ModelResponse(parts=[], provider_details={"cost": "0.0034"}),
        ModelResponse(parts=[], provider_details={"cost": True}),
        ModelResponse(parts=[]),
    ]

    assert provider_cost_usd_from_messages(messages) == Decimal("0.0046")


def test_estimated_cost_uses_provider_cost_when_available() -> None:
    t = UsageTracker()
    t.record(
        "openrouter:openai/gpt-5.2",
        "agent",
        RunUsage(input_tokens=100, output_tokens=50, requests=1),
        cost_usd=Decimal("0.0123"),
    )

    cost = CostSplit(actual=Decimal("0.0123"), equivalent=Decimal("0.0123"))
    assert t.cost_by_model()["openrouter:openai/gpt-5.2"] == cost
    assert t.total_cost() == cost
    assert t.cost_by_category()["agent"] == cost


def test_estimated_cost_uses_token_price_when_provider_cost_is_partial(monkeypatch: pytest.MonkeyPatch) -> None:
    class Price:
        total_price = Decimal("0.05")

    def fake_calc_price(*_args: Any, **_kwargs: Any) -> Price:
        return Price()

    monkeypatch.setattr("carapace.usage.calc_price", fake_calc_price)
    t = UsageTracker()
    t.record(
        "openrouter:openai/gpt-5.2",
        "agent",
        RunUsage(input_tokens=100, output_tokens=50, requests=1),
        cost_usd=Decimal("0.0123"),
    )
    t.record(
        "openrouter:openai/gpt-5.2",
        "agent",
        RunUsage(input_tokens=1000, output_tokens=500, requests=1),
    )

    assert t.cost_by_model()["openrouter:openai/gpt-5.2"].actual == Decimal("0.05")
    assert t.cost_by_category()["agent"].actual == Decimal("0.05")


def test_estimated_cost_falls_back_to_provider_cost_when_pricing_is_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_calc_price(*_args: Any, **_kwargs: Any) -> None:
        raise LookupError

    monkeypatch.setattr("carapace.usage.calc_price", fake_calc_price)
    t = UsageTracker()
    t.record(
        "openrouter:unknown-model",
        "agent",
        RunUsage(input_tokens=100, output_tokens=50, requests=1),
        cost_usd=Decimal("0.0123"),
    )

    assert t.cost_by_model()["openrouter:unknown-model"].actual == Decimal("0.0123")
    assert t.cost_by_category()["agent"].actual == Decimal("0.0123")


def test_estimated_category_cost_sums_to_model_costs_when_disjoint() -> None:
    """Each model is only used in one category → per-category prices sum to total."""
    t = UsageTracker()
    t.record(
        "google-gla:gemini-2.0-flash",
        "sentinel",
        RunUsage(input_tokens=1000, output_tokens=100, requests=1),
    )
    t.record(
        "anthropic:claude-haiku-4-5",
        "agent",
        RunUsage(input_tokens=500, output_tokens=50, requests=1),
    )
    total = t.total_cost()
    assert total.actual > 0
    assert sum(t.cost_by_category().values(), CostSplit()) == total


def test_usage_budget_gauges_include_tokens_and_cost() -> None:
    tracker = UsageTracker()
    tracker.record(
        "anthropic:claude-haiku-4-5",
        "agent",
        RunUsage(input_tokens=1_000, output_tokens=250, requests=1),
    )

    gauges = usage_budget_gauges(
        tracker, SessionBudget(input_tokens=2_000, output_tokens=500, cost_usd=Decimal("1.00"))
    )

    assert [g.key for g in gauges] == ["input", "output", "cost"]
    assert gauges[0].current_value == "1.0k tokens"
    assert gauges[0].current_amount == 1_000.0
    assert gauges[1].current_value == "250 tokens"
    assert gauges[1].current_amount == 250.0
    assert gauges[2].limit_value == "$1.0000"
    assert gauges[2].current_amount is not None


def test_usage_budget_gauges_include_tool_calls() -> None:
    tracker = UsageTracker(tool_calls=3)

    gauges = usage_budget_gauges(tracker, SessionBudget(tool_calls=5))

    assert [g.key for g in gauges] == ["tool_calls"]
    assert gauges[0].current_value == "3 tool calls"
    assert gauges[0].limit_value == "5 tool calls"
    assert gauges[0].remaining_value == "2 tool calls"
    assert gauges[0].current_amount == 3.0


def test_usage_budget_exceeded_error_includes_tool_calls() -> None:
    tracker = UsageTracker(tool_calls=2)

    error = usage_budget_exceeded_error(tracker, SessionBudget(tool_calls=2))

    assert error is not None
    assert str(error) == (
        "Session budget reached: tool calls 2 tool calls / 2 tool calls. "
        "Raise the limit to continue: /budget tool_calls N"
    )


def test_usage_budget_exceeded_error_names_a_command_for_every_reached_limit() -> None:
    tracker = UsageTracker(tool_calls=2)
    tracker.record("test:model", "agent", RunUsage(input_tokens=1_000))

    error = usage_budget_exceeded_error(tracker, SessionBudget(input_tokens=1_000, output_tokens=500, tool_calls=2))

    assert error is not None
    assert str(error).endswith("Raise the limit to continue: /budget input N, /budget tool_calls N")


def test_session_budget_exceeded_error_requires_a_reached_gauge() -> None:
    with pytest.raises(ValueError, match="reached budget gauge"):
        SessionBudgetExceededError(usage_budget_gauges(UsageTracker(tool_calls=1), SessionBudget(tool_calls=2)))


def test_usage_budget_exceeded_error_treats_unknown_cost_pricing_as_zero() -> None:
    tracker = UsageTracker()
    tracker.record(
        "local:unknown-model",
        "agent",
        RunUsage(input_tokens=100, output_tokens=50, requests=1),
    )

    error = usage_budget_exceeded_error(tracker, SessionBudget(cost_usd=Decimal("5.00")))

    assert error is None

    gauges = usage_budget_gauges(tracker, SessionBudget(cost_usd=Decimal("5.00")))
    assert gauges[0].current_value == "$0.0000"
    assert gauges[0].current_amount == 0.0


def test_usage_limits_for_remaining_budget_uses_remaining_output_tokens() -> None:
    tracker = UsageTracker()
    tracker.record(
        "anthropic:claude-haiku-4-5",
        "agent",
        RunUsage(input_tokens=100, output_tokens=250, requests=1),
    )

    limits = usage_limits_for_remaining_budget(tracker, output_tokens_limit=500, request_limit=None)

    assert limits.output_tokens_limit == 250
    assert limits.request_limit is None


def test_usage_limits_for_remaining_budget_can_include_request_limit() -> None:
    tracker = UsageTracker()

    limits = usage_limits_for_remaining_budget(tracker, output_tokens_limit=None, request_limit=5)

    assert limits.request_limit == 5
    assert limits.output_tokens_limit is None


def test_usage_limits_for_remaining_budget_combines_output_and_request_limits() -> None:
    tracker = UsageTracker()
    tracker.record(
        "anthropic:claude-haiku-4-5",
        "agent",
        RunUsage(input_tokens=100, output_tokens=250, requests=1),
    )

    limits = usage_limits_for_remaining_budget(tracker, output_tokens_limit=500, request_limit=5)

    assert limits is not None
    assert limits.output_tokens_limit == 250
    assert limits.request_limit == 5


def test_usage_limits_for_remaining_budget_is_explicit_without_any_limit() -> None:
    limits = usage_limits_for_remaining_budget(UsageTracker(), output_tokens_limit=None, request_limit=None)

    # pydantic-ai would otherwise fall back to its own default request limit.
    assert (limits.output_tokens_limit, limits.request_limit) == (None, None)


def test_agent_request_limit_is_three_times_the_autonomy_limit() -> None:
    assert agent_request_limit(100) == 300
    assert agent_request_limit(None) is None


# --- actual vs. equivalent cost (subscription models) ---

_SUBSCRIPTION_MODEL = "openai-codex:gpt-5.4"
_API_MODEL = "anthropic:claude-haiku-4-5"


def _mixed_session() -> tuple[UsageTracker, Decimal, Decimal]:
    """Agent on a ChatGPT subscription, sentinel on a pay-per-token API; returns both model prices."""
    tracker = UsageTracker()
    tracker.record(_SUBSCRIPTION_MODEL, "agent", RunUsage(input_tokens=100_000, output_tokens=10_000, requests=3))
    tracker.record(_API_MODEL, "sentinel", RunUsage(input_tokens=20_000, output_tokens=1_000, requests=2))
    subscription_price = price_for_usage(_SUBSCRIPTION_MODEL, tracker.models[_SUBSCRIPTION_MODEL])
    api_price = price_for_usage(_API_MODEL, tracker.models[_API_MODEL])
    assert subscription_price and api_price
    return tracker, subscription_price, api_price


def test_mixed_session_bills_only_the_pay_per_token_model() -> None:
    tracker, subscription_price, api_price = _mixed_session()

    assert tracker.has_subscription_usage
    assert tracker.total_cost() == CostSplit(actual=api_price, equivalent=api_price + subscription_price)
    assert tracker.cost_by_model() == {
        _SUBSCRIPTION_MODEL: CostSplit(actual=Decimal(0), equivalent=subscription_price),
        _API_MODEL: CostSplit(actual=api_price, equivalent=api_price),
    }
    assert tracker.cost_by_category() == {
        "agent": CostSplit(actual=Decimal(0), equivalent=subscription_price),
        "sentinel": CostSplit(actual=api_price, equivalent=api_price),
    }


def test_mixed_session_enforces_each_cost_limit_on_its_own_total() -> None:
    tracker, subscription_price, api_price = _mixed_session()
    total_equivalent = api_price + subscription_price

    # Real money is well under its limit, but the list price of everything is over its own.
    equivalent_reached = usage_budget_exceeded_error(
        tracker, SessionBudget(cost_usd=api_price * 2, equivalent_cost_usd=total_equivalent)
    )
    assert equivalent_reached is not None
    assert [gauge.key for gauge in equivalent_reached.gauges if gauge.reached] == ["equivalent_cost"]
    assert str(equivalent_reached).endswith("Raise the limit to continue: /budget equivalent_cost N")

    actual_reached = usage_budget_exceeded_error(
        tracker, SessionBudget(cost_usd=api_price, equivalent_cost_usd=total_equivalent * 2)
    )
    assert actual_reached is not None
    assert [gauge.key for gauge in actual_reached.gauges if gauge.reached] == ["cost"]
    assert str(actual_reached).endswith("Raise the limit to continue: /budget cost N")

    assert usage_budget_exceeded_error(tracker, SessionBudget(cost_usd=api_price * 2)) is None


def test_equivalent_cost_gauge_shows_with_subscription_usage_or_a_limit() -> None:
    mixed, subscription_price, api_price = _mixed_session()
    api_only = UsageTracker()
    api_only.record(_API_MODEL, "agent", RunUsage(input_tokens=1_000, output_tokens=100, requests=1))

    [unlimited] = usage_budget_gauges(mixed, SessionBudget())
    assert (unlimited.key, unlimited.limit_value, unlimited.reached) == ("equivalent_cost", None, False)
    assert unlimited.current_amount == float(api_price + subscription_price)
    assert usage_budget_gauges(api_only, SessionBudget()) == []
    assert [gauge.key for gauge in usage_budget_gauges(api_only, SessionBudget(equivalent_cost_usd=Decimal(5)))] == [
        "equivalent_cost"
    ]
    assert [gauge.key for gauge in usage_budget_gauges(api_only, SessionBudget(cost_usd=Decimal(5)))] == ["cost"]
