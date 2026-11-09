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
_EMPTY = {"input_tokens": None, "output_tokens": None, "tool_calls": None, "autonomous_tool_calls": None}


def _without_equivalent(budget: dict) -> dict:
    """A budget as stored before 0010: the current models also write the new field."""
    return {key: value for key, value in budget.items() if key != "equivalent_cost_usd"}


def _insert_user(conn: Connection, username: str, budget: SessionBudget, now: datetime) -> None:
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
    config = conn.scalar(select(_raw_users.c.config).where(_raw_users.c.username == username))
    conn.execute(
        update(_raw_users)
        .where(_raw_users.c.username == username)
        .values(config=config | {"budgets": _without_equivalent(config["budgets"])})
    )


def _insert_session(conn: Connection, session_id: str, budget: SessionBudget, now: datetime) -> None:
    state = SessionState.now(session_id=session_id)
    state.budget = budget
    row = {"session_id": session_id, "user": "u", "channel_type": "web", "created_at": now, "last_active": now}
    conn.execute(insert(SessionRow), [row | {"state": state}])
    stored = conn.scalar(select(_raw_sessions.c.state).where(_raw_sessions.c.session_id == session_id))
    conn.execute(
        update(_raw_sessions)
        .where(_raw_sessions.c.session_id == session_id)
        .values(state=stored | {"budget": _without_equivalent(stored["budget"])})
    )


def _budgets(conn: Connection) -> dict[str, dict]:
    agent = conn.scalar(select(PlatformSettingRow.data).where(PlatformSettingRow.key == "agent"))
    users = {
        name: config["budgets"] for name, config in conn.execute(select(_raw_users.c.username, _raw_users.c.config))
    }
    sessions = {
        sid: state["budget"] for sid, state in conn.execute(select(_raw_sessions.c.session_id, _raw_sessions.c.state))
    }
    return {"platform": agent["default_session_budget"], **users, **sessions}


def test_migration_turns_every_cost_limit_into_an_equivalent_cost_limit_and_back(tmp_path):
    engine, _ = create_engine_and_factory(DatabaseConfig(url=f"sqlite+pysqlite:///{tmp_path}/m.db"))
    cfg = _alembic_config(str(engine.url))
    now = datetime.now(tz=UTC)
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "0009")
        platform_budget = _EMPTY | {"cost_usd": "5.00"}
        conn.execute(
            insert(PlatformSettingRow),
            [{"key": "agent", "data": {"model": "m:agent", "default_session_budget": platform_budget}}],
        )
        _insert_user(conn, "u", SessionBudget(cost_usd=Decimal("2.50")), now)
        _insert_session(conn, "limited", SessionBudget(cost_usd=Decimal("1.00")), now)
        _insert_session(conn, "unlimited", SessionBudget(), now)

        command.upgrade(cfg, "0010")
        upgraded = _budgets(conn)
        # Set after the split: a real-money cap well below the list-price one.
        both = _EMPTY | {"cost_usd": "1.00", "equivalent_cost_usd": "20.00"}
        state = conn.scalar(select(_raw_sessions.c.state).where(_raw_sessions.c.session_id == "unlimited"))
        conn.execute(
            update(_raw_sessions)
            .where(_raw_sessions.c.session_id == "unlimited")
            .values(state=state | {"budget": both})
        )
        command.downgrade(cfg, "0009")
        downgraded = _budgets(conn)
    engine.dispose()

    # Blocking stays as before: the old cost limit priced subscription usage at list price too.
    assert upgraded == {
        "platform": _EMPTY | {"cost_usd": None, "equivalent_cost_usd": "5.00"},
        "u": _EMPTY | {"cost_usd": None, "equivalent_cost_usd": "2.50"},
        "limited": _EMPTY | {"cost_usd": None, "equivalent_cost_usd": "1.00"},
        "unlimited": _EMPTY | {"cost_usd": None},
    }
    assert downgraded == {
        "platform": _EMPTY | {"cost_usd": "5.00"},
        "u": _EMPTY | {"cost_usd": "2.50"},
        "limited": _EMPTY | {"cost_usd": "1.00"},
        # The old single limit priced everything, so the stricter of the two caps survives.
        "unlimited": _EMPTY | {"cost_usd": "1.00"},
    }
