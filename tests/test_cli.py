"""CLI smoke tests (no LLM tokens needed)."""

import re

from typer.testing import CliRunner

from carapace.cli import app

runner = CliRunner()

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def test_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Carapace" in _strip_ansi(result.output)


def test_chat_help():
    result = runner.invoke(app, ["chat", "--help"])
    assert result.exit_code == 0
    output = _strip_ansi(result.output)
    assert "--session" in output
    assert "--data-dir" in output
