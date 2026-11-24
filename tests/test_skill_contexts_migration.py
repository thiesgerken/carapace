from __future__ import annotations

from datetime import UTC, datetime

from alembic import command
from sqlalchemy import JSON, Connection, String, column, insert, select, table, update

from carapace.database.engine import _alembic_config, create_engine_and_factory
from carapace.database.models import SessionActionLogRow, SessionRow, SessionSentinelRow
from carapace.models.config import DatabaseConfig
from carapace.models.session import SessionState
from carapace.security.context import SessionSecurity

_raw_sessions = table("sessions", column("session_id", String), column("state", JSON))
_GRANT = {"skill_name": "weather", "domains": ["api.example.com"], "tunnels": [], "credential_names": {}}
_USER = {"type": "user_message", "content": "what is the weather"}
_ACTIVATED = {"type": "skill_activated", "skill_name": "weather", "description": "", "declared_domains": []}
_GRANTED = {"type": "context_grant", "skill_name": "weather", "domains": ["api.example.com"]}
_TOOL = {"type": "tool_call", "tool": "exec", "args": {"command": "weather"}, "decision": "allowed", "explanation": ""}


def _insert_pre_0018_session(conn: Connection, session_id: str, log: list[dict], *, synced_entries: int) -> None:
    now = datetime.now(tz=UTC)
    row = {"session_id": session_id, "user": "thies", "channel_type": "web", "created_at": now, "last_active": now}
    conn.execute(insert(SessionRow), [row | {"state": SessionState.now(session_id=session_id)}])
    # The current model writes neither field; a session from before 0018 has both.
    stored = conn.scalar(select(_raw_sessions.c.state).where(_raw_sessions.c.session_id == session_id))
    old = stored | {"activated_skills": ["weather"], "context_grants": {"weather": _GRANT}}
    conn.execute(update(_raw_sessions).where(_raw_sessions.c.session_id == session_id).values(state=old))
    conn.execute(
        insert(SessionActionLogRow),
        [{"session_id": session_id, "seq": seq, "data": data} for seq, data in enumerate(log)],
    )
    conn.execute(
        insert(SessionSentinelRow),
        [{"session_id": session_id, "messages": [], "synced_entries": synced_entries, "eval_count": 1}],
    )


def test_a_session_from_before_0018_loads_without_its_activations_and_grants(tmp_path) -> None:
    engine, factory = create_engine_and_factory(DatabaseConfig(url=f"sqlite+pysqlite:///{tmp_path}/m.db"))
    cfg = _alembic_config(str(engine.url))
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "0017")
        _insert_pre_0018_session(conn, "s1", [_USER, _ACTIVATED, _GRANTED, _TOOL, _USER], synced_entries=4)
        command.upgrade(cfg, "0018")
        log = conn.execute(
            select(SessionActionLogRow.seq, SessionActionLogRow.data).order_by(SessionActionLogRow.seq)
        ).all()
        synced = conn.scalar(select(SessionSentinelRow.synced_entries))
    with factory() as db:
        state = db.scalar(select(SessionRow.state))
    security = SessionSecurity("s1", session_factory=factory)
    security.load_sentinel_state()
    engine.dispose()

    assert state is not None and state.session_id == "s1"
    assert [(seq, data) for seq, data in log] == [(0, _USER), (1, _TOOL), (2, _USER)]
    # Two of the four entries the shadow conversation had seen are gone.
    assert synced == 2
    assert [entry.type for entry in security.action_log] == ["user_message", "tool_call", "user_message"]
    assert security.unsynced_entries() == security.action_log[2:]
