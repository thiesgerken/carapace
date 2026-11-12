from __future__ import annotations

from datetime import UTC, datetime

from alembic import command
from sqlalchemy import Connection, insert, select

from carapace.database.engine import _alembic_config, create_engine_and_factory
from carapace.database.models import SessionActionLogRow, SessionEventRow, SessionRow, SessionSentinelRow
from carapace.models.config import DatabaseConfig
from carapace.models.session import SessionState
from carapace.security.context import SessionSecurity, ToolCallEntry, UserMessageEntry

_USER = {"type": "user_message", "content": "push the fix"}
_LEGACY_RESPONSE = {"type": "agent_response", "token_count": 1234}
_TOOL = {"type": "tool_call", "tool": "exec", "args": {"command": "ls"}, "decision": "allowed", "explanation": ""}


def _insert_session(conn: Connection, session_id: str, log: list[dict], *, synced_entries: int | None) -> None:
    now = datetime.now(tz=UTC)
    row = {"session_id": session_id, "user": "u", "channel_type": "web", "created_at": now, "last_active": now}
    conn.execute(insert(SessionRow), [row | {"state": SessionState.now(session_id=session_id)}])
    conn.execute(
        insert(SessionActionLogRow),
        [{"session_id": session_id, "seq": seq, "data": data} for seq, data in enumerate(log)],
    )
    if synced_entries is not None:
        conn.execute(
            insert(SessionSentinelRow),
            [{"session_id": session_id, "messages": [], "synced_entries": synced_entries, "eval_count": 1}],
        )


def _log(conn: Connection, session_id: str) -> list[tuple[int, dict]]:
    rows = conn.execute(
        select(SessionActionLogRow.seq, SessionActionLogRow.data)
        .where(SessionActionLogRow.session_id == session_id)
        .order_by(SessionActionLogRow.seq)
    )
    return [(seq, data) for seq, data in rows]


def test_upgrade_drops_textless_agent_responses_and_keeps_the_sync_position(tmp_path) -> None:
    engine, factory = create_engine_and_factory(DatabaseConfig(url=f"sqlite+pysqlite:///{tmp_path}/m.db"))
    cfg = _alembic_config(str(engine.url))
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "0013")
        _insert_session(
            conn,
            "synced",
            [_USER, _LEGACY_RESPONSE, _TOOL, _LEGACY_RESPONSE, _USER, _LEGACY_RESPONSE],
            synced_entries=4,
        )
        _insert_session(conn, "never-evaluated", [_USER, _LEGACY_RESPONSE], synced_entries=None)
        _insert_session(conn, "untouched", [_USER, _TOOL], synced_entries=2)

        command.upgrade(cfg, "0014")

        assert _log(conn, "synced") == [(0, _USER), (1, _TOOL), (2, _USER)]
        # The shadow conversation had seen the user message and the tool call, but not the last user message.
        assert (
            conn.scalar(select(SessionSentinelRow.synced_entries).where(SessionSentinelRow.session_id == "synced")) == 2
        )
        assert _log(conn, "never-evaluated") == [(0, _USER)]
        assert _log(conn, "untouched") == [(0, _USER), (1, _TOOL)]
        assert (
            conn.scalar(select(SessionSentinelRow.synced_entries).where(SessionSentinelRow.session_id == "untouched"))
            == 2
        )
    try:
        security = SessionSecurity("synced", session_factory=factory)
        security.load_sentinel_state()
        assert security.unsynced_entries() == [UserMessageEntry(content="push the fix")]
    finally:
        engine.dispose()


def test_downgrade_turns_change_requests_into_denials(tmp_path) -> None:
    engine, _ = create_engine_and_factory(DatabaseConfig(url=f"sqlite+pysqlite:///{tmp_path}/m.db"))
    cfg = _alembic_config(str(engine.url))
    revised = ToolCallEntry(tool="exec", args={"command": "ls"}, decision="changes_requested", explanation="split it")
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "0014")
        _insert_session(conn, "s", [_USER, revised.model_dump(mode="json")], synced_entries=None)
        conn.execute(
            insert(SessionEventRow),
            [
                {
                    "session_id": "s",
                    "seq": 0,
                    "data": {"role": "tool_call", "tool": "exec", "approval_verdict": "revise"},
                }
            ],
        )

        command.downgrade(cfg, "0013")

        assert _log(conn, "s")[1][1]["decision"] == "denied"
        assert conn.scalar(select(SessionEventRow.data)) == {
            "role": "tool_call",
            "tool": "exec",
            "approval_verdict": "deny",
        }
    engine.dispose()
