"""user codex credentials

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-03 12:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import carapace.database.base

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_codex_credentials",
        sa.Column("user", sa.String(length=256), nullable=False),
        sa.Column("access_token", sa.Text(), nullable=False),
        sa.Column("refresh_token", sa.Text(), nullable=False),
        sa.Column("account_id", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("updated_at", carapace.database.base.UtcDateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user"], ["users.username"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user"),
    )


def downgrade() -> None:
    op.drop_table("user_codex_credentials")
