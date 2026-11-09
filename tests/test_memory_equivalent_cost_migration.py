from __future__ import annotations

from datetime import UTC, datetime

from alembic import command
from sqlalchemy import JSON, BigInteger, Connection, String, column, insert, select, table

from carapace.database.engine import _alembic_config, create_engine_and_factory
from carapace.database.models import MemoryDigestRow, MemoryTaskRow, User
from carapace.models.config import DatabaseConfig
from carapace.models.user import UserConfig

_NOW = datetime(2026, 11, 9, 12, tzinfo=UTC)
_raw_users = table("users", column("username", String), column("config", JSON))
_raw_tasks = table("memory_tasks", column("id", BigInteger), column("estimate", JSON), column("provenance", JSON))
_raw_digests = table("memory_digests", column("id", BigInteger), column("provenance", JSON))
_TOKENS = {"input_tokens_per_day": None, "input_tokens_per_month": 50000}
_ESTIMATE = {"model": "openai-codex:gpt-5.5", "input_tokens": 1000, "output_tokens_cap": 100}
_PROVENANCE = {
    "carapace_version": "0.172.0",
    "model": "openai-codex:gpt-5.5",
    "prompt_version": "p1",
    "input_format_version": 1,
    "input_hash": "h",
    "input_tokens": 1000,
    "output_tokens": 80,
    "duration_ms": 10,
    "task_id": 1,
    "created_at": "2026-11-09T12:00:00Z",
}


def _insert_user(conn: Connection, username: str, config: dict) -> None:
    row = {"username": username, "password_hash": "x", "config": UserConfig(), "created_at": _NOW, "updated_at": _NOW}
    conn.execute(insert(User), [row | {"password_changed_at": _NOW}])
    conn.execute(_raw_users.update().where(_raw_users.c.username == username).values(config=config))


def _insert_priced_records(conn: Connection) -> None:
    task = {"user": "limited", "kind": "session_extract", "target": "s1", "spawned_by": "auto", "created_at": _NOW}
    conn.execute(insert(MemoryTaskRow), [task | {"status": "done"}, task | {"target": "s2", "status": "pending"}])
    conn.execute(
        _raw_tasks.update()
        .where(_raw_tasks.c.id == 1)
        .values(estimate=_ESTIMATE | {"cost_usd": "0.01"}, provenance=_PROVENANCE | {"cost_usd": "0.0123"})
    )
    digest = {"user": "limited", "level": "week", "period_key": "2026-W45", "is_current": True, "coverage": []}
    meta = {"coverage_hash": "c", "model": "m:x", "prompt_version": "p1", "input_format_version": 1}
    row = digest | meta | {"provenance": _PROVENANCE | {"cost_usd": None}, "digest": {}, "created_at": _NOW}
    # Raw JSON for the Pydantic-typed columns, so the payload goes in exactly as written above.
    raw_json = {"provenance", "digest"}
    types = MemoryDigestRow.__table__.c
    columns = (column(name, JSON if name in raw_json else types[name].type) for name in row)
    conn.execute(insert(table("memory_digests", *columns)), [row])


def _state(conn: Connection) -> dict:
    budgets = {
        name: config.get("memory", {}).get("budget")
        for name, config in conn.execute(select(_raw_users.c.username, _raw_users.c.config))
    }
    tasks = [(e, p) for _, e, p in conn.execute(select(_raw_tasks).order_by(_raw_tasks.c.id))]
    digests = [p for _, p in conn.execute(select(_raw_digests))]
    return {"budgets": budgets, "tasks": tasks, "digests": digests}


def test_migration_moves_memory_cost_limits_and_prices_to_equivalent_cost_and_back(tmp_path):
    engine, _ = create_engine_and_factory(DatabaseConfig(url=f"sqlite+pysqlite:///{tmp_path}/m.db"))
    cfg = _alembic_config(str(engine.url))
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "0010")
        _insert_user(conn, "limited", {"memory": {"budget": {"cost_usd_per_day": "2.00", **_TOKENS}}})
        # An explicit null switches the limit off and must stay off.
        unlimited = {"cost_usd_per_day": None, "cost_usd_per_month": None, **_TOKENS}
        _insert_user(conn, "unlimited", {"memory": {"budget": unlimited}})
        _insert_user(conn, "defaults", {"timezone": "UTC"})
        _insert_priced_records(conn)

        command.upgrade(cfg, "0011")
        upgraded = _state(conn)
        # Set after the split: a real-money cap below the list-price one.
        both = {"cost_usd_per_day": "0.50", "equivalent_cost_usd_per_day": "3.00", **_TOKENS}
        conn.execute(
            _raw_users.update().where(_raw_users.c.username == "limited").values(config={"memory": {"budget": both}})
        )
        command.downgrade(cfg, "0010")
        downgraded = _state(conn)
    engine.dispose()

    assert upgraded["budgets"] == {
        "limited": {"cost_usd_per_day": None, "equivalent_cost_usd_per_day": "2.00", **_TOKENS},
        "unlimited": unlimited | {"equivalent_cost_usd_per_day": None, "equivalent_cost_usd_per_month": None},
        "defaults": None,
    }
    assert upgraded["tasks"] == [
        (_ESTIMATE | {"equivalent_cost_usd": "0.01"}, _PROVENANCE | {"equivalent_cost_usd": "0.0123"}),
        (None, None),
    ]
    assert upgraded["digests"] == [_PROVENANCE | {"equivalent_cost_usd": None}]

    assert downgraded["budgets"] == {
        # The old single limit priced everything, so the stricter of the two caps survives.
        "limited": {"cost_usd_per_day": "0.50", **_TOKENS},
        "unlimited": unlimited,
        "defaults": None,
    }
    assert downgraded["tasks"] == [
        (_ESTIMATE | {"cost_usd": "0.01"}, _PROVENANCE | {"cost_usd": "0.0123"}),
        (None, None),
    ]
    assert downgraded["digests"] == [_PROVENANCE | {"cost_usd": None}]
