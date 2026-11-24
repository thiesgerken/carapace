"""the sentinel's `revise` verdict becomes `deny`

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-25 12:00:00.000000

"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")

_action_log = sa.table("session_action_log", sa.column("id", sa.BigInteger), sa.column("data", _JSON))
_events = sa.table("session_events", sa.column("id", sa.BigInteger), sa.column("data", _JSON))
_audit = sa.table("session_audit", sa.column("id", sa.BigInteger), sa.column("data", _JSON))
_spans = sa.table(
    "session_spans", sa.column("session_id", sa.String), sa.column("span_id", sa.String), sa.column("attrs", _JSON)
)
_sentinel = sa.table("session_sentinel", sa.column("session_id", sa.String), sa.column("messages", _JSON))

# The sentinel's output tool; its calls in the shadow conversation carry the verdicts.
_VERDICT_TOOL = "judge"


def _replace_json_value(table: sa.TableClause, key: str, old: str, new: str) -> None:
    bind = op.get_bind()
    rows = bind.execute(sa.select(table.c.id, table.c.data).where(table.c.data[key].as_string() == old)).all()
    for row_id, data in rows:
        bind.execute(sa.update(table).where(table.c.id == row_id).values(data=data | {key: new}))


def _rewrite_audit() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.select(_audit.c.id, _audit.c.data).where(
            sa.or_(
                _audit.c.data["final_decision"].as_string() == "changes_requested",
                _audit.c.data[("sentinel_verdict", "decision")].as_string() == "revise",
            )
        )
    ).all()
    for row_id, data in rows:
        rewritten = dict(data)
        if rewritten.get("final_decision") == "changes_requested":
            rewritten["final_decision"] = "denied"
        verdict = rewritten.get("sentinel_verdict")
        if isinstance(verdict, dict) and verdict.get("decision") == "revise":
            rewritten["sentinel_verdict"] = verdict | {"decision": "deny"}
        bind.execute(sa.update(_audit).where(_audit.c.id == row_id).values(data=rewritten))


def _rewrite_spans() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.select(_spans.c.session_id, _spans.c.span_id, _spans.c.attrs).where(
            _spans.c.attrs["verdict"].as_string() == "revise"
        )
    ).all()
    for session_id, span_id, attrs in rows:
        bind.execute(
            sa.update(_spans)
            .where(_spans.c.session_id == session_id, _spans.c.span_id == span_id)
            .values(attrs=attrs | {"verdict": "deny"})
        )


def _denied_verdict_call(part: dict[str, Any]) -> dict[str, Any]:
    """The verdict tool call with `revise` turned into `deny`; any other part as it is.

    Providers store the arguments either as an object or as the JSON text the model wrote.
    """
    if part.get("part_kind") != "tool-call" or part.get("tool_name") != _VERDICT_TOOL:
        return part
    args = part.get("args")
    if isinstance(args, str):
        parsed = json.loads(args)
        if parsed.get("decision") == "revise":
            return part | {"args": json.dumps(parsed | {"decision": "deny"})}
    elif isinstance(args, dict) and args.get("decision") == "revise":
        return part | {"args": args | {"decision": "deny"}}
    return part


def _rewrite_shadow_conversations() -> None:
    bind = op.get_bind()
    for session_id, messages in bind.execute(sa.select(_sentinel.c.session_id, _sentinel.c.messages)).all():
        if not messages:
            continue
        rewritten = [
            message | {"parts": [_denied_verdict_call(part) for part in message.get("parts", [])]}
            for message in messages
        ]
        if rewritten != messages:
            bind.execute(sa.update(_sentinel).where(_sentinel.c.session_id == session_id).values(messages=rewritten))


def upgrade() -> None:
    """A change request did not run the operation either, so every stored one becomes a denial.

    Free text keeps its wording: the action log lines the shadow conversation was shown, explanations,
    and the `detail` of session events. The LLM request logs and context snapshots keep what the
    sentinel actually answered.
    """
    _replace_json_value(_action_log, "decision", "changes_requested", "denied")
    _replace_json_value(_events, "approval_verdict", "revise", "deny")
    _rewrite_audit()
    _rewrite_spans()
    _rewrite_shadow_conversations()


def downgrade() -> None:
    """Nothing to restore: a denial is valid in the older models too."""
