"""CLI smoke tests (no LLM tokens needed)."""

import asyncio
import json
import re
from types import SimpleNamespace
from typing import ClassVar
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

import carapace.cli as cli_module
from carapace.cli import (
    _approval_info,
    _last_turn_terminal_content,
    _read_turn,
    _render_escalation_request,
    _replay_history,
    _ws_url,
    app,
)

runner = CliRunner()

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def test_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "carapace" in _strip_ansi(result.output)


def test_chat_help():
    result = runner.invoke(app, ["chat", "--help"])
    assert result.exit_code == 0
    output = _strip_ansi(result.output)
    assert "--session" in output
    assert "--server" in output
    assert "--user" in output
    assert "--password" in output
    assert "--api-key" in output
    assert "--key" in output


def test_chat_rejects_api_key_with_credentials() -> None:
    result = runner.invoke(app, ["chat", "--api-key", "ck_secret", "--user", "thies"])
    assert result.exit_code != 0
    assert "not both" in _strip_ansi(result.output)


def test_ws_url_appends_api_key():
    assert _ws_url("http://example.test", "s1") == "ws://example.test/api/chat/s1"
    assert _ws_url("https://example.test", "s1", "ck_a.b c") == "wss://example.test/api/chat/s1?api_key=ck_a.b%20c"


def test_chat_api_key_uses_bearer_and_skips_login(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeClient:
        def __init__(self, base_url: str, headers: dict[str, str] | None = None):
            assert base_url == "http://example.test"
            assert headers == {"Authorization": "Bearer ck_secret"}

        def post(self, *args: object, **kwargs: object):
            raise AssertionError("API-key auth must not call /api/auth/login")

        def get(self, url: str, *, params: dict[str, str] | None = None):
            assert url == "/api/sessions"
            return _FakeHttpResponse({"items": [], "has_more": False, "next_cursor": None})

        def close(self) -> None:
            return None

    monkeypatch.setattr(cli_module.httpx, "Client", _FakeClient)

    result = runner.invoke(app, ["chat", "--server", "http://example.test", "--api-key", "ck_secret", "--list"])
    assert result.exit_code == 0
    assert "No existing sessions." in _strip_ansi(result.output)


@pytest.mark.parametrize(
    ("inputs", "expected_decision", "expected_message"),
    [
        (["a"], "allow", None),
        (["allow"], "allow", None),
        (["d", ""], "deny", None),
        (["deny", "blocked by user"], "deny", "blocked by user"),
        (["x", "not safe enough"], "deny", "not safe enough"),
    ],
)
def test_proxy_approval_choice_mapping(inputs: list[str], expected_decision: str, expected_message: str | None):
    with patch("carapace.cli.console.input", side_effect=inputs):
        decision, message = asyncio.run(_render_escalation_request({"domain": "example.com", "command": "curl"}))
    assert decision == expected_decision
    assert message == expected_message


class _FakeHttpResponse:
    def __init__(self, payload: object):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self._payload


def test_chat_list_fetches_all_session_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = iter(
        [
            {
                "items": [
                    {
                        "session_id": "session-1",
                        "title": "First",
                        "created_at": "2026-05-06T10:00:00",
                        "last_active": "2026-05-06T10:01:00",
                        "message_count": 3,
                    }
                ],
                "has_more": True,
                "next_cursor": "1",
            },
            {
                "items": [
                    {
                        "session_id": "session-2",
                        "title": "Second",
                        "created_at": "2026-05-06T10:02:00",
                        "last_active": "2026-05-06T10:03:00",
                        "message_count": 7,
                    }
                ],
                "has_more": False,
                "next_cursor": None,
            },
        ]
    )
    seen_params: list[dict[str, str]] = []

    class _Cookie:
        name = "carapace_session"
        value = "session-token"

    class _Cookies:
        def __init__(self) -> None:
            self.jar = [_Cookie()]

    class _FakeClient:
        def __init__(self, base_url: str):
            assert base_url == "http://example.test"
            self.cookies = _Cookies()

        def post(self, url: str, *, json: dict[str, str] | None = None):
            assert url == "/api/auth/login"
            assert json == {"username": "thies", "password": "secret"}
            return _FakeHttpResponse({"user": {"username": "thies"}})

        def get(self, url: str, *, params: dict[str, str] | None = None):
            assert url == "/api/sessions"
            seen_params.append(dict(params or {}))
            return _FakeHttpResponse(next(responses))

        def close(self) -> None:
            return None

    monkeypatch.setattr(cli_module.httpx, "Client", _FakeClient)

    result = runner.invoke(
        app,
        ["chat", "--server", "http://example.test", "--user", "thies", "--password", "secret", "--list"],
    )

    assert result.exit_code == 0
    output = _strip_ansi(result.output)
    assert "session-1" in output
    assert "session-2" in output
    assert seen_params == [
        {"include_message_count": "true", "limit": "200"},
        {"include_message_count": "true", "limit": "200", "cursor": "1"},
    ]


def test_replay_history_uses_authenticated_client(monkeypatch: pytest.MonkeyPatch) -> None:
    seen_requests: list[tuple[str, dict[str, int]]] = []

    class _FakeClient:
        def get(self, url: str, *, params: dict[str, int] | None = None):
            seen_requests.append((url, dict(params or {})))
            return _FakeHttpResponse([{"role": "user", "content": "hello"}])

    def fail_module_get(*args: object, **kwargs: object) -> None:
        raise AssertionError("module-level httpx.get should not be used")

    monkeypatch.setattr(cli_module.httpx, "get", fail_module_get)

    _replay_history(_FakeClient(), "session-1", 25)  # type: ignore[arg-type]

    assert seen_requests == [("/api/sessions/session-1/history", {"limit": 25})]


# --- agent (non-interactive) commands ---


class _FakeResponse:
    def __init__(self, status_code: int, payload: object = None):
        self.status_code = status_code
        self._payload = payload
        self.text = ""

    def json(self) -> object:
        return self._payload


class _FakeAgentClient:
    """Records REST calls; returns queued responses keyed by (method, path-prefix)."""

    calls: ClassVar[list[tuple[str, str, dict[str, object] | None]]] = []
    responses: ClassVar[dict[tuple[str, str], _FakeResponse]] = {}

    def __init__(self, base_url: str, headers: dict[str, str] | None = None):
        self.base_url = base_url

    def request(self, method: str, path: str, *, params=None, json=None):
        _FakeAgentClient.calls.append((method, path, json))
        return _FakeAgentClient.responses.get((method, path), _FakeResponse(200, {}))

    def close(self) -> None:
        return None


class _FakeWS:
    def __init__(self, frames: list[dict[str, object]]):
        self._frames = list(frames)
        self.sent: list[dict[str, object]] = []

    async def recv(self) -> str:
        if self._frames:
            return json.dumps(self._frames.pop(0))
        await asyncio.sleep(10)  # block so an outer timeout fires
        raise AssertionError("unreachable")

    async def send(self, data: str) -> None:
        self.sent.append(json.loads(data))

    async def close(self) -> None:
        return None


def test_chat_refuses_non_tty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli_module.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(cli_module.sys.stdout, "isatty", lambda: False)
    monkeypatch.setattr(cli_module.httpx, "Client", _FakeAgentClient)
    result = runner.invoke(app, ["chat", "--server", "http://example.test", "--api-key", "ck_x"])
    assert result.exit_code == 1
    assert "not a TTY" in _strip_ansi(result.output)


def test_read_turn_done_keeps_markup() -> None:
    ws = _FakeWS([{"type": "status"}, {"type": "done", "content": "# Title $x^2$", "usage": {}}])
    result, code = asyncio.run(_read_turn(ws, session_id="s1", timeout=5, stream=False))
    assert code == 0
    assert result["status"] == "done"
    assert result["content"] == "# Title $x^2$"  # markup preserved verbatim


def test_read_turn_aborts_on_approval() -> None:
    ws = _FakeWS([{"type": "approval_request", "tool_call_id": "tc1", "tool": "bash", "args": {}}])
    result, code = asyncio.run(_read_turn(ws, session_id="s1", timeout=5, stream=False))
    assert code == 2
    assert result["status"] == "needs_approval"
    assert result["request"]["id"] == "tc1"
    assert result["allow_command"] == "carapace approval allow s1 tc1"
    assert result["deny_command"] == "carapace approval deny s1 tc1"


def test_read_turn_times_out() -> None:
    ws = _FakeWS([])
    result, code = asyncio.run(_read_turn(ws, session_id="s1", timeout=0.05, stream=False))
    assert code == 3
    assert result["status"] == "timeout"


def test_read_turn_observe_status_already_finished() -> None:
    # job run --wait: turn finished before connect -> only an on-connect status, no terminal frame.
    # Reported as neutral "finished" (not a fabricated "done" success), with usage carried over.
    ws = _FakeWS([{"type": "status", "agent_running": False, "usage": {"total": 1}}])
    result, code = asyncio.run(_read_turn(ws, session_id="s1", timeout=5, stream=False, observe=True))
    assert code == 0
    assert result["status"] == "finished"
    assert result["usage"] == {"total": 1}


def test_read_turn_observe_status_running_waits_for_done() -> None:
    # Still running on connect: ignore the status, wait for the real done frame.
    ws = _FakeWS([{"type": "status", "agent_running": True}, {"type": "done", "content": "ok", "usage": {}}])
    result, code = asyncio.run(_read_turn(ws, session_id="s1", timeout=5, stream=False, observe=True))
    assert code == 0
    assert result["status"] == "done"
    assert result["content"] == "ok"


def test_read_turn_status_ignored_when_not_observing() -> None:
    # send/approval path: the on-connect status (agent_running False, pre-send) must not terminate.
    ws = _FakeWS([{"type": "status", "agent_running": False}])
    result, code = asyncio.run(_read_turn(ws, session_id="s1", timeout=0.05, stream=False))
    assert code == 3
    assert result["status"] == "timeout"


def test_last_turn_terminal_content_returns_latest_assistant() -> None:
    history = [
        {"role": "user", "content": "go"},
        {"role": "assistant", "content": "first"},
        {"role": "tool_call", "tool": "bash"},
        {"role": "assistant", "content": "done"},
    ]
    cli = SimpleNamespace(client=SimpleNamespace(get=lambda url, *, params=None: _FakeHttpResponse(history)))
    assert _last_turn_terminal_content(cli, "s1") == "done"  # type: ignore[arg-type]


def test_last_turn_terminal_content_returns_turn_error() -> None:
    # A failed/cancelled turn persists its terminal message as an error event; the observer
    # backfill surfaces that instead of the previous turn's answer.
    history = [
        {"role": "user", "content": "go"},
        {"role": "assistant", "content": "first"},
        {"role": "user", "content": "again"},
        {"role": "error", "content": "The previous turn failed before completion."},
    ]
    cli = SimpleNamespace(client=SimpleNamespace(get=lambda url, *, params=None: _FakeHttpResponse(history)))
    assert _last_turn_terminal_content(cli, "s1") == "The previous turn failed before completion."  # type: ignore[arg-type]


def test_last_turn_terminal_content_tolerates_errors() -> None:
    def _boom(url: str, *, params: object = None) -> None:
        raise cli_module.httpx.ConnectError("down")

    cli = SimpleNamespace(client=SimpleNamespace(get=_boom))
    assert _last_turn_terminal_content(cli, "s1") == ""  # type: ignore[arg-type]


def test_approval_info_escalation() -> None:
    info = _approval_info({"type": "domain_access_approval_request", "request_id": "r1", "domain": "x.test"}, "s1")
    assert info["request"]["id"] == "r1"
    assert info["request"]["kind"] == "domain_access"
    assert info["allow_command"] == "carapace approval allow s1 r1"


def test_session_get_emits_json(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeAgentClient.calls = []
    _FakeAgentClient.responses = {("GET", "/api/sessions/s1"): _FakeResponse(200, {"session_id": "s1"})}
    monkeypatch.setattr(cli_module.httpx, "Client", _FakeAgentClient)
    result = runner.invoke(app, ["session", "get", "s1"], env={"CARAPACE_API_KEY": "ck_x"})
    assert result.exit_code == 0
    assert json.loads(result.output) == {"session_id": "s1"}
    assert ("GET", "/api/sessions/s1", None) in _FakeAgentClient.calls


def test_session_create_sends_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeAgentClient.calls = []
    _FakeAgentClient.responses = {("POST", "/api/sessions"): _FakeResponse(200, {"session_id": "s2"})}
    monkeypatch.setattr(cli_module.httpx, "Client", _FakeAgentClient)
    result = runner.invoke(app, ["session", "create", "--yolo"], env={"CARAPACE_API_KEY": "ck_x"})
    assert result.exit_code == 0
    assert ("POST", "/api/sessions", {"channel_type": "cli", "yolo_mode": True}) in _FakeAgentClient.calls


def test_approval_allow_sends_tool_response(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_request(cli, method, path, **kwargs):
        return {"approvals": [{"id": "tc1", "kind": "tool"}], "escalations": []}

    async def fake_drive(cli, session_id, *, approval=None, wait, timeout, **kwargs):
        captured["approval"] = approval
        return {"status": "submitted"}, 0

    monkeypatch.setattr(cli_module, "_request_json", fake_request)
    monkeypatch.setattr(cli_module, "_drive_turn", fake_drive)
    monkeypatch.setattr(cli_module.httpx, "Client", _FakeAgentClient)
    result = runner.invoke(app, ["approval", "allow", "s1", "tc1"], env={"CARAPACE_API_KEY": "ck_x"})
    assert result.exit_code == 0
    assert captured["approval"] == {
        "type": "approval_response",
        "tool_call_id": "tc1",
        "approved": True,
        "message": None,
    }


def test_approval_deny_unknown_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli_module, "_request_json", lambda *a, **k: {"approvals": [], "escalations": []})
    monkeypatch.setattr(cli_module.httpx, "Client", _FakeAgentClient)
    result = runner.invoke(app, ["approval", "deny", "s1", "nope"], env={"CARAPACE_API_KEY": "ck_x"})
    assert result.exit_code == 1
    assert json.loads(result.output)["status"] == "not_found"


def test_job_create_reads_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeAgentClient.calls = []
    _FakeAgentClient.responses = {("POST", "/api/jobs"): _FakeResponse(201, {"id": "j1"})}
    monkeypatch.setattr(cli_module.httpx, "Client", _FakeAgentClient)
    result = runner.invoke(
        app, ["job", "create", "--file", "-"], input='{"name":"j"}', env={"CARAPACE_API_KEY": "ck_x"}
    )
    assert result.exit_code == 0
    assert ("POST", "/api/jobs", {"name": "j"}) in _FakeAgentClient.calls
