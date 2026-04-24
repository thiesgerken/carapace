"""Server smoke tests (no LLM tokens needed)."""

from __future__ import annotations

import base64
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

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

    cred_reg = CredentialRegistry()
    srv._data_dir = tmp_path
    srv._config = config
    srv._credential_registry = cred_reg
    srv._engine = SessionEngine(
        config=config,
        data_dir=tmp_path,
        knowledge_dir=tmp_path,
        git_store=MagicMock(spec=GitStore),
        session_mgr=session_mgr,
        skill_catalog=skill_catalog,
        agent_model=None,
        sandbox_mgr=sandbox_mgr,
        credential_registry=cred_reg,
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
    assert session["message_count"] == 2


def test_get_session(client, auth_headers):
    create_resp = client.post("/api/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]
    resp = client.get(f"/api/sessions/{sid}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["session_id"] == sid


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
