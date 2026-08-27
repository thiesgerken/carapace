from __future__ import annotations

import argparse
import io
import runpy
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest


def test_get_prints_http_400_body(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    namespace = runpy.run_path(str(Path(__file__).parents[1] / "sandbox" / "ccred"))
    error = urllib.error.HTTPError(
        "http://carapace/credentials/files/key?kind=login",
        400,
        "Bad Request",
        {},
        io.BytesIO(b"login retrieval is unsupported"),
    )

    def fail(_request: urllib.request.Request) -> Any:
        raise error

    monkeypatch.setenv("CARAPACE_API_URL", "http://carapace")
    monkeypatch.setattr(urllib.request, "urlopen", fail)

    with pytest.raises(SystemExit) as exc_info:
        namespace["cmd_get"](argparse.Namespace(vault_path="files/key", kind="login", output=None))

    assert exc_info.value.code == 1
    assert capsys.readouterr().err == "error: login retrieval is unsupported\n"
