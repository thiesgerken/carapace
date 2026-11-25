"""skill activations and context grants leave the session state and the action log

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-24 12:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")

_sessions = sa.table("sessions", sa.column("session_id", sa.String), sa.column("state", _JSON))
_action_log = sa.table(
    "session_action_log",
    sa.column("id", sa.BigInteger),
    sa.column("session_id", sa.String),
    sa.column("seq", sa.Integer),
    sa.column("data", _JSON),
)
_sentinel = sa.table("session_sentinel", sa.column("session_id", sa.String), sa.column("synced_entries", sa.Integer))

_DROPPED_STATE = ("activated_skills", "context_grants")
_DROPPED_ENTRIES = ("skill_activated", "context_grant")


def _drop_entries(bind: sa.Connection, session_id: str) -> None:
    """Remove a session's activation and grant entries and close the gaps they leave.

    `synced_entries` counts the leading entries the shadow conversation was told about, so it
    shrinks by the removed entries among them.
    """
    rows = bind.execute(
        sa.select(_action_log.c.id, _action_log.c.seq, _action_log.c.data["type"].as_string())
        .where(_action_log.c.session_id == session_id)
        .order_by(_action_log.c.seq)
    ).all()
    dropped = [(row_id, seq) for row_id, seq, entry_type in rows if entry_type in _DROPPED_ENTRIES]
    kept = [(row_id, seq) for row_id, seq, entry_type in rows if entry_type not in _DROPPED_ENTRIES]
    bind.execute(sa.delete(_action_log).where(_action_log.c.id.in_([row_id for row_id, _seq in dropped])))
    # Ascending order keeps (session_id, seq) unique: every target seq is already vacated.
    for new_seq, (row_id, seq) in enumerate(kept):
        if seq != new_seq:
            bind.execute(sa.update(_action_log).where(_action_log.c.id == row_id).values(seq=new_seq))

    synced = bind.scalar(sa.select(_sentinel.c.synced_entries).where(_sentinel.c.session_id == session_id))
    if synced is not None:
        removed_synced = sum(1 for _row_id, seq in dropped if seq < synced)
        bind.execute(
            sa.update(_sentinel)
            .where(_sentinel.c.session_id == session_id)
            .values(synced_entries=synced - removed_synced)
        )


def upgrade() -> None:
    """Skills are read, not activated, and grant nothing (#574): there is no activation left to remember.

    The shadow conversations keep what they were told about past activations and grants.
    """
    bind = op.get_bind()
    for session_id, state in bind.execute(sa.select(_sessions.c.session_id, _sessions.c.state)).all():
        if state is not None and any(key in state for key in _DROPPED_STATE):
            kept = {key: value for key, value in state.items() if key not in _DROPPED_STATE}
            bind.execute(_sessions.update().where(_sessions.c.session_id == session_id).values(state=kept))
    session_ids = bind.scalars(
        sa.select(_action_log.c.session_id)
        .where(_action_log.c.data["type"].as_string().in_(_DROPPED_ENTRIES))
        .distinct()
    ).all()
    for session_id in session_ids:
        _drop_entries(bind, session_id)


def downgrade() -> None:
    """Nothing to restore: the older models default both session fields to empty."""
