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
        (403, "Forbidden", b"", "credential request denied by user"),
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
