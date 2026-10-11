"""long-term memory

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-10 12:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

import carapace.database.base

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")
_ID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
_OPEN_MEMORY_TASK = sa.text("status IN ('pending', 'queued', 'running')")
_IS_CURRENT = sa.text("is_current")


_platform_settings = sa.table("platform_settings", sa.column("key", sa.String), sa.column("data", _JSON))
_users = sa.table("users", sa.column("username", sa.String), sa.column("config", _JSON))


def _user_column() -> sa.Column:
    return sa.Column("user", sa.String(length=256), sa.ForeignKey("users.username", ondelete="CASCADE"), nullable=False)


def upgrade() -> None:
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.add_column(sa.Column("memory_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))

    op.create_table(
        "memory_tasks",
        sa.Column("id", _ID, autoincrement=True, nullable=False),
        _user_column(),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("target", sa.String(length=256), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("week_key", sa.String(length=16), nullable=True),
        sa.Column("month_key", sa.String(length=16), nullable=True),
        sa.Column("model", sa.String(length=256), nullable=True),
        sa.Column("blocked_reason", sa.String(length=32), nullable=True),
        sa.Column("spawned_by", sa.String(length=16), nullable=False),
        sa.Column("model_override", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("estimate", _JSON, nullable=True),
        sa.Column("provenance", _JSON, nullable=True),
        sa.Column("billed_input_tokens", sa.BigInteger(), nullable=False),
        sa.Column("billed_output_tokens", sa.BigInteger(), nullable=False),
        sa.Column("billed_cost_micro_usd", sa.BigInteger(), nullable=False),
        sa.Column("billed_at", carapace.database.base.UtcDateTime(timezone=True), nullable=True),
        sa.Column("result_id", sa.BigInteger(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", carapace.database.base.UtcDateTime(timezone=True), nullable=False),
        sa.Column("queued_at", carapace.database.base.UtcDateTime(timezone=True), nullable=True),
        sa.Column("started_at", carapace.database.base.UtcDateTime(timezone=True), nullable=True),
        sa.Column("finished_at", carapace.database.base.UtcDateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_memory_tasks_user", "memory_tasks", ["user"])
    op.create_index("ix_memory_tasks_status", "memory_tasks", ["status"])
    op.create_index("ix_memory_tasks_week_key", "memory_tasks", ["week_key"])
    op.create_index("ix_memory_tasks_month_key", "memory_tasks", ["month_key"])
    op.create_index("ix_memory_tasks_billed_at", "memory_tasks", ["billed_at"])
    op.create_index(
        "uq_memory_tasks_open",
        "memory_tasks",
        ["user", "kind", "target"],
        unique=True,
        sqlite_where=_OPEN_MEMORY_TASK,
        postgresql_where=_OPEN_MEMORY_TASK,
    )

    op.create_table(
        "memory_session_extractions",
        sa.Column("id", _ID, autoincrement=True, nullable=False),
        _user_column(),
        sa.Column("session_id", sa.String(length=256), nullable=False),
        sa.Column("week_key", sa.String(length=16), nullable=False),
        sa.Column("month_key", sa.String(length=16), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=256), nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("input_format_version", sa.Integer(), nullable=False),
        sa.Column("provenance", _JSON, nullable=False),
        sa.Column("extraction", _JSON, nullable=False),
        sa.Column("created_at", carapace.database.base.UtcDateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.session_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_memory_session_extractions_user", "memory_session_extractions", ["user"])
    op.create_index("ix_memory_session_extractions_session_id", "memory_session_extractions", ["session_id"])
    op.create_index("ix_memory_session_extractions_week_key", "memory_session_extractions", ["week_key"])
    op.create_index("ix_memory_session_extractions_month_key", "memory_session_extractions", ["month_key"])
    op.create_index(
        "uq_memory_session_extractions_current",
        "memory_session_extractions",
        ["session_id"],
        unique=True,
        sqlite_where=_IS_CURRENT,
        postgresql_where=_IS_CURRENT,
    )

    op.create_table(
        "memory_facts",
        sa.Column("id", _ID, autoincrement=True, nullable=False),
        _user_column(),
        sa.Column("extraction_id", _ID, nullable=False),
        sa.Column("session_id", sa.String(length=256), nullable=False),
        sa.Column("category", sa.String(length=16), nullable=False),
        sa.Column("subject", sa.Text(), nullable=True),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("source_kind", sa.String(length=16), nullable=False),
        sa.Column("confidence", sa.String(length=16), nullable=False),
        sa.Column("durability", sa.String(length=16), nullable=False),
        sa.Column("valid_until", sa.Date(), nullable=True),
        sa.Column("source_seqs", _JSON, nullable=False),
        sa.Column("week_key", sa.String(length=16), nullable=False),
        sa.Column("created_at", carapace.database.base.UtcDateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["extraction_id"], ["memory_session_extractions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_memory_facts_user", "memory_facts", ["user"])
    op.create_index("ix_memory_facts_extraction_id", "memory_facts", ["extraction_id"])
    op.create_index("ix_memory_facts_category", "memory_facts", ["category"])
    op.create_index("ix_memory_facts_week_key", "memory_facts", ["week_key"])

    op.create_table(
        "memory_digests",
        sa.Column("id", _ID, autoincrement=True, nullable=False),
        _user_column(),
        sa.Column("level", sa.String(length=8), nullable=False),
        sa.Column("period_key", sa.String(length=16), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("coverage", _JSON, nullable=False),
        sa.Column("coverage_hash", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=256), nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("input_format_version", sa.Integer(), nullable=False),
        sa.Column("provenance", _JSON, nullable=False),
        sa.Column("digest", _JSON, nullable=False),
        sa.Column("created_at", carapace.database.base.UtcDateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_memory_digests_period", "memory_digests", ["user", "level", "period_key"])
    op.create_index(
        "uq_memory_digests_current",
        "memory_digests",
        ["user", "level", "period_key"],
        unique=True,
        sqlite_where=_IS_CURRENT,
        postgresql_where=_IS_CURRENT,
    )

    _seed_memory_models()


def _seeded(settings: dict, sources: dict[str, str]) -> dict:
    """*settings* with each unset target copied from its source, where that source is set."""
    return settings | {
        target: settings[source]
        for target, source in sources.items()
        if settings.get(target) is None and settings.get(source) is not None
    }


def _seed_memory_models() -> None:
    """Start memory on the tiers already chosen: low on the cheap sentinel model, high on the agent model."""
    bind = op.get_bind()
    agent = bind.scalar(sa.select(_platform_settings.c.data).where(_platform_settings.c.key == "agent"))
    if agent is not None:
        seeded = _seeded(agent, {"memory_low_model": "sentinel_model", "memory_high_model": "model"})
        if seeded != agent:
            bind.execute(_platform_settings.update().where(_platform_settings.c.key == "agent").values(data=seeded))
    for username, config in bind.execute(sa.select(_users.c.username, _users.c.config)).all():
        defaults = config["default_models"]
        seeded = _seeded(defaults, {"memory_low": "sentinel", "memory_high": "agent"})
        if seeded != defaults:
            bind.execute(
                _users.update().where(_users.c.username == username).values(config=config | {"default_models": seeded})
            )


def _strip_memory_user_settings() -> None:
    """Drop the memory keys from every user config: the pre-memory ``UserConfig`` forbids unknown keys."""
    bind = op.get_bind()
    for username, config in bind.execute(sa.select(_users.c.username, _users.c.config)).all():
        stripped = {key: value for key, value in config.items() if key not in ("timezone", "memory")}
        stripped["default_models"] = {
            key: value for key, value in config["default_models"].items() if key not in ("memory_low", "memory_high")
        }
        bind.execute(_users.update().where(_users.c.username == username).values(config=stripped))


def downgrade() -> None:
    _strip_memory_user_settings()
    op.drop_table("memory_digests")
    op.drop_table("memory_facts")
    op.drop_table("memory_session_extractions")
    op.drop_table("memory_tasks")
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.drop_column("memory_enabled")
