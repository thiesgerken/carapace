from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from alembic import command
from sqlalchemy import JSON, Connection, String, column, insert, select, table, update

from carapace.database.engine import _alembic_config, create_engine_and_factory
from carapace.database.models import PlatformSettingRow, SessionRow, User
from carapace.models.config import DatabaseConfig
from carapace.models.session import SessionBudget, SessionState
from carapace.models.user import UserConfig

_raw_users = table("users", column("username", String), column("config", JSON))
_raw_sessions = table("sessions", column("session_id", String), column("state", JSON))
_FIELD = "autonomous_tool_calls"
# Budget keys a row written by the current models has, but a row from before 0009 doesn't.
_NEWER_BUDGET_KEYS = {_FIELD, "equivalent_cost_usd"}
_PRE_AUTONOMY_BUDGET = {"input_tokens": None, "output_tokens": None, "cost_usd": "2.50", "tool_calls": None}
_PRE_AUTONOMY_EMPTY_BUDGET = {"input_tokens": None, "output_tokens": None, "cost_usd": None, "tool_calls": None}


def _insert_pre_autonomy_user(conn: Connection, username: str, budget: SessionBudget, now: datetime) -> None:
    conn.execute(
        insert(User),
        [
            {
                "username": username,
                "password_hash": "x",
                "config": UserConfig(budgets=budget),
                "created_at": now,
                "updated_at": now,
                "password_changed_at": now,
            }
        ],
    )
    # The current model writes the new fields; rows from before 0009 don't have them.
    config = conn.scalar(select(_raw_users.c.config).where(_raw_users.c.username == username))
    budgets = {key: value for key, value in config["budgets"].items() if key not in _NEWER_BUDGET_KEYS}
    conn.execute(
        update(_raw_users).where(_raw_users.c.username == username).values(config=config | {"budgets": budgets})
    )


def _user_budgets(conn: Connection) -> dict[str, dict]:
    return {
        name: config["budgets"] for name, config in conn.execute(select(_raw_users.c.username, _raw_users.c.config))
    }


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
        _insert_pre_autonomy_user(conn, "own_budget", SessionBudget(cost_usd=Decimal("2.50")), now)
        _insert_pre_autonomy_user(conn, "platform_budget", SessionBudget(), now)
        command.upgrade(cfg, "0009")
        agent = conn.scalar(select(PlatformSettingRow.data).where(PlatformSettingRow.key == "agent"))
        upgraded_budgets = _user_budgets(conn)

        state = SessionState.now(session_id="s1")
        state.budget = SessionBudget(tool_calls=5, autonomous_tool_calls=20)
        conn.execute(
            insert(SessionRow),
            [
                {
                    "session_id": "s1",
                    "user": "own_budget",
                    "channel_type": "web",
                    "created_at": now,
                    "last_active": now,
                    "state": state,
                }
            ],
        )
        # Like the users above: a session from 0009 has no keys of later revisions.
        stored = conn.scalar(select(_raw_sessions.c.state))
        budget = {key: value for key, value in stored["budget"].items() if key != "equivalent_cost_usd"}
        conn.execute(update(_raw_sessions).values(state=stored | {"budget": budget}))
        command.downgrade(cfg, "0008")
        downgraded_agent = conn.scalar(select(PlatformSettingRow.data).where(PlatformSettingRow.key == "agent"))
        downgraded_budgets = _user_budgets(conn)
        session_state = conn.scalar(select(_raw_sessions.c.state))
    engine.dispose()

    assert agent["default_session_budget"] == _PRE_AUTONOMY_BUDGET | {_FIELD: 100}
    # Only a user budget with a limit masks the platform default; an empty one still falls back to it.
    assert upgraded_budgets == {
        "own_budget": _PRE_AUTONOMY_BUDGET | {_FIELD: 100},
        "platform_budget": _PRE_AUTONOMY_EMPTY_BUDGET,
    }
    assert downgraded_agent["default_session_budget"] == _PRE_AUTONOMY_BUDGET
    assert downgraded_budgets == {"own_budget": _PRE_AUTONOMY_BUDGET, "platform_budget": _PRE_AUTONOMY_EMPTY_BUDGET}
    assert session_state["budget"] == _PRE_AUTONOMY_EMPTY_BUDGET | {"tool_calls": 5}
