from __future__ import annotations

from pydantic_ai.usage import RunUsage

from carapace.usage import UsageTracker


def test_record_sets_context_tokens_to_last_event_slice() -> None:
    t = UsageTracker()
    t.record(
        "m",
        "agent",
        RunUsage(input_tokens=100, output_tokens=50, requests=1),
    )
    assert t.categories["agent"].context_tokens == 150
    assert t.models["m"].context_tokens == 150
    t.record("m", "agent", RunUsage(input_tokens=10, output_tokens=5, requests=1))
    assert t.categories["agent"].context_tokens == 15


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
