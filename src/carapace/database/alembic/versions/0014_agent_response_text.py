"""action log agent responses carry their text; sentinel verdicts can request changes

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-12 20:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")

_action_log = sa.table(
    "session_action_log",
    sa.column("id", sa.BigInteger),
    sa.column("session_id", sa.String),
    sa.column("seq", sa.Integer),
    sa.column("data", _JSON),
)
_sentinel = sa.table("session_sentinel", sa.column("session_id", sa.String), sa.column("synced_entries", sa.Integer))
_events = sa.table("session_events", sa.column("id", sa.BigInteger), sa.column("data", _JSON))


def _drop_legacy_agent_responses(bind: sa.Connection, session_id: str) -> None:
    """Remove a session's agent responses and close the gaps they leave in the action log.

    `synced_entries` counts the leading entries the shadow conversation was told about, so it
    shrinks by the removed entries among them.
    """
    rows = bind.execute(
        sa.select(_action_log.c.id, _action_log.c.seq, _action_log.c.data["type"].as_string())
        .where(_action_log.c.session_id == session_id)
        .order_by(_action_log.c.seq)
    ).all()
    legacy = [(row_id, seq) for row_id, seq, entry_type in rows if entry_type == "agent_response"]
    kept = [(row_id, seq) for row_id, seq, entry_type in rows if entry_type != "agent_response"]
    bind.execute(sa.delete(_action_log).where(_action_log.c.id.in_([row_id for row_id, _seq in legacy])))
    # Ascending order keeps (session_id, seq) unique: every target seq is already vacated.
    for new_seq, (row_id, seq) in enumerate(kept):
        if seq != new_seq:
            bind.execute(sa.update(_action_log).where(_action_log.c.id == row_id).values(seq=new_seq))

    synced = bind.scalar(sa.select(_sentinel.c.synced_entries).where(_sentinel.c.session_id == session_id))
    if synced is not None:
        removed_synced = sum(1 for _row_id, seq in legacy if seq < synced)
        bind.execute(
            sa.update(_sentinel)
            .where(_sentinel.c.session_id == session_id)
            .values(synced_entries=synced - removed_synced)
        )


def upgrade() -> None:
    """Agent responses recorded only a token count before; now they carry the text the user saw.

    The text cannot be recovered reliably (rewinds and compaction break the mapping to the transcript),
    and shadow conversations already contain these entries as they were rendered. So the old entries
    go instead of getting an invented text.
    """
    bind = op.get_bind()
    session_ids = bind.scalars(
        sa.select(_action_log.c.session_id).where(_action_log.c.data["type"].as_string() == "agent_response").distinct()
    ).all()
    for session_id in session_ids:
        _drop_legacy_agent_responses(bind, session_id)


def _replace_json_value(table: sa.TableClause, key: str, old: str, new: str) -> None:
    bind = op.get_bind()
    rows = bind.execute(sa.select(table.c.id, table.c.data).where(table.c.data[key].as_string() == old)).all()
    for row_id, data in rows:
        bind.execute(sa.update(table).where(table.c.id == row_id).values(data=data | {key: new}))


def downgrade() -> None:
    """A change request did not run the operation, which the old decisions can only call a denial.

    Agent responses keep their text, which the old model ignores.
    """
    _replace_json_value(_action_log, "decision", "changes_requested", "denied")
    _replace_json_value(_events, "approval_verdict", "revise", "deny")
