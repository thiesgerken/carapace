"""Budget math for memory LLM tasks: spend windows, the gate decision and estimate pricing.

Unpriced work (local models without pricing data) adds nothing to cost and is bounded only
by the token limits, which exist for exactly that case.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from ..models.user import MemoryBudget
from ..usage import ModelUsage, price_for_usage
from .models import EstimateTotal, Provenance, TaskEstimate
from .periods import local_midnight_utc


@dataclass(frozen=True)
class Spend:
    cost_usd: Decimal = Decimal(0)
    input_tokens: int = 0

    def plus(self, estimate: TaskEstimate) -> Spend:
        return Spend(self.cost_usd + (estimate.cost_usd or 0), self.input_tokens + estimate.input_tokens)


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


def spend_of(provenances: Iterable[Provenance]) -> Spend:
    total = Spend()
    for p in provenances:
        total = Spend(total.cost_usd + (p.cost_usd or 0), total.input_tokens + p.input_tokens)
    return total


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> Decimal | None:
    """Price of a call at the model's list price. None when the model has no pricing data."""
    return price_for_usage(model, ModelUsage(input_tokens=input_tokens, output_tokens=output_tokens))


def fits(budget: MemoryBudget, day: Spend, month: Spend, estimate: TaskEstimate | None) -> bool:
    """Whether running a task keeps every configured limit. Tasks without an estimate are free."""
    if estimate is None:
        return True
    day, month = day.plus(estimate), month.plus(estimate)
    checks = (
        (budget.cost_usd_per_day, day.cost_usd),
        (budget.cost_usd_per_month, month.cost_usd),
        (budget.input_tokens_per_day, day.input_tokens),
        (budget.input_tokens_per_month, month.input_tokens),
    )
    return all(limit is None or spent <= limit for limit, spent in checks)


def affordable_count(budget: MemoryBudget, day: Spend, month: Spend, estimates: Sequence[TaskEstimate | None]) -> int:
    """Length of the longest prefix of *estimates* that fits the budget together.

    A prefix, not a best fit: auto mode promotes in priority order and stops at the first task
    it cannot afford rather than skipping ahead to cheaper ones.
    """
    for count, estimate in enumerate(estimates):
        if not fits(budget, day, month, estimate):
            return count
        if estimate is not None:
            day, month = day.plus(estimate), month.plus(estimate)
    return len(estimates)


def sum_estimates(estimates: Iterable[TaskEstimate | None]) -> EstimateTotal:
    task_count = input_tokens = output_tokens_cap = unpriced_count = 0
    cost_usd = Decimal(0)
    for estimate in estimates:
        task_count += 1
        if estimate is None:
            continue
        input_tokens += estimate.input_tokens
        output_tokens_cap += estimate.output_tokens_cap
        if estimate.cost_usd is None:
            unpriced_count += 1
        else:
            cost_usd += estimate.cost_usd
    return EstimateTotal(
        task_count=task_count,
        input_tokens=input_tokens,
        output_tokens_cap=output_tokens_cap,
        cost_usd=cost_usd,
        unpriced_count=unpriced_count,
    )
