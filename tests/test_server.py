"""Server smoke tests (no LLM tokens needed)."""

from __future__ import annotations

import base64
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

# We patch the server module globals directly for testing
import carapace.server as srv
from carapace.bootstrap import ensure_data_dir
from carapace.config import load_config
from carapace.git.store import GitStore
from carapace.models import CredentialMetadata
from carapace.sandbox.manager import SandboxManager
from carapace.security.context import CredentialAccessEntry
from carapace.server import app, sandbox_app
from carapace.session import SessionEngine, SessionManager
from carapace.skills import SkillRegistry

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

    srv._data_dir = tmp_path
    srv._config = config
    srv._engine = SessionEngine(
        config=config,
        data_dir=tmp_path,
        knowledge_dir=tmp_path,
        git_store=MagicMock(spec=GitStore),
        session_mgr=session_mgr,
        skill_catalog=skill_catalog,
        agent_model=None,
        sandbox_mgr=sandbox_mgr,
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


def test_get_session(client, auth_headers):
    create_resp = client.post("/api/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]
    resp = client.get(f"/api/sessions/{sid}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["session_id"] == sid


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
