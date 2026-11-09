"""How ``/usage`` output presents actual and equivalent cost; shared by the CLI and the Matrix channel.

Kept free of server dependencies: the CLI client imports it.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

SUBSCRIPTION_NOTE = " · subscription"


def show_equivalent_total(budget_gauges: list[dict[str, Any]]) -> bool:
    """The equivalent total follows its gauge: shown with a limit or when the session used a subscription."""
    return any(gauge.get("key") == "equivalent_cost" for gauge in budget_gauges)


def equivalent_note(equivalent: str) -> str:
    return f" (≈ ${Decimal(equivalent):.4f} equivalent)"


def category_equivalent_note(cost: dict[str, Any]) -> str:
    """Note for a category's cost, only where subscription usage makes the equivalent cost differ."""
    actual, equivalent = str(cost.get("actual", "0")), str(cost.get("equivalent", "0"))
    return "" if Decimal(actual) == Decimal(equivalent) else equivalent_note(equivalent)
