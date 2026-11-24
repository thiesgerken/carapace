from __future__ import annotations

import json
from datetime import UTC, datetime

from alembic import command
from pydantic_ai.messages import ModelMessagesTypeAdapter, ModelRequest, ModelResponse, ToolCallPart, UserPromptPart
from sqlalchemy import JSON, Connection, String, column, insert, select, table

from carapace.database.engine import _alembic_config, create_engine_and_factory
from carapace.database.models import (
    SessionActionLogRow,
    SessionAuditRow,
    SessionEventRow,
    SessionRow,
    SessionSpanRow,
)
from carapace.models.config import DatabaseConfig
from carapace.models.session import SessionState
from carapace.security.context import SessionSecurity

# Raw tables: the current models no longer accept what a session from before 0019 stored.
_raw_sentinel = table(
    "session_sentinel",
    column("session_id", String),
    column("messages", JSON),
    column("synced_entries"),
    column("eval_count"),
)
_raw_action_log = table("session_action_log", column("session_id", String), column("seq"), column("data", JSON))
_raw_events = table("session_events", column("session_id", String), column("seq"), column("data", JSON))
_raw_audit = table("session_audit", column("session_id", String), column("timestamp"), column("data", JSON))

_NOW = datetime(2026, 11, 20, tzinfo=UTC)
_PUSH = {"type": "git_push", "ref": "refs/heads/main", "decision": "changes_requested", "explanation": "split it"}
_ALLOWED_PUSH = _PUSH | {"decision": "allowed", "explanation": "fine"}
_EVENT = {
    "role": "tool_call",
    "tool": "git_push",
    "args": {"ref": "refs/heads/main"},
    "detail": "[sentinel: revise] split it",
}
_VERDICT = {"decision": "revise", "explanation": "split it", "risk_level": "low", "comment": ""}
_AUDIT = {"timestamp": _NOW.isoformat(), "kind": "git_push", "args_summary": {}, "sentinel_verdict": _VERDICT}


def _shadow_conversation() -> list[dict]:
    """Two evaluations: one provider stored the verdict arguments as an object, the other as JSON text."""
    messages = [
        ModelRequest(parts=[UserPromptPart(content="git push evaluation #1")]),
        ModelResponse(parts=[ToolCallPart(tool_name="judge", args=dict(_VERDICT), tool_call_id="a")]),
        ModelRequest(parts=[UserPromptPart(content="git push evaluation #2")]),
        ModelResponse(parts=[ToolCallPart(tool_name="judge", args=json.dumps(_VERDICT), tool_call_id="b")]),
        ModelResponse(parts=[ToolCallPart(tool_name="read_skill_file", args={"decision": "revise"}, tool_call_id="c")]),
    ]
    return ModelMessagesTypeAdapter.dump_python(messages, mode="json")


def _insert_pre_0019_session(conn: Connection, session_id: str) -> None:
    row = {"session_id": session_id, "user": "thies", "channel_type": "web", "created_at": _NOW, "last_active": _NOW}
    conn.execute(insert(SessionRow), [row | {"state": SessionState.now(session_id=session_id)}])
    conn.execute(
        insert(_raw_action_log),
        [
            {"session_id": session_id, "seq": 0, "data": _PUSH},
            {"session_id": session_id, "seq": 1, "data": _ALLOWED_PUSH},
        ],
    )
    conn.execute(
        insert(_raw_events),
        [
            {
                "session_id": session_id,
                "seq": 0,
                "data": _EVENT | {"approval_source": "sentinel", "approval_verdict": "revise"},
            },
            {
                "session_id": session_id,
                "seq": 1,
                "data": _EVENT | {"approval_source": "sentinel", "approval_verdict": "allow"},
            },
        ],
    )
    conn.execute(
        insert(_raw_audit),
        [{"session_id": session_id, "timestamp": _NOW, "data": _AUDIT | {"final_decision": "changes_requested"}}],
    )
    conn.execute(
        insert(SessionSpanRow),
        [
            {
                "session_id": session_id,
                "span_id": span_id,
                "turn_id": "t1",
                "parent_id": None,
                "kind": "sentinel",
                "name": "git push",
                "started_at": _NOW,
                "ended_at": _NOW,
                "status": "ok",
                "attrs": {"verdict": verdict, "subject": "refs/heads/main"},
            }
            for span_id, verdict in (("s-revise", "revise"), ("s-allow", "allow"))
        ],
    )
    conn.execute(
        insert(_raw_sentinel),
        [{"session_id": session_id, "messages": _shadow_conversation(), "synced_entries": 2, "eval_count": 2}],
    )


def test_a_session_from_before_0019_loads_with_its_change_requests_as_denials(tmp_path) -> None:
    engine, factory = create_engine_and_factory(DatabaseConfig(url=f"sqlite+pysqlite:///{tmp_path}/m.db"))
    cfg = _alembic_config(str(engine.url))
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "0018")
        _insert_pre_0019_session(conn, "s1")
        command.upgrade(cfg, "0019")
        log = conn.scalars(select(SessionActionLogRow.data).order_by(SessionActionLogRow.seq)).all()
        events = conn.scalars(select(SessionEventRow.data).order_by(SessionEventRow.seq)).all()
        audit = conn.scalars(select(SessionAuditRow.data)).all()
        spans = dict(conn.execute(select(SessionSpanRow.span_id, SessionSpanRow.attrs)).all())
        shadow = conn.scalar(select(_raw_sentinel.c.messages))
    security = SessionSecurity("s1", session_factory=factory)
    security.load_sentinel_state()
    engine.dispose()

    assert log == [_PUSH | {"decision": "denied"}, _ALLOWED_PUSH]
    assert [event["approval_verdict"] for event in events] == ["deny", "allow"]
    # Free text keeps its wording.
    assert events[0]["detail"] == "[sentinel: revise] split it"
    assert audit == [_AUDIT | {"final_decision": "denied", "sentinel_verdict": _VERDICT | {"decision": "deny"}}]
    assert spans == {
        "s-revise": {"verdict": "deny", "subject": "refs/heads/main"},
        "s-allow": {"verdict": "allow", "subject": "refs/heads/main"},
    }
    as_object, as_text, other_tool = (shadow[1]["parts"][0], shadow[3]["parts"][0], shadow[4]["parts"][0])
    assert as_object["args"] == _VERDICT | {"decision": "deny"}
    assert json.loads(as_text["args"]) == _VERDICT | {"decision": "deny"}
    assert other_tool["args"] == {"decision": "revise"}, "only the verdict tool's calls carry verdicts"
    assert [entry.decision for entry in security.action_log] == ["denied", "allowed"]
