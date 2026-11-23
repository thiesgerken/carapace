"""max_sentinel_calls_per_tool_call becomes max_sentinel_calls_per_exec

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-24 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")

_platform_settings = sa.table("platform_settings", sa.column("key", sa.String), sa.column("data", _JSON))

_OLD = "max_sentinel_calls_per_tool_call"
_NEW = "max_sentinel_calls_per_exec"


def _rename(old: str, new: str) -> None:
    """Rename the stored key: the platform store only reads known keys, so the old one would be ignored."""
    bind = op.get_bind()
    agent = bind.scalar(sa.select(_platform_settings.c.data).where(_platform_settings.c.key == "agent"))
    if agent is None or old not in agent:
        return
    renamed = {(new if key == old else key): value for key, value in agent.items()}
    bind.execute(_platform_settings.update().where(_platform_settings.c.key == "agent").values(data=renamed))


def upgrade() -> None:
    """Domain reviews are capped per exec since `exec` itself is no longer reviewed."""
    _rename(_OLD, _NEW)


def downgrade() -> None:
    _rename(_NEW, _OLD)
