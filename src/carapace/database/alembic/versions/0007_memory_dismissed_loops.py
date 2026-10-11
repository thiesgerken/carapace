"""memory dismissed loops

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-11 18:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import carapace.database.base

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "memory_dismissed_loops",
        sa.Column("user", sa.String(length=256), nullable=False),
        sa.Column("loop_id", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=256), nullable=False),
        sa.Column("dismissed_at", carapace.database.base.UtcDateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user"], ["users.username"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.session_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user", "loop_id"),
    )
    op.create_index("ix_memory_dismissed_loops_session_id", "memory_dismissed_loops", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_memory_dismissed_loops_session_id", table_name="memory_dismissed_loops")
    op.drop_table("memory_dismissed_loops")
