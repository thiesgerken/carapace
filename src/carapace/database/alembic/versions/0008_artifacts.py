"""artifact sharing

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-22 19:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import carapace.database.base

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "artifacts",
        sa.Column("owner", sa.String(length=256), nullable=False),
        sa.Column("slug", sa.String(length=256), nullable=False),
        sa.Column("share_token", sa.String(length=256), nullable=True),
        sa.Column("shared_at", carapace.database.base.UtcDateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["owner"], ["users.username"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("owner", "slug"),
        sa.UniqueConstraint("share_token", name="uq_artifacts_share_token"),
    )


def downgrade() -> None:
    op.drop_table("artifacts")
