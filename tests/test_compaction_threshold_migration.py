from __future__ import annotations

from alembic import command
from sqlalchemy import JSON, String, column, insert, select, table

from carapace.database.engine import _alembic_config, create_engine_and_factory
from carapace.database.models import PlatformSettingRow
from carapace.models.config import DatabaseConfig

_raw_models = table(
    "models", column("id", String), column("provider", String), column("name", String), column("data", JSON)
)
_COMPACTION = {"keep_turns": 8, "verbatim_tool_turns": 4, "tool_output_floor_tokens": 500}
_MODEL = {"provider": "anthropic", "name": "m"}


def test_migration_drops_sentinel_threshold_pct_and_strips_model_thresholds_on_downgrade(tmp_path):
    engine, _ = create_engine_and_factory(DatabaseConfig(url=f"sqlite+pysqlite:///{tmp_path}/m.db"))
    cfg = _alembic_config(str(engine.url))
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "0014")
        conn.execute(
            insert(PlatformSettingRow),
            [
                {
                    "key": "agent",
                    "data": {"model": "anthropic:m", "compaction": _COMPACTION | {"sentinel_threshold_pct": 70}},
                }
            ],
        )
        command.upgrade(cfg, "0015")
        upgraded = conn.scalar(select(PlatformSettingRow.data).where(PlatformSettingRow.key == "agent"))

        conn.execute(
            insert(_raw_models),
            [{"id": "anthropic:m", **_MODEL, "data": _MODEL | {"compaction_threshold_tokens": 90_000}}],
        )
        command.downgrade(cfg, "0014")
        downgraded_model = conn.scalar(select(_raw_models.c.data))
    engine.dispose()

    assert upgraded["compaction"] == _COMPACTION
    assert downgraded_model == _MODEL
