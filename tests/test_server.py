"""Server smoke tests (no LLM tokens needed)."""

from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart

# We patch the server module globals directly for testing
import carapace.sandbox.state as sandbox_state
import carapace.server as srv
from carapace.bootstrap import ensure_data_dir
from carapace.config import load_config
from carapace.credentials import CredentialRegistry
from carapace.git.store import GitStore
from carapace.models import CredentialMetadata, SessionBudget
from carapace.sandbox.manager import SandboxManager
from carapace.sandbox.state import SessionSandboxSnapshot
from carapace.security.context import CredentialAccessEntry
from carapace.server import app, sandbox_app
from carapace.session import SessionEngine, SessionManager
from carapace.session.archive import SessionArchiveResult, SessionArchiveService
from carapace.skills import SkillRegistry
from carapace.usage import LlmRequestState

_TEST_TOKEN = "test-bearer-token-for-server-tests"


@pytest.fixture(autouse=True)
def _setup_server(tmp_path, monkeypatch):
    """Initialise server globals with a temp data dir so tests don't need lifespan."""
    # Bogus key — the sentinel Agent validates the env var at construction
    # time, but these tests never call the LLM.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake-for-tests")
    monkeypatch.setenv("CARAPACE_TOKEN", _TEST_TOKEN)
    ensure_data_dir(tmp_path)
    config = load_config(tmp_path)
    session_mgr = SessionManager(tmp_path)
    registry = SkillRegistry(tmp_path / "skills")
    skill_catalog = registry.scan()
    sandbox_mgr = MagicMock(spec=SandboxManager)
    sandbox_mgr.get_domain_info.return_value = []
    sandbox_mgr.reset_session = AsyncMock()
    sandbox_mgr.destroy_session = AsyncMock()

    cred_reg = CredentialRegistry()
    git_store = MagicMock(spec=GitStore)
    git_store.commit = AsyncMock(return_value=True)
    srv._data_dir = tmp_path
    srv._config = config
    srv._credential_registry = cred_reg
    srv._engine = SessionEngine(
        config=config,
        data_dir=tmp_path,
        knowledge_dir=tmp_path,
        git_store=git_store,
        session_mgr=session_mgr,
        skill_catalog=skill_catalog,
        agent_model=None,
        sandbox_mgr=sandbox_mgr,
        credential_registry=cred_reg,
    )
    srv._session_archive = SessionArchiveService(
        knowledge_dir=tmp_path,
        git_store=git_store,
        session_mgr=session_mgr,
        config=config.sessions.commit,
    )


@pytest.fixture()
def bearer() -> str:
    return _TEST_TOKEN


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture()
def auth_headers(bearer) -> dict[str, str]:
    return {"Authorization": f"Bearer {bearer}"}


# --- Auth ---


def test_no_auth_returns_401(client):
    resp = client.get("/api/sessions")
    assert resp.status_code in (401, 403)


def test_bad_token_returns_401(client):
    resp = client.get("/api/sessions", headers={"Authorization": "Bearer wrong"})
    assert resp.status_code == 401


# --- Sessions REST ---


def test_create_session(client, auth_headers):
    resp = client.post("/api/sessions", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "session_id" in data
    assert data["channel_type"] == "cli"
    assert data["private"] is False


def test_create_session_uses_configured_default_privacy(client, auth_headers):
    srv._config.sessions.default_private = True

    resp = client.post("/api/sessions", headers=auth_headers)

    assert resp.status_code == 200
    assert resp.json()["private"] is True


def test_list_sessions(client, auth_headers):
    client.post("/api/sessions", headers=auth_headers)
    client.post("/api/sessions", headers=auth_headers)
    resp = client.get("/api/sessions", headers=auth_headers)
    assert resp.status_code == 200
    sessions = resp.json()
    assert len(sessions) >= 2


def test_list_sessions_skips_message_count_by_default(client, auth_headers, monkeypatch):
    create_resp = client.post("/api/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]

    load_events = MagicMock(side_effect=AssertionError("load_events should not be called"))
    monkeypatch.setattr(srv._engine.session_mgr, "load_events", load_events)

    resp = client.get("/api/sessions", headers=auth_headers)

    assert resp.status_code == 200
    session = next(item for item in resp.json() if item["session_id"] == sid)
    assert session["message_count"] == 0


def test_list_sessions_can_include_message_count(client, auth_headers):
    create_resp = client.post("/api/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]
    srv._engine.session_mgr.append_events(
        sid,
        [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "reply"},
            {"role": "user", "content": "second"},
        ],
    )

    resp = client.get("/api/sessions?include_message_count=true", headers=auth_headers)

    assert resp.status_code == 200
    session = next(item for item in resp.json() if item["session_id"] == sid)
    assert session["message_count"] == 3


def test_list_sessions_can_include_message_count_from_history_fallback(client, auth_headers):
    create_resp = client.post("/api/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]
    srv._engine.session_mgr.save_history(
        sid,
        [
            ModelRequest(parts=[UserPromptPart(content="first")]),
            ModelResponse(parts=[TextPart(content="reply")]),
            ModelRequest(parts=[UserPromptPart(content="second")]),
        ],
    )

    resp = client.get("/api/sessions?include_message_count=true", headers=auth_headers)

    assert resp.status_code == 200
    session = next(item for item in resp.json() if item["session_id"] == sid)
    assert session["message_count"] == 3


def test_get_session(client, auth_headers):
    create_resp = client.post("/api/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]
    resp = client.get(f"/api/sessions/{sid}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["session_id"] == sid


def test_update_session_privacy(client, auth_headers):
    create_resp = client.post("/api/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]
    srv._engine.session_mgr.append_events(
        sid,
        [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "world"},
        ],
    )

    resp = client.patch(f"/api/sessions/{sid}", headers=auth_headers, json={"private": True})

    assert resp.status_code == 200
    assert resp.json()["private"] is True
    assert resp.json()["message_count"] == 2
    assert srv._engine.session_mgr.load_state(sid).private is True


def test_update_session_privacy_updates_active_session_state(client, auth_headers):
    create_resp = client.post("/api/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]
    active = srv._engine.get_or_activate(sid)
    original_state = active.state
    active.state.activated_skills.append("demo-skill")
    assert active.state.private is False

    resp = client.patch(f"/api/sessions/{sid}", headers=auth_headers, json={"private": True})

    assert resp.status_code == 200
    assert active.state is original_state
    assert active.state.private is True
    assert active.state.activated_skills == ["demo-skill"]


def test_commit_session_knowledge_writes_archive(client, auth_headers, tmp_path):
    create_resp = client.post("/api/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]
    srv._engine.session_mgr.append_events(
        sid,
        [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "world"},
        ],
    )

    resp = client.post(f"/api/sessions/{sid}/knowledge/commit", headers=auth_headers)

    assert resp.status_code == 200
    data = resp.json()
    assert data["committed"] is True
    assert data["session"]["message_count"] == 2
    archive_path = data["archive_path"]
    assert archive_path is not None
    archive_file = tmp_path / archive_path
    assert archive_file.is_file()
    payload = archive_file.read_text()
    assert sid in payload
    assert '"history"' in payload
    assert '"timestamp"' in payload


def test_commit_session_knowledge_rejects_private_sessions(client, auth_headers):
    create_resp = client.post("/api/sessions", headers=auth_headers, json={"private": True})
    sid = create_resp.json()["session_id"]
    srv._engine.session_mgr.append_events(sid, [{"role": "user", "content": "secret"}])

    resp = client.post(f"/api/sessions/{sid}/knowledge/commit", headers=auth_headers)

    assert resp.status_code == 409


def test_commit_session_knowledge_passes_agent_guard_inside_archive_lock(client, auth_headers):
    create_resp = client.post("/api/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]
    srv._engine.session_mgr.append_events(sid, [{"role": "user", "content": "hello"}])
    srv._session_archive.commit_session = AsyncMock(
        return_value=SessionArchiveResult(
            committed=False,
            archive_path=None,
            committed_at=None,
            trigger="manual",
            reason="Cannot archive a session while an agent turn is running",
        )
    )

    resp = client.post(f"/api/sessions/{sid}/knowledge/commit", headers=auth_headers)

    assert resp.status_code == 200
    _, kwargs = srv._session_archive.commit_session.await_args
    assert kwargs["trigger"] == "manual"
    assert callable(kwargs["is_agent_running"])


def test_delete_session_removes_archived_knowledge(client, auth_headers, tmp_path):
    create_resp = client.post("/api/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]
    srv._engine.session_mgr.append_events(sid, [{"role": "user", "content": "hello"}])
    commit_resp = client.post(f"/api/sessions/{sid}/knowledge/commit", headers=auth_headers)
    archive_path = commit_resp.json()["archive_path"]
    assert archive_path is not None
    archive_file = tmp_path / archive_path
    assert archive_file.exists()

    resp = client.delete(f"/api/sessions/{sid}", headers=auth_headers)

    assert resp.status_code == 204
    assert not archive_file.exists()
    assert srv._engine.sandbox_mgr.destroy_session.await_count == 1


def test_delete_private_session_keeps_committed_knowledge(client, auth_headers, tmp_path):
    create_resp = client.post("/api/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]
    srv._engine.session_mgr.append_events(sid, [{"role": "user", "content": "hello"}])
    commit_resp = client.post(f"/api/sessions/{sid}/knowledge/commit", headers=auth_headers)
    archive_path = commit_resp.json()["archive_path"]
    assert archive_path is not None
    archive_file = tmp_path / archive_path
    assert archive_file.exists()

    patch_resp = client.patch(f"/api/sessions/{sid}", headers=auth_headers, json={"private": True})
    assert patch_resp.status_code == 200

    resp = client.delete(f"/api/sessions/{sid}", headers=auth_headers)

    assert resp.status_code == 204
    assert archive_file.exists()


def test_delete_session_still_succeeds_when_archive_cleanup_fails(client, auth_headers):
    create_resp = client.post("/api/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]
    srv._session_archive.delete_session_archive = AsyncMock(side_effect=RuntimeError("boom"))

    resp = client.delete(f"/api/sessions/{sid}", headers=auth_headers)

    assert resp.status_code == 204
    assert srv._engine.session_mgr.load_state(sid) is None


@pytest.mark.asyncio
async def test_autosave_skips_state_load_errors_and_continues(monkeypatch) -> None:
    eligible = srv._engine.session_mgr.create_session(private=False)
    cutoff_age = datetime.now(tz=UTC) - timedelta(hours=srv._config.sessions.commit.autosave_inactivity_hours + 1)

    eligible_state = srv._engine.session_mgr.load_state(eligible.session_id)
    eligible_state.last_active = cutoff_age
    srv._engine.session_mgr.save_state(eligible_state)

    bad_session_id = "broken-session"
    monkeypatch.setattr(srv._engine.session_mgr, "list_sessions", lambda: [bad_session_id, eligible.session_id])

    original_load_state = srv._engine.session_mgr.load_state

    def flaky_load_state(session_id: str):
        if session_id == bad_session_id:
            raise FileNotFoundError("missing state")
        return original_load_state(session_id)

    monkeypatch.setattr(srv._engine.session_mgr, "load_state", flaky_load_state)
    srv._session_archive.commit_session = AsyncMock()

    await srv._autosave_inactive_sessions()

    srv._session_archive.commit_session.assert_awaited_once()
    _, kwargs = srv._session_archive.commit_session.await_args
    assert kwargs["trigger"] == "autosave"
    cutoff_delta = kwargs["autosave_cutoff"] - cutoff_age
    assert timedelta(minutes=59) < cutoff_delta < timedelta(hours=1, minutes=1)
    assert kwargs["is_agent_running"]() is False


@pytest.mark.asyncio
async def test_autosave_skips_sessions_already_committed_since_last_activity() -> None:
    stale = srv._engine.session_mgr.create_session(private=False)
    eligible = srv._engine.session_mgr.create_session(private=False)
    cutoff_age = datetime.now(tz=UTC) - timedelta(hours=srv._config.sessions.commit.autosave_inactivity_hours + 1)

    stale_state = srv._engine.session_mgr.load_state(stale.session_id)
    stale_state.last_active = cutoff_age
    stale_state.knowledge_last_committed_at = cutoff_age + timedelta(minutes=5)
    srv._engine.session_mgr.save_state(stale_state)

    eligible_state = srv._engine.session_mgr.load_state(eligible.session_id)
    eligible_state.last_active = cutoff_age
    eligible_state.knowledge_last_committed_at = cutoff_age - timedelta(minutes=5)
    srv._engine.session_mgr.save_state(eligible_state)

    srv._session_archive.commit_session = AsyncMock()

    await srv._autosave_inactive_sessions()

    srv._session_archive.commit_session.assert_awaited_once()
    args, kwargs = srv._session_archive.commit_session.await_args
    assert args == (eligible.session_id,)
    assert kwargs["trigger"] == "autosave"


@pytest.mark.asyncio
async def test_autosave_passes_runtime_agent_guard(monkeypatch) -> None:
    eligible = srv._engine.session_mgr.create_session(private=False)
    cutoff_age = datetime.now(tz=UTC) - timedelta(hours=srv._config.sessions.commit.autosave_inactivity_hours + 1)

    eligible_state = srv._engine.session_mgr.load_state(eligible.session_id)
    eligible_state.last_active = cutoff_age
    srv._engine.session_mgr.save_state(eligible_state)

    monkeypatch.setattr(srv._engine, "is_agent_running", lambda session_id: session_id == eligible.session_id)
    srv._session_archive.commit_session = AsyncMock()

    await srv._autosave_inactive_sessions()

    srv._session_archive.commit_session.assert_not_awaited()


def test_get_session_includes_cached_sandbox_snapshot(client, auth_headers):
    create_resp = client.post("/api/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]
    srv._engine.session_mgr.save_sandbox_snapshot(
        sid,
        SessionSandboxSnapshot(
            runtime="kubernetes",
            status="scaled_down",
            storage_present=True,
            last_measured_used_bytes=1234,
        ),
    )

    resp = client.get(f"/api/sessions/{sid}", headers=auth_headers)

    assert resp.status_code == 200
    assert resp.json()["sandbox"]["status"] == "scaled_down"
    assert resp.json()["sandbox"]["last_measured_used_bytes"] == 1234


def test_get_session_uses_in_process_sandbox_snapshot_cache(client, auth_headers, monkeypatch):
    create_resp = client.post("/api/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]
    srv._engine.session_mgr.save_sandbox_snapshot(
        sid,
        SessionSandboxSnapshot(
            runtime="kubernetes",
            status="scaled_down",
            storage_present=True,
            last_measured_used_bytes=1234,
        ),
    )

    monkeypatch.setattr(
        sandbox_state.SessionSandboxSnapshot,
        "model_validate",
        MagicMock(side_effect=AssertionError("sandbox snapshot should be served from cache")),
    )

    first = client.get(f"/api/sessions/{sid}", headers=auth_headers)
    second = client.get(f"/api/sessions/{sid}", headers=auth_headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["sandbox"]["status"] == "scaled_down"
    assert second.json()["sandbox"]["status"] == "scaled_down"


def test_get_session_sandbox_returns_cached_snapshot(client, auth_headers):
    create_resp = client.post("/api/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]
    srv._engine.session_mgr.save_sandbox_snapshot(
        sid,
        SessionSandboxSnapshot(
            runtime="kubernetes",
            status="running",
            storage_present=True,
            last_measured_used_bytes=4096,
        ),
    )

    resp = client.get(f"/api/sessions/{sid}/sandbox", headers=auth_headers)

    assert resp.status_code == 200
    assert resp.json()["status"] == "running"
    assert resp.json()["last_measured_used_bytes"] == 4096


def test_get_session_sandbox_returns_default_snapshot_when_missing(client, auth_headers):
    create_resp = client.post("/api/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]

    resp = client.get(f"/api/sessions/{sid}/sandbox", headers=auth_headers)

    assert resp.status_code == 200
    assert resp.json()["status"] == "missing"
    assert resp.json()["exists"] is False


def test_start_session_sandbox_starts_when_idle(client, auth_headers):
    create_resp = client.post("/api/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]

    async def _ensure_session(session_id: str) -> tuple[MagicMock, bool]:
        assert session_id == sid
        srv._engine.session_mgr.save_sandbox_snapshot(
            sid,
            SessionSandboxSnapshot(
                exists=True,
                runtime="kubernetes",
                status="running",
                storage_present=True,
                updated_at=datetime.now(tz=UTC),
            ),
        )
        return MagicMock(), True

    srv._engine.sandbox_mgr.ensure_session = AsyncMock(side_effect=_ensure_session)

    resp = client.post(f"/api/sessions/{sid}/sandbox/up", headers=auth_headers)

    assert resp.status_code == 200
    assert resp.json()["status"] == "running"
    srv._engine.sandbox_mgr.ensure_session.assert_awaited_once_with(sid)


def test_start_session_sandbox_rejects_running_agent(client, auth_headers):
    create_resp = client.post("/api/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]
    active = srv._engine.get_or_activate(sid)
    active.agent_task = MagicMock()
    active.agent_task.done.return_value = False

    resp = client.post(f"/api/sessions/{sid}/sandbox/up", headers=auth_headers)

    assert resp.status_code == 409


def test_stop_session_sandbox_scales_down_when_idle(client, auth_headers):
    create_resp = client.post("/api/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]
    srv._engine.session_mgr.save_sandbox_snapshot(
        sid,
        SessionSandboxSnapshot(
            exists=True,
            runtime="kubernetes",
            status="running",
            storage_present=True,
            updated_at=datetime.now(tz=UTC),
        ),
    )

    async def _cleanup_session(session_id: str) -> None:
        assert session_id == sid
        srv._engine.session_mgr.save_sandbox_snapshot(
            sid,
            SessionSandboxSnapshot(
                exists=True,
                runtime="kubernetes",
                status="scaled_down",
                storage_present=True,
                updated_at=datetime.now(tz=UTC),
            ),
        )

    srv._engine.sandbox_mgr.cleanup_session = AsyncMock(side_effect=_cleanup_session)

    resp = client.post(f"/api/sessions/{sid}/sandbox/down", headers=auth_headers)

    assert resp.status_code == 200
    assert resp.json()["status"] == "scaled_down"
    srv._engine.sandbox_mgr.cleanup_session.assert_awaited_once_with(sid)


def test_stop_session_sandbox_rejects_running_agent(client, auth_headers):
    create_resp = client.post("/api/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]
    active = srv._engine.get_or_activate(sid)
    active.agent_task = MagicMock()
    active.agent_task.done.return_value = False

    resp = client.post(f"/api/sessions/{sid}/sandbox/down", headers=auth_headers)

    assert resp.status_code == 409


def test_wipe_session_sandbox_resets_when_idle(client, auth_headers):
    create_resp = client.post("/api/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]
    srv._engine.session_mgr.save_sandbox_snapshot(sid, SessionSandboxSnapshot(runtime="docker"))

    resp = client.post(f"/api/sessions/{sid}/sandbox/wipe", headers=auth_headers)

    assert resp.status_code == 200
    srv._engine.sandbox_mgr.reset_session.assert_awaited_once_with(sid)


def test_wipe_session_sandbox_rejects_running_agent(client, auth_headers):
    create_resp = client.post("/api/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]
    active = srv._engine.get_or_activate(sid)
    active.agent_task = MagicMock()
    active.agent_task.done.return_value = False

    resp = client.post(f"/api/sessions/{sid}/sandbox/wipe", headers=auth_headers)

    assert resp.status_code == 409


def test_get_nonexistent_session(client, auth_headers):
    resp = client.get("/api/sessions/doesnotexist", headers=auth_headers)
    assert resp.status_code == 404


def test_sandbox_list_credentials_audit(client, auth_headers, monkeypatch):
    """GET /credentials appends CredentialAccessEntry and audit for the session."""
    create_resp = client.post("/api/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]

    mock_reg = MagicMock()
    mock_reg.list = AsyncMock(return_value=[CredentialMetadata(vault_path="dev/key", name="key", description="test")])
    monkeypatch.setattr(srv, "_credential_registry", mock_reg, raising=False)
    srv._engine.sandbox_mgr.verify_session_token.side_effect = lambda s, t: s == sid and t == "secret"
    srv._engine.sandbox_mgr.mark_credential_notified.return_value = False

    basic = base64.b64encode(b"wrong-id:secret").decode()
    sb_client = TestClient(sandbox_app)
    resp = sb_client.get("/credentials", headers={"Authorization": f"Basic {basic}"})
    assert resp.status_code == 401

    basic_ok = base64.b64encode(f"{sid}:secret".encode()).decode()
    resp = sb_client.get("/credentials?q=dev", headers={"Authorization": f"Basic {basic_ok}"})
    assert resp.status_code == 200
    assert resp.json() == [{"vault_path": "dev/key", "name": "key", "description": "test"}]

    active = srv._engine.get_or_activate(sid)
    cred_entries = [e for e in active.security.action_log if isinstance(e, CredentialAccessEntry)]
    assert len(cred_entries) == 1
    assert cred_entries[0].vault_paths == ["dev/key"]
    assert cred_entries[0].decision == "approved"
    assert "query='dev'" in cred_entries[0].explanation

    audit_path = srv._data_dir / "sessions" / sid / "audit.yaml"
    assert audit_path.is_file()
    text = audit_path.read_text()
    assert "credential_access" in text
    assert "auto_allowed" in text


# --- WebSocket: basic slash commands ---


def test_ws_auth_required(client):
    with pytest.raises(Exception), client.websocket_connect("/api/chat/fake"):  # noqa: B017
        pass


def test_ws_session_not_found(client, bearer):
    with pytest.raises(Exception), client.websocket_connect(f"/api/chat/doesnotexist?token={bearer}"):  # noqa: B017
        pass


def _consume_status(ws):
    """Consume the initial status message sent on connect."""
    msg = ws.receive_json()
    assert msg["type"] == "status"
    return msg


def test_ws_help_command(client, auth_headers, bearer):
    create_resp = client.post("/api/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]

    with client.websocket_connect(f"/api/chat/{sid}?token={bearer}") as ws:
        _consume_status(ws)
        ws.send_json({"type": "message", "content": "/help"})
        echo = ws.receive_json()
        assert echo["type"] == "user_message"
        assert echo["content"] == "/help"
        msg = ws.receive_json()
        assert msg["type"] == "command_result"
        assert msg["command"] == "help"
        assert "commands" in msg["data"]


def test_ws_security_command(client, auth_headers, bearer):
    create_resp = client.post("/api/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]

    with client.websocket_connect(f"/api/chat/{sid}?token={bearer}") as ws:
        _consume_status(ws)
        ws.send_json({"type": "message", "content": "/security"})
        echo = ws.receive_json()
        assert echo["type"] == "user_message"
        msg = ws.receive_json()
        assert msg["type"] == "command_result"
        assert msg["command"] == "security"


def test_ws_session_command(client, auth_headers, bearer):
    create_resp = client.post("/api/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]

    with client.websocket_connect(f"/api/chat/{sid}?token={bearer}") as ws:
        _consume_status(ws)
        ws.send_json({"type": "message", "content": "/session"})
        echo = ws.receive_json()
        assert echo["type"] == "user_message"
        msg = ws.receive_json()
        assert msg["type"] == "command_result"
        assert msg["command"] == "session"
        assert msg["data"]["session_id"] == sid


def test_ws_reset_to_turn_emits_ack(client, auth_headers, bearer):
    create_resp = client.post("/api/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]
    srv._engine.session_mgr.save_events(
        sid,
        [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "first answer"},
            {"role": "user", "content": "second"},
            {"role": "assistant", "content": "second answer"},
        ],
    )
    srv._engine.session_mgr.save_history(
        sid,
        [
            ModelRequest(parts=[UserPromptPart(content="first")]),
            ModelResponse(parts=[TextPart(content="first answer")]),
            ModelRequest(parts=[UserPromptPart(content="second")]),
            ModelResponse(parts=[TextPart(content="second answer")]),
        ],
    )

    with client.websocket_connect(f"/api/chat/{sid}?token={bearer}") as ws:
        _consume_status(ws)
        ws.send_json({"type": "reset_to_turn", "event_index": 1})
        msg = ws.receive_json()
        assert msg["type"] == "command_result"
        assert msg["command"] == "reset_to_turn"
        assert msg["data"] == {"event_index": 1}

    assert srv._engine.session_mgr.load_events(sid) == [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "first answer"},
    ]


def test_ws_status_includes_budget_gauges_for_configured_defaults(client, auth_headers, bearer):
    srv._engine.config.agent.default_session_budget = SessionBudget(input_tokens=1_000)
    create_resp = client.post("/api/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]

    with client.websocket_connect(f"/api/chat/{sid}?token={bearer}") as ws:
        status = _consume_status(ws)
        assert status["usage"]["budget_gauges"][0]["key"] == "input"
        assert status["usage"]["budget_gauges"][0]["current_value"] == "0 tokens"


def test_ws_status_includes_live_llm_activity_when_running(client, auth_headers, bearer):
    create_resp = client.post("/api/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]
    active = srv._engine.get_or_activate(sid)
    active.llm_request_state = LlmRequestState(
        request_id="req-1",
        source="agent",
        model_name="anthropic:claude-haiku-4-5",
        started_at=datetime.now(tz=UTC),
        phase="thinking",
    )
    active.agent_task = MagicMock()
    active.agent_task.done.return_value = False

    with client.websocket_connect(f"/api/chat/{sid}?token={bearer}") as ws:
        status = _consume_status(ws)
        assert status["llm_activity"]["request_id"] == "req-1"
        assert status["llm_activity"]["phase"] == "thinking"
        assert status["llm_activity"]["source"] == "agent"


def test_history_includes_thinking_reasoning_metadata(client, auth_headers):
    create_resp = client.post("/api/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]
    srv._engine.session_mgr.append_events(
        sid,
        [
            {
                "role": "thinking",
                "content": "first thought",
                "reasoning_duration_ms": 1200,
                "reasoning_tokens": 42,
            },
            {"role": "assistant", "content": "done"},
        ],
    )

    resp = client.get(f"/api/sessions/{sid}/history", headers=auth_headers)

    assert resp.status_code == 200
    history = resp.json()
    assert history[0]["role"] == "thinking"
    assert history[0]["reasoning_duration_ms"] == 1200
    assert history[0]["reasoning_tokens"] == 42


def test_ws_budget_command_emits_status_refresh(client, auth_headers, bearer):
    create_resp = client.post("/api/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]

    with client.websocket_connect(f"/api/chat/{sid}?token={bearer}") as ws:
        _consume_status(ws)
        ws.send_json({"type": "message", "content": "/budget input 1000"})
        echo = ws.receive_json()
        assert echo["type"] == "user_message"
        msg = ws.receive_json()
        assert msg["type"] == "command_result"
        assert msg["command"] == "budget"
        status = ws.receive_json()
        assert status["type"] == "status"
        assert status["usage"]["budget_gauges"][0]["key"] == "input"


def test_ws_skills_command(client, auth_headers, bearer):
    create_resp = client.post("/api/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]

    with client.websocket_connect(f"/api/chat/{sid}?token={bearer}") as ws:
        _consume_status(ws)
        ws.send_json({"type": "message", "content": "/skills"})
        echo = ws.receive_json()
        assert echo["type"] == "user_message"
        msg = ws.receive_json()
        assert msg["type"] == "command_result"
        assert msg["command"] == "skills"


def test_ws_memory_command(client, auth_headers, bearer):
    create_resp = client.post("/api/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]

    with client.websocket_connect(f"/api/chat/{sid}?token={bearer}") as ws:
        _consume_status(ws)
        ws.send_json({"type": "message", "content": "/memory"})
        echo = ws.receive_json()
        assert echo["type"] == "user_message"
        msg = ws.receive_json()
        assert msg["type"] == "command_result"
        assert msg["command"] == "memory"


def test_ws_verbose_command(client, auth_headers, bearer):
    create_resp = client.post("/api/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]

    with client.websocket_connect(f"/api/chat/{sid}?token={bearer}") as ws:
        _consume_status(ws)
        ws.send_json({"type": "message", "content": "/verbose"})
        echo = ws.receive_json()
        assert echo["type"] == "user_message"
        msg = ws.receive_json()
        assert msg["type"] == "command_result"
        assert msg["command"] == "verbose"
        assert msg["data"]["verbose"] is False


def test_ws_unknown_command(client, auth_headers, bearer):
    create_resp = client.post("/api/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]

    with client.websocket_connect(f"/api/chat/{sid}?token={bearer}") as ws:
        _consume_status(ws)
        ws.send_json({"type": "message", "content": "/foobar"})
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert "Unknown command" in msg["detail"]
