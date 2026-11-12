"""per-model compaction threshold replaces sentinel_threshold_pct

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-12 12:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")

_platform_settings = sa.table("platform_settings", sa.column("key", sa.String), sa.column("data", _JSON))
_models = sa.table("models", sa.column("id", sa.String), sa.column("data", _JSON))

_DROPPED_FIELD = "sentinel_threshold_pct"
_ADDED_FIELD = "compaction_threshold_tokens"


def upgrade() -> None:
    """Drop the stored key: ``CompactionConfig`` forbids unknown keys, so it would break startup.

    The sentinel now compacts at its model's compaction threshold, so there is nothing to carry over.
    """
    bind = op.get_bind()
    agent = bind.scalar(sa.select(_platform_settings.c.data).where(_platform_settings.c.key == "agent"))
    if agent is None or _DROPPED_FIELD not in agent.get("compaction", {}):
        return
    compaction = {key: value for key, value in agent["compaction"].items() if key != _DROPPED_FIELD}
    bind.execute(
        _platform_settings.update()
        .where(_platform_settings.c.key == "agent")
        .values(data=agent | {"compaction": compaction})
    )


def downgrade() -> None:
    """Drop the per-model thresholds: the older ``AvailableModelEntry`` forbids unknown keys.

    The older ``CompactionConfig`` defaults the missing ``sentinel_threshold_pct`` on its own.
    """
    bind = op.get_bind()
    for model_id, data in bind.execute(sa.select(_models.c.id, _models.c.data)).all():
        if _ADDED_FIELD in data:
            stripped = {key: value for key, value in data.items() if key != _ADDED_FIELD}
            bind.execute(_models.update().where(_models.c.id == model_id).values(data=stripped))
