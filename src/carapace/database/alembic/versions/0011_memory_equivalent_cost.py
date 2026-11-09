"""split the memory budget into actual and equivalent cost

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-09 20:00:00.000000

"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from decimal import Decimal

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")

_users = sa.table("users", sa.column("username", sa.String), sa.column("config", _JSON))
# The memory costs stored per task and record are list prices: they become the equivalent cost.
_PRICED_COLUMNS = (
    ("memory_tasks", "estimate"),
    ("memory_tasks", "provenance"),
    ("memory_session_extractions", "provenance"),
    ("memory_digests", "provenance"),
)
_WINDOWS = ("per_day", "per_month")


def _budget_to_equivalent(budget: dict) -> dict:
    """The old limits priced subscription usage at list price too: they are the new equivalent limits.

    An explicitly stored null ("off") moves as well, so an unlimited budget stays unlimited.
    """
    moved = {f"cost_usd_{w}": None for w in _WINDOWS if f"cost_usd_{w}" in budget}
    return budget | moved | {f"equivalent_{key}": budget[key] for key in moved}


def _budget_to_single_cost(budget: dict) -> dict:
    """Back to one list-price limit per window: the stricter of the two, since the old limit priced everything."""
    single = {key: value for key, value in budget.items() if not key.startswith("equivalent_")}
    for window in _WINDOWS:
        keys = [f"cost_usd_{window}", f"equivalent_cost_usd_{window}"]
        if not any(key in budget for key in keys):
            continue
        limits = [Decimal(str(budget[key])) for key in keys if budget.get(key) is not None]
        single[f"cost_usd_{window}"] = str(min(limits)) if limits else None
    return single


def _rename_key(old: str, new: str) -> Callable[[dict], dict]:
    def rename(payload: dict) -> dict:
        return {new if key == old else key: value for key, value in payload.items()}

    return rename


def _change_user_budgets(change: Callable[[dict], dict]) -> None:
    bind = op.get_bind()
    for username, config in bind.execute(sa.select(_users.c.username, _users.c.config)).all():
        memory = config.get("memory")
        if memory is not None and "budget" in memory:
            bind.execute(
                _users.update()
                .where(_users.c.username == username)
                .values(config=config | {"memory": memory | {"budget": change(memory["budget"])}})
            )


def _change_priced_records(change: Callable[[dict], dict]) -> None:
    bind = op.get_bind()
    for table_name, column_name in _PRICED_COLUMNS:
        records = sa.table(table_name, sa.column("id", sa.BigInteger), sa.column(column_name, _JSON))
        for record_id, value in bind.execute(sa.select(records.c.id, records.c[column_name])).all():
            # Tasks without an estimate or provenance yet hold SQL or JSON null; both read as None.
            if value is not None:
                bind.execute(records.update().where(records.c.id == record_id).values({column_name: change(value)}))


def upgrade() -> None:
    _change_user_budgets(_budget_to_equivalent)
    _change_priced_records(_rename_key("cost_usd", "equivalent_cost_usd"))


def downgrade() -> None:
    _change_user_budgets(_budget_to_single_cost)
    _change_priced_records(_rename_key("equivalent_cost_usd", "cost_usd"))
