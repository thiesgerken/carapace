from __future__ import annotations

from alembic import command
from sqlalchemy import insert, select

from carapace.database.engine import _alembic_config, create_engine_and_factory
from carapace.database.models import PlatformSettingRow
from carapace.models.config import DatabaseConfig


def test_migration_carries_the_review_cap_over_to_the_new_key_and_back(tmp_path):
    engine, _ = create_engine_and_factory(DatabaseConfig(url=f"sqlite+pysqlite:///{tmp_path}/m.db"))
    cfg = _alembic_config(str(engine.url))
    stored = {"model": "anthropic:m", "max_sentinel_calls_per_tool_call": 3}
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "0016")
        conn.execute(insert(PlatformSettingRow), [{"key": "agent", "data": stored}])
        command.upgrade(cfg, "0017")
        upgraded = conn.scalar(select(PlatformSettingRow.data).where(PlatformSettingRow.key == "agent"))
        command.downgrade(cfg, "0016")
        downgraded = conn.scalar(select(PlatformSettingRow.data).where(PlatformSettingRow.key == "agent"))
    engine.dispose()

    assert upgraded == {"model": "anthropic:m", "max_sentinel_calls_per_exec": 3}
    assert downgraded == stored
