"""split the cost budget into actual and equivalent cost

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-09 18:00:00.000000

"""

from __future__ import annotations

from collections.abc import Callable, Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")

_platform_settings = sa.table("platform_settings", sa.column("key", sa.String), sa.column("data", _JSON))
_users = sa.table("users", sa.column("username", sa.String), sa.column("config", _JSON))
_sessions = sa.table("sessions", sa.column("session_id", sa.String), sa.column("state", _JSON))


def _to_equivalent(budget: dict) -> dict:
    """The old cost limit priced subscription usage at list price too: it is the new equivalent cost limit."""
    return budget | {"cost_usd": None, "equivalent_cost_usd": budget.get("cost_usd")}


def _to_single_cost(budget: dict) -> dict:
    """Back to one list-price cost limit; it takes the equivalent limit, or the actual one if only that is set."""
    single = {key: value for key, value in budget.items() if key != "equivalent_cost_usd"}
    equivalent = budget.get("equivalent_cost_usd")
    return single | {"cost_usd": equivalent if equivalent is not None else budget.get("cost_usd")}


def _change_budgets(change: Callable[[dict], dict]) -> None:
    bind = op.get_bind()
    agent = bind.scalar(sa.select(_platform_settings.c.data).where(_platform_settings.c.key == "agent"))
    if agent is not None and "default_session_budget" in agent:
        bind.execute(
            _platform_settings.update()
            .where(_platform_settings.c.key == "agent")
            .values(data=agent | {"default_session_budget": change(agent["default_session_budget"])})
        )
    for username, config in bind.execute(sa.select(_users.c.username, _users.c.config)).all():
        if "budgets" in config:
            bind.execute(
                _users.update()
                .where(_users.c.username == username)
                .values(config=config | {"budgets": change(config["budgets"])})
            )
    for session_id, state in bind.execute(sa.select(_sessions.c.session_id, _sessions.c.state)).all():
        if state is not None and "budget" in state:
            bind.execute(
                _sessions.update()
                .where(_sessions.c.session_id == session_id)
                .values(state=state | {"budget": change(state["budget"])})
            )


def upgrade() -> None:
    _change_budgets(_to_equivalent)


def downgrade() -> None:
    _change_budgets(_to_single_cost)
