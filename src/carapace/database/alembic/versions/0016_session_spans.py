"""timing spans of finished turns

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-16 12:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

import carapace.database.base

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "session_spans",
        sa.Column("session_id", sa.String(length=256), nullable=False),
        sa.Column("span_id", sa.String(length=32), nullable=False),
        sa.Column("turn_id", sa.String(length=32), nullable=False),
        sa.Column("parent_id", sa.String(length=32), nullable=True),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("started_at", carapace.database.base.UtcDateTime(timezone=True), nullable=False),
        sa.Column("ended_at", carapace.database.base.UtcDateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "attrs", sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"), nullable=False
        ),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.session_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("session_id", "span_id"),
    )
    op.create_index("ix_session_spans_session_turn", "session_spans", ["session_id", "turn_id"])


def downgrade() -> None:
    op.drop_index("ix_session_spans_session_turn", table_name="session_spans")
    op.drop_table("session_spans")
