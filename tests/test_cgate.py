"""The `cgate` CLI contract: generated skill wrappers depend on its flags, request body and exit codes."""

from __future__ import annotations

import io
import json
import runpy
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest

CGATE = str(Path(__file__).parents[1] / "sandbox" / "cgate")


def _run(monkeypatch: pytest.MonkeyPatch, *argv: str) -> int:
    monkeypatch.setenv("CARAPACE_API_URL", "http://sess-1:token@carapace:8322")
    monkeypatch.setattr(sys, "argv", ["cgate", *argv])
    with pytest.raises(SystemExit) as exc_info:
        runpy.run_path(CGATE, run_name="__main__")
        raise SystemExit(0)
    return int(exc_info.value.code or 0)


def test_request_posts_the_declaration(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[urllib.request.Request] = []

    class _Ok:
        def __enter__(self) -> _Ok:
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

        def read(self) -> bytes:
            return b""

    def capture(request: urllib.request.Request) -> Any:
        sent.append(request)
        return _Ok()

    monkeypatch.setattr(urllib.request, "urlopen", capture)

    code = _run(
        monkeypatch,
        "request",
        "--domain",
        "api.example.com",
        "--domain",
        "*.cdn.example.com",
        "--credential",
        "demo/api-key",
        "--oauth",
        "demo/tracker-oauth",
        "--tunnel",
        "imap.example.com:993",
        "--store-path",
        "/nix/store/abc-example",
    )

    assert code == 0
    (request,) = sent
    assert (request.full_url, request.get_method()) == ("http://carapace:8322/gate", "POST")
    assert request.get_header("Authorization") == "Basic c2Vzcy0xOnRva2Vu"
    assert json.loads(request.data or b"") == {
        "domains": ["api.example.com", "*.cdn.example.com"],
        "credentials": ["demo/api-key"],
        "oauth": ["demo/tracker-oauth"],
        "tunnels": ["imap.example.com:993"],
        "store_path": "/nix/store/abc-example",
        "command": None,
    }


def test_a_skill_command_gets_its_settings_and_credentials_as_exports(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    sent: list[urllib.request.Request] = []
    answer = {
        "settings": {"CITY": "Bad Homburg", "PORT": 443, "METRIC": True},
        "credentials": {"TOKEN": "demo/t"},
        "oauth": {"CAL": "demo/cal"},
    }

    class _Answer(io.BytesIO):
        def __enter__(self) -> _Answer:
            return self

    def respond(request: urllib.request.Request) -> Any:
        sent.append(request)
        return _Answer(json.dumps(answer).encode())

    def ccred(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        assert args == ["ccred", "get", "demo/t"]
        return subprocess.CompletedProcess(args, 0, stdout="it's s3cret\n")

    monkeypatch.setattr(urllib.request, "urlopen", respond)
    monkeypatch.setattr(subprocess, "run", ccred)

    code = _run(monkeypatch, "request", "--store-path", "/nix/store/abc-example", "--command", "weather")

    assert code == 0
    assert json.loads(sent[0].data or b"")["command"] == "weather"
    assert capsys.readouterr().out.splitlines() == [
        "export CITY='Bad Homburg'",
        "export PORT=443",
        "export METRIC=true",
        "export CAL=demo/cal",
        "export TOKEN='it'\"'\"'s s3cret'",
    ]


def test_a_command_takes_nothing_but_its_store_path(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _run(monkeypatch, "request", "--command", "weather") == 2
    assert _run(monkeypatch, "request", "--store-path", "/nix/store/a-b", "--command", "w", "--domain", "x.com") == 2


def test_denial_exits_1_with_the_reason(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    def deny(_request: urllib.request.Request) -> Any:
        raise urllib.error.HTTPError(
            "http://carapace/gate", 403, "Forbidden", {}, io.BytesIO(b"User denied this operation. Not now.")
        )

    monkeypatch.setattr(urllib.request, "urlopen", deny)

    assert _run(monkeypatch, "request", "--domain", "api.example.com") == 1
    assert capsys.readouterr().err == "error: User denied this operation. Not now.\n"


def test_a_tunnel_that_did_not_open_exits_1_with_the_reason(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail(_request: urllib.request.Request) -> Any:
        body = io.BytesIO(b"The tunnels could not be opened: imap.example.com:993 did not start")
        raise urllib.error.HTTPError("http://carapace/gate", 502, "Bad Gateway", {}, body)

    monkeypatch.setattr(urllib.request, "urlopen", fail)

    assert _run(monkeypatch, "request", "--tunnel", "imap.example.com:993") == 1
    assert capsys.readouterr().err == "error: The tunnels could not be opened: imap.example.com:993 did not start\n"
