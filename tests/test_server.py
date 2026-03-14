"""Server smoke tests (no LLM tokens needed)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

# We patch the server module globals directly for testing
import carapace.server as srv
from carapace.auth import ensure_token
from carapace.bootstrap import ensure_data_dir
from carapace.config import load_config, load_security_md
from carapace.sandbox.manager import SandboxManager
from carapace.server import app
from carapace.session import SessionEngine, SessionManager
from carapace.skills import SkillRegistry


@pytest.fixture(autouse=True)
def _setup_server(tmp_path, monkeypatch):
    """Initialise server globals with a temp data dir so tests don't need lifespan."""
    # Bogus key — the sentinel Agent validates the env var at construction
    # time, but these tests never call the LLM.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake-for-tests")
    ensure_data_dir(tmp_path)
    config = load_config(tmp_path)
    security_md = load_security_md(tmp_path)
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
        security_md=security_md,
        session_mgr=session_mgr,
        skill_catalog=skill_catalog,
        agent_model=None,
        sandbox_mgr=sandbox_mgr,
    )
    ensure_token(tmp_path)


@pytest.fixture()
def bearer(tmp_path) -> str:
    return ensure_token(tmp_path)


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture()
def auth_headers(bearer) -> dict[str, str]:
    return {"Authorization": f"Bearer {bearer}"}


# --- Auth ---


def test_no_auth_returns_401(client):
    resp = client.get("/sessions")
    assert resp.status_code in (401, 403)


def test_bad_token_returns_401(client):
    resp = client.get("/sessions", headers={"Authorization": "Bearer wrong"})
    assert resp.status_code == 401


# --- Sessions REST ---


def test_create_session(client, auth_headers):
    resp = client.post("/sessions", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "session_id" in data
    assert data["channel_type"] == "cli"


def test_list_sessions(client, auth_headers):
    client.post("/sessions", headers=auth_headers)
    client.post("/sessions", headers=auth_headers)
    resp = client.get("/sessions", headers=auth_headers)
    assert resp.status_code == 200
    sessions = resp.json()
    assert len(sessions) >= 2


def test_get_session(client, auth_headers):
    create_resp = client.post("/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]
    resp = client.get(f"/sessions/{sid}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["session_id"] == sid


def test_get_nonexistent_session(client, auth_headers):
    resp = client.get("/sessions/doesnotexist", headers=auth_headers)
    assert resp.status_code == 404


# --- WebSocket: basic slash commands ---


def test_ws_auth_required(client):
    with pytest.raises(Exception), client.websocket_connect("/chat/fake"):  # noqa: B017
        pass


def test_ws_session_not_found(client, bearer):
    with pytest.raises(Exception), client.websocket_connect(f"/chat/doesnotexist?token={bearer}"):  # noqa: B017
        pass


def _consume_status(ws):
    """Consume the initial status message sent on connect."""
    msg = ws.receive_json()
    assert msg["type"] == "status"
    return msg


def test_ws_help_command(client, auth_headers, bearer):
    create_resp = client.post("/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]

    with client.websocket_connect(f"/chat/{sid}?token={bearer}") as ws:
        _consume_status(ws)
        ws.send_json({"type": "message", "content": "/help"})
        msg = ws.receive_json()
        assert msg["type"] == "command_result"
        assert msg["command"] == "help"
        assert "commands" in msg["data"]


def test_ws_security_command(client, auth_headers, bearer):
    create_resp = client.post("/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]

    with client.websocket_connect(f"/chat/{sid}?token={bearer}") as ws:
        _consume_status(ws)
        ws.send_json({"type": "message", "content": "/security"})
        msg = ws.receive_json()
        assert msg["type"] == "command_result"
        assert msg["command"] == "security"


def test_ws_session_command(client, auth_headers, bearer):
    create_resp = client.post("/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]

    with client.websocket_connect(f"/chat/{sid}?token={bearer}") as ws:
        _consume_status(ws)
        ws.send_json({"type": "message", "content": "/session"})
        msg = ws.receive_json()
        assert msg["type"] == "command_result"
        assert msg["command"] == "session"
        assert msg["data"]["session_id"] == sid


def test_ws_skills_command(client, auth_headers, bearer):
    create_resp = client.post("/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]

    with client.websocket_connect(f"/chat/{sid}?token={bearer}") as ws:
        _consume_status(ws)
        ws.send_json({"type": "message", "content": "/skills"})
        msg = ws.receive_json()
        assert msg["type"] == "command_result"
        assert msg["command"] == "skills"


def test_ws_memory_command(client, auth_headers, bearer):
    create_resp = client.post("/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]

    with client.websocket_connect(f"/chat/{sid}?token={bearer}") as ws:
        _consume_status(ws)
        ws.send_json({"type": "message", "content": "/memory"})
        msg = ws.receive_json()
        assert msg["type"] == "command_result"
        assert msg["command"] == "memory"


def test_ws_verbose_command(client, auth_headers, bearer):
    create_resp = client.post("/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]

    with client.websocket_connect(f"/chat/{sid}?token={bearer}") as ws:
        _consume_status(ws)
        ws.send_json({"type": "message", "content": "/verbose"})
        msg = ws.receive_json()
        assert msg["type"] == "command_result"
        assert msg["command"] == "verbose"
        assert msg["data"]["verbose"] is False


def test_ws_unknown_command(client, auth_headers, bearer):
    create_resp = client.post("/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]

    with client.websocket_connect(f"/chat/{sid}?token={bearer}") as ws:
        _consume_status(ws)
        ws.send_json({"type": "message", "content": "/foobar"})
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert "Unknown command" in msg["detail"]
