from __future__ import annotations

from decimal import Decimal

from pydantic_ai.usage import RunUsage

from carapace.usage import (
    UsageTracker,
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
    total = t.estimated_cost().get("total")
    if total is None or total == 0:
        return
    cats = t.estimated_category_cost()
    assert sum(cats.values()) == total


def test_usage_budget_gauges_include_tokens_and_cost() -> None:
    tracker = UsageTracker()
    tracker.record(
        "anthropic:claude-haiku-4-5",
        "agent",
        RunUsage(input_tokens=1_000, output_tokens=250, requests=1),
    )

    gauges = usage_budget_gauges(
        tracker,
        input_tokens_limit=2_000,
        output_tokens_limit=500,
        total_cost_limit=Decimal("1.00"),
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

    gauges = usage_budget_gauges(
        tracker,
        tool_calls_limit=5,
    )

    assert [g.key for g in gauges] == ["tool_calls"]
    assert gauges[0].current_value == "3 tool calls"
    assert gauges[0].limit_value == "5 tool calls"
    assert gauges[0].remaining_value == "2 tool calls"
    assert gauges[0].current_amount == 3.0


def test_usage_budget_exceeded_error_includes_tool_calls() -> None:
    tracker = UsageTracker(tool_calls=2)

    error = usage_budget_exceeded_error(
        tracker,
        tool_calls_limit=2,
    )

    assert error is not None
    assert str(error) == "Session budget reached: tool calls 2 tool calls / 2 tool calls"


def test_usage_budget_exceeded_error_treats_unknown_cost_pricing_as_zero() -> None:
    tracker = UsageTracker()
    tracker.record(
        "local:unknown-model",
        "agent",
        RunUsage(input_tokens=100, output_tokens=50, requests=1),
    )

    error = usage_budget_exceeded_error(
        tracker,
        total_cost_limit=Decimal("5.00"),
    )

    assert error is None

    gauges = usage_budget_gauges(
        tracker,
        total_cost_limit=Decimal("5.00"),
    )
    assert gauges[0].current_value == "$0.0000"
    assert gauges[0].current_amount == 0.0


def test_usage_limits_for_remaining_budget_uses_remaining_output_tokens() -> None:
    tracker = UsageTracker()
    tracker.record(
        "anthropic:claude-haiku-4-5",
        "agent",
        RunUsage(input_tokens=100, output_tokens=250, requests=1),
    )

    limits = usage_limits_for_remaining_budget(tracker, output_tokens_limit=500)

    assert limits is not None
    assert limits.output_tokens_limit == 250


def test_usage_limits_for_remaining_budget_can_include_request_limit() -> None:
    tracker = UsageTracker()

    limits = usage_limits_for_remaining_budget(tracker, request_limit=5)

    assert limits is not None
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


def test_usage_limits_for_remaining_budget_returns_none_without_output_limit() -> None:
    tracker = UsageTracker()

    limits = usage_limits_for_remaining_budget(tracker)

    assert limits is None
