from __future__ import annotations

import argparse
import io
import runpy
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest


@pytest.mark.parametrize(
    ("code", "reason", "body", "expected"),
    [
        (400, "Bad Request", b"login retrieval is unsupported", "login retrieval is unsupported"),
        (
            403,
            "Forbidden",
            b"Sentinel denied this operation. Not needed for the task.",
            "Sentinel denied this operation. Not needed for the task.",
        ),
        (404, "Not Found", b"", "credential not found: files/key"),
        (500, "Internal Server Error", b"", "500 Internal Server Error"),
    ],
)
def test_get_prints_http_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    code: int,
    reason: str,
    body: bytes,
    expected: str,
) -> None:
    namespace = runpy.run_path(str(Path(__file__).parents[1] / "sandbox" / "ccred"))
    error = urllib.error.HTTPError(
        "http://carapace/credentials/files/key?kind=login",
        code,
        reason,
        {},
        io.BytesIO(body),
    )

    def fail(_request: urllib.request.Request) -> Any:
        raise error

    monkeypatch.setenv("CARAPACE_API_URL", "http://carapace")
    monkeypatch.setattr(urllib.request, "urlopen", fail)

    with pytest.raises(SystemExit) as exc_info:
        namespace["cmd_get"](argparse.Namespace(vault_path="files/key", kind="login", output=None))

    assert exc_info.value.code == 1
    assert capsys.readouterr().err == f"error: {expected}\n"


def test_list_prints_the_denial(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    namespace = runpy.run_path(str(Path(__file__).parents[1] / "sandbox" / "ccred"))

    def fail(_request: urllib.request.Request) -> Any:
        raise urllib.error.HTTPError(
            "http://carapace/credentials", 403, "Forbidden", {}, io.BytesIO(b"User denied this operation.")
        )

    monkeypatch.setenv("CARAPACE_API_URL", "http://carapace")
    monkeypatch.setattr(urllib.request, "urlopen", fail)

    with pytest.raises(SystemExit) as exc_info:
        namespace["cmd_list"](argparse.Namespace())

    assert exc_info.value.code == 1
    assert capsys.readouterr().err == "error: User denied this operation.\n"
