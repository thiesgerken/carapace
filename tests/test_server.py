"""Server smoke tests (no LLM tokens needed)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

# We patch the server module globals directly for testing
import carapace.server as srv
from carapace.auth import ensure_token
from carapace.bootstrap import ensure_data_dir
from carapace.config import load_config, load_rules
from carapace.server import app
from carapace.session import SessionManager
from carapace.skills import SkillRegistry


@pytest.fixture(autouse=True)
def _setup_server(tmp_path):
    """Initialise server globals with a temp data dir so tests don't need lifespan."""
    ensure_data_dir(tmp_path)
    srv._data_dir = tmp_path
    srv._config = load_config(tmp_path)
    srv._rules = load_rules(tmp_path)
    srv._session_mgr = SessionManager(tmp_path)
    registry = SkillRegistry(tmp_path / "skills")
    srv._skill_catalog = registry.scan()
    srv._agent_model = None
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


def test_ws_help_command(client, auth_headers, bearer):
    create_resp = client.post("/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]

    with client.websocket_connect(f"/chat/{sid}?token={bearer}") as ws:
        ws.send_json({"type": "message", "content": "/help"})
        msg = ws.receive_json()
        assert msg["type"] == "command_result"
        assert msg["command"] == "help"
        assert "commands" in msg["data"]


def test_ws_rules_command(client, auth_headers, bearer):
    create_resp = client.post("/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]

    with client.websocket_connect(f"/chat/{sid}?token={bearer}") as ws:
        ws.send_json({"type": "message", "content": "/rules"})
        msg = ws.receive_json()
        assert msg["type"] == "command_result"
        assert msg["command"] == "rules"


def test_ws_session_command(client, auth_headers, bearer):
    create_resp = client.post("/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]

    with client.websocket_connect(f"/chat/{sid}?token={bearer}") as ws:
        ws.send_json({"type": "message", "content": "/session"})
        msg = ws.receive_json()
        assert msg["type"] == "command_result"
        assert msg["command"] == "session"
        assert msg["data"]["session_id"] == sid


def test_ws_skills_command(client, auth_headers, bearer):
    create_resp = client.post("/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]

    with client.websocket_connect(f"/chat/{sid}?token={bearer}") as ws:
        ws.send_json({"type": "message", "content": "/skills"})
        msg = ws.receive_json()
        assert msg["type"] == "command_result"
        assert msg["command"] == "skills"


def test_ws_memory_command(client, auth_headers, bearer):
    create_resp = client.post("/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]

    with client.websocket_connect(f"/chat/{sid}?token={bearer}") as ws:
        ws.send_json({"type": "message", "content": "/memory"})
        msg = ws.receive_json()
        assert msg["type"] == "command_result"
        assert msg["command"] == "memory"


def test_ws_verbose_command(client, auth_headers, bearer):
    create_resp = client.post("/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]

    with client.websocket_connect(f"/chat/{sid}?token={bearer}") as ws:
        ws.send_json({"type": "message", "content": "/verbose"})
        msg = ws.receive_json()
        assert msg["type"] == "command_result"
        assert msg["command"] == "verbose"
        assert msg["data"]["verbose"] is False


def test_ws_usage_command(client, auth_headers, bearer):
    create_resp = client.post("/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]

    with client.websocket_connect(f"/chat/{sid}?token={bearer}") as ws:
        ws.send_json({"type": "message", "content": "/usage"})
        msg = ws.receive_json()
        assert msg["type"] == "command_result"
        assert msg["command"] == "usage"
        assert "total_requests" in msg["data"]
        assert "total_tokens" in msg["data"]
        assert "total_cost" in msg["data"]
        assert msg["data"]["total_requests"] == 0


def test_ws_unknown_command(client, auth_headers, bearer):
    create_resp = client.post("/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]

    with client.websocket_connect(f"/chat/{sid}?token={bearer}") as ws:
        ws.send_json({"type": "message", "content": "/foobar"})
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert "Unknown command" in msg["detail"]
