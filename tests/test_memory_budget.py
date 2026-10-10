from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from carapace.memory.budget import Spend, affordable_count, budget_windows, fits, spend_of, sum_estimates
from carapace.memory.models import Provenance, TaskEstimate
from carapace.models.user import MemoryBudget


def _estimate(cost: str | None, tokens: int = 1000) -> TaskEstimate:
    return TaskEstimate(model="m", input_tokens=tokens, output_tokens_cap=100, cost_usd=Decimal(cost) if cost else None)


def test_budget_windows_use_local_day_and_calendar_month():
    now = datetime(2026, 9, 30, 22, 30, tzinfo=UTC)  # 00:30 on Oct 1 in Berlin
    windows = budget_windows(now, ZoneInfo("Europe/Berlin"))
    assert windows.day_start == datetime(2026, 9, 30, 22, tzinfo=UTC)
    assert windows.month_start == datetime(2026, 9, 30, 22, tzinfo=UTC)

    utc = budget_windows(now, UTC)
    assert utc.day_start == datetime(2026, 9, 30, tzinfo=UTC)
    assert utc.month_start == datetime(2026, 9, 1, tzinfo=UTC)


def test_fits_checks_every_configured_limit():
    budget = MemoryBudget(cost_usd_per_day=Decimal("1.00"), cost_usd_per_month=Decimal("2.00"))
    assert fits(budget, Spend(Decimal("0.50")), Spend(Decimal("1.50")), _estimate("0.50"))
    assert not fits(budget, Spend(Decimal("0.50")), Spend(Decimal("1.50")), _estimate("0.51"))
    assert not fits(budget, Spend(Decimal("0.90")), Spend(Decimal("0.90")), _estimate("0.20"))

    tokens = MemoryBudget(cost_usd_per_day=None, cost_usd_per_month=None, input_tokens_per_month=5000)
    assert fits(tokens, Spend(), Spend(input_tokens=4000), _estimate("9.99", tokens=1000))
    assert not fits(tokens, Spend(), Spend(input_tokens=4001), _estimate("0.01", tokens=1000))


def test_unpriced_and_free_tasks():
    budget = MemoryBudget(cost_usd_per_day=Decimal(0), input_tokens_per_day=1000)
    # Unpriced work adds no cost, so only token limits bound it.
    assert fits(budget, Spend(), Spend(), _estimate(None, tokens=1000))
    assert not fits(budget, Spend(), Spend(), _estimate(None, tokens=1001))
    # No estimate (mirror) is free.
    assert fits(budget, Spend(Decimal(5), 10**9), Spend(Decimal(5), 10**9), None)


def test_affordable_count_stops_at_first_unaffordable_task():
    budget = MemoryBudget(cost_usd_per_day=Decimal("1.00"))
    estimates = [_estimate("0.40"), None, _estimate("0.40"), _estimate("0.40"), _estimate("0.01")]
    assert affordable_count(budget, Spend(), Spend(), estimates) == 3
    assert affordable_count(budget, Spend(Decimal("0.70")), Spend(), estimates) == 0
    assert (
        affordable_count(MemoryBudget(cost_usd_per_day=None, cost_usd_per_month=None), Spend(), Spend(), estimates) == 5
    )


def test_sum_estimates():
    total = sum_estimates([_estimate("0.10"), _estimate(None, tokens=500), None])
    assert total.task_count == 3
    assert total.input_tokens == 1500
    assert total.output_tokens_cap == 200
    assert total.cost_usd == Decimal("0.10")
    assert total.unpriced_count == 1


def test_spend_of():
    def provenance(cost: str | None, tokens: int) -> Provenance:
        return Provenance(
            carapace_version="0",
            model="m",
            prompt_version="p",
            input_format_version=1,
            input_hash="h",
            input_tokens=tokens,
            output_tokens=1,
            cost_usd=Decimal(cost) if cost else None,
            duration_ms=1,
            task_id=1,
            created_at=datetime.now(tz=UTC),
        )

    assert spend_of([provenance("0.25", 10), provenance(None, 5)]) == Spend(Decimal("0.25"), 15)
