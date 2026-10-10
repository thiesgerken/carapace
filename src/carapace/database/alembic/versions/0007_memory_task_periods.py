"""memory task periods and model

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-10 21:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("memory_tasks") as batch_op:
        batch_op.add_column(sa.Column("week_key", sa.String(length=16), nullable=True))
        batch_op.add_column(sa.Column("month_key", sa.String(length=16), nullable=True))
        batch_op.add_column(sa.Column("model", sa.String(length=256), nullable=True))
        batch_op.create_index("ix_memory_tasks_week_key", ["week_key"])
        batch_op.create_index("ix_memory_tasks_month_key", ["month_key"])


def downgrade() -> None:
    with op.batch_alter_table("memory_tasks") as batch_op:
        batch_op.drop_index("ix_memory_tasks_month_key")
        batch_op.drop_index("ix_memory_tasks_week_key")
        batch_op.drop_column("model")
        batch_op.drop_column("month_key")
        batch_op.drop_column("week_key")
