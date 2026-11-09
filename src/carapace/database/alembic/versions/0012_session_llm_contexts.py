"""latest LLM context per session and agent role

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


def upgrade() -> None:
    op.create_table(
        "session_llm_contexts",
        sa.Column("session_id", sa.String(length=256), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column(
            "context", sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"), nullable=False
        ),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.session_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("session_id", "role"),
    )


def downgrade() -> None:
    op.drop_table("session_llm_contexts")
