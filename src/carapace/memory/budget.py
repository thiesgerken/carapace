"""Budget math for memory LLM tasks: spend windows, the gate decision and estimate pricing.

Every LLM task has an estimate; tasks without an LLM call (mirror) never reach these functions.
Unpriced work (local models without pricing data) adds nothing to cost and is bounded only
by the token limits, which exist for exactly that case. Cost is tracked as actual and equivalent
cost (see ``usage.CostSplit``), each against its own limits.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from ..models.user import MemoryBudget
from ..usage import CostSplit, ModelUsage, price_for_usage
from .models import EstimateTotal, TaskEstimate
from .periods import local_midnight_utc


@dataclass(frozen=True)
class Spend:
    cost: CostSplit = field(default_factory=CostSplit)
    input_tokens: int = 0

    def plus(self, estimate: TaskEstimate) -> Spend:
        return Spend(self.cost + _estimate_cost(estimate), self.input_tokens + estimate.input_tokens)

    def plus_spend(self, other: Spend) -> Spend:
        return Spend(self.cost + other.cost, self.input_tokens + other.input_tokens)


def _estimate_cost(estimate: TaskEstimate) -> CostSplit:
    return CostSplit(actual=estimate.cost_usd or Decimal(0), equivalent=estimate.equivalent_cost_usd or Decimal(0))


@dataclass(frozen=True)
class BudgetWindows:
    """UTC starts of the current budget windows: the local day and the local calendar month."""

    day_start: datetime
    month_start: datetime


def budget_windows(now: datetime, tz: ZoneInfo) -> BudgetWindows:
    today = now.astimezone(tz).date()
    return BudgetWindows(
        day_start=local_midnight_utc(today, tz),
        month_start=local_midnight_utc(today.replace(day=1), tz),
    )


def estimate_cost(model: str, input_tokens: int, output_tokens: int, *, cached_tokens: int = 0) -> Decimal | None:
    """Price of a call at the model's list price (its equivalent cost). None when the model has no pricing data.

    *cached_tokens* of the input go through the prompt cache and are priced as cache writes: a
    write costs more than a read or uncached input, so the estimate stays an upper bound. Models
    without a cache write price charge them as plain input.
    """
    usage = ModelUsage(input_tokens=input_tokens, output_tokens=output_tokens, cache_write_tokens=cached_tokens)
    return price_for_usage(model, usage)


def fits(budget: MemoryBudget, day: Spend, month: Spend, estimate: TaskEstimate) -> bool:
    """Whether running a task keeps every configured limit."""
    day, month = day.plus(estimate), month.plus(estimate)
    checks = (
        (budget.cost_usd_per_day, day.cost.actual),
        (budget.cost_usd_per_month, month.cost.actual),
        (budget.equivalent_cost_usd_per_day, day.cost.equivalent),
        (budget.equivalent_cost_usd_per_month, month.cost.equivalent),
        (budget.input_tokens_per_day, day.input_tokens),
        (budget.input_tokens_per_month, month.input_tokens),
    )
    return all(limit is None or spent <= limit for limit, spent in checks)


def affordable_count(budget: MemoryBudget, day: Spend, month: Spend, estimates: Sequence[TaskEstimate]) -> int:
    """Length of the longest prefix of *estimates* that fits the budget together.

    A prefix, not a best fit: auto mode promotes in priority order and stops at the first task
    it cannot afford rather than skipping ahead to cheaper ones.
    """
    for count, estimate in enumerate(estimates):
        if not fits(budget, day, month, estimate):
            return count
        day, month = day.plus(estimate), month.plus(estimate)
    return len(estimates)


def sum_estimates(estimates: Iterable[TaskEstimate]) -> EstimateTotal:
    task_count = input_tokens = output_tokens_cap = unpriced_count = 0
    cost = CostSplit()
    for estimate in estimates:
        task_count += 1
        input_tokens += estimate.input_tokens
        output_tokens_cap += estimate.output_tokens_cap
        unpriced_count += estimate.equivalent_cost_usd is None
        cost += _estimate_cost(estimate)
    return EstimateTotal(
        task_count=task_count,
        input_tokens=input_tokens,
        output_tokens_cap=output_tokens_cap,
        cost_usd=cost.actual,
        equivalent_cost_usd=cost.equivalent,
        unpriced_count=unpriced_count,
    )
