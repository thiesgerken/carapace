"""The `cgate` CLI contract: generated skill wrappers depend on its flags, request body and exit codes."""

from __future__ import annotations

import io
import json
import runpy
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
        "store_path": "/nix/store/abc-example",
    }


def test_denial_exits_1_with_the_reason(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    def deny(_request: urllib.request.Request) -> Any:
        raise urllib.error.HTTPError(
            "http://carapace/gate", 403, "Forbidden", {}, io.BytesIO(b"User denied this operation. Not now.")
        )

    monkeypatch.setattr(urllib.request, "urlopen", deny)

    assert _run(monkeypatch, "request", "--domain", "api.example.com") == 1
    assert capsys.readouterr().err == "error: User denied this operation. Not now.\n"


def test_tunnel_is_refused_by_name(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    assert _run(monkeypatch, "request", "--tunnel", "imap.example.com:993") == 2
    assert "--tunnel is not supported yet" in capsys.readouterr().err
