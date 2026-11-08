from __future__ import annotations

from datetime import UTC, datetime

from alembic import command
from sqlalchemy import JSON, String, column, insert, select, table

from carapace.database.engine import _alembic_config, create_engine_and_factory
from carapace.database.models import PlatformSettingRow, SessionRow, User
from carapace.models.config import DatabaseConfig
from carapace.models.session import SessionBudget, SessionState
from carapace.models.user import UserConfig

_raw_users = table("users", column("username", String), column("config", JSON))
_raw_sessions = table("sessions", column("session_id", String), column("state", JSON))
_PRE_AUTONOMY_BUDGET = {"input_tokens": None, "output_tokens": None, "cost_usd": "2.50", "tool_calls": None}


def test_migration_gives_installs_the_default_autonomy_limit_and_strips_it_on_downgrade(tmp_path):
    engine, _ = create_engine_and_factory(DatabaseConfig(url=f"sqlite+pysqlite:///{tmp_path}/m.db"))
    cfg = _alembic_config(str(engine.url))
    now = datetime.now(tz=UTC)
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "0008")
        conn.execute(
            insert(PlatformSettingRow),
            [{"key": "agent", "data": {"model": "m:agent", "default_session_budget": _PRE_AUTONOMY_BUDGET}}],
        )
        command.upgrade(cfg, "head")
        agent = conn.scalar(select(PlatformSettingRow.data).where(PlatformSettingRow.key == "agent"))

        conn.execute(
            insert(User),
            [
                {
                    "username": "thies",
                    "password_hash": "x",
                    "config": UserConfig(budgets=SessionBudget(autonomous_tool_calls=20)),
                    "created_at": now,
                    "updated_at": now,
                    "password_changed_at": now,
                }
            ],
        )
        state = SessionState.now(session_id="s1")
        state.budget = SessionBudget(tool_calls=5, autonomous_tool_calls=20)
        conn.execute(
            insert(SessionRow),
            [
                {
                    "session_id": "s1",
                    "user": "thies",
                    "channel_type": "web",
                    "created_at": now,
                    "last_active": now,
                    "state": state,
                }
            ],
        )
        command.downgrade(cfg, "0008")
        downgraded_agent = conn.scalar(select(PlatformSettingRow.data).where(PlatformSettingRow.key == "agent"))
        user_config = conn.scalar(select(_raw_users.c.config))
        session_state = conn.scalar(select(_raw_sessions.c.state))
    engine.dispose()

    assert agent["default_session_budget"] == _PRE_AUTONOMY_BUDGET | {"autonomous_tool_calls": 100}
    assert downgraded_agent["default_session_budget"] == _PRE_AUTONOMY_BUDGET
    assert "autonomous_tool_calls" not in user_config["budgets"]
    assert session_state["budget"] == {"input_tokens": None, "output_tokens": None, "cost_usd": None, "tool_calls": 5}
