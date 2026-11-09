"""autonomy limit

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-09 12:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")

_platform_settings = sa.table("platform_settings", sa.column("key", sa.String), sa.column("data", _JSON))
_users = sa.table("users", sa.column("username", sa.String), sa.column("config", _JSON))
_sessions = sa.table("sessions", sa.column("session_id", sa.String), sa.column("state", _JSON))

_FIELD = "autonomous_tool_calls"
# Frozen copy of the platform default in AgentConfig.default_session_budget.
_DEFAULT_LIMIT = 100


def _stored_agent_settings() -> dict | None:
    return op.get_bind().scalar(sa.select(_platform_settings.c.data).where(_platform_settings.c.key == "agent"))


def _save_agent_settings(agent: dict) -> None:
    op.get_bind().execute(_platform_settings.update().where(_platform_settings.c.key == "agent").values(data=agent))


def upgrade() -> None:
    """Give existing installs the default autonomy limit wherever a stored budget would otherwise mask it."""
    agent = _stored_agent_settings()
    if agent is not None and "default_session_budget" in agent:
        budget = agent["default_session_budget"]
        if _FIELD not in budget:
            _save_agent_settings(agent | {"default_session_budget": budget | {_FIELD: _DEFAULT_LIMIT}})
    # A user default budget with any limit replaces the platform default wholesale; an empty one falls back to it.
    bind = op.get_bind()
    for username, config in bind.execute(sa.select(_users.c.username, _users.c.config)).all():
        budgets = config.get("budgets", {})
        if _FIELD not in budgets and any(value is not None for value in budgets.values()):
            bind.execute(
                _users.update()
                .where(_users.c.username == username)
                .values(config=config | {"budgets": budgets | {_FIELD: _DEFAULT_LIMIT}})
            )


def downgrade() -> None:
    """Drop the field everywhere: the older ``SessionBudget`` forbids unknown keys."""
    bind = op.get_bind()
    agent = _stored_agent_settings()
    if agent is not None and "default_session_budget" in agent:
        budget = {key: value for key, value in agent["default_session_budget"].items() if key != _FIELD}
        _save_agent_settings(agent | {"default_session_budget": budget})
    for username, config in bind.execute(sa.select(_users.c.username, _users.c.config)).all():
        if _FIELD in config.get("budgets", {}):
            budgets = {key: value for key, value in config["budgets"].items() if key != _FIELD}
            bind.execute(
                _users.update().where(_users.c.username == username).values(config=config | {"budgets": budgets})
            )
    for session_id, state in bind.execute(sa.select(_sessions.c.session_id, _sessions.c.state)).all():
        if state is not None and _FIELD in state.get("budget", {}):
            budget = {key: value for key, value in state["budget"].items() if key != _FIELD}
            bind.execute(
                _sessions.update().where(_sessions.c.session_id == session_id).values(state=state | {"budget": budget})
            )
