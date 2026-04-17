from __future__ import annotations

from decimal import Decimal

from pydantic_ai.usage import RunUsage

from carapace.usage import UsageTracker, usage_budget_exceeded_error, usage_budget_gauges


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


def test_usage_budget_exceeded_error_blocks_unknown_cost_pricing() -> None:
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

    assert error is not None
    assert "Pricing unavailable" in str(error)
    assert error.gauges[0].unavailable_reason is not None
