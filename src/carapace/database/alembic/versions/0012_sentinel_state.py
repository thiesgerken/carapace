"""persisted sentinel state: shadow conversation and action log

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-09 20:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "session_sentinel",
        sa.Column("session_id", sa.String(length=256), nullable=False),
        sa.Column("messages", _JSON, nullable=False),
        sa.Column("synced_entries", sa.Integer(), nullable=False),
        sa.Column("eval_count", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.session_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("session_id"),
    )
    op.create_table(
        "session_action_log",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.String(length=256), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("data", _JSON, nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.session_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "seq", name="uq_session_action_log_seq"),
    )


def downgrade() -> None:
    op.drop_table("session_action_log")
    op.drop_table("session_sentinel")
