"""CLI smoke tests (no LLM tokens needed)."""

import asyncio
import re
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from carapace.cli import _render_proxy_approval_request, app

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
    assert "--server" in output
    assert "--token" in output


@pytest.mark.parametrize(
    ("choice", "expected"),
    [
        ("o", "allow_once"),
        ("O", "allow_all_once"),
        ("once", "allow_once"),
        ("t", "allow_15min"),
        ("T", "allow_all_15min"),
        ("timed", "allow_15min"),
        ("d", "deny"),
    ],
)
def test_proxy_approval_choice_mapping(choice: str, expected: str):
    with patch("carapace.cli.console.input", return_value=choice):
        decision = asyncio.run(_render_proxy_approval_request({"domain": "example.com", "command": "curl"}))
    assert decision == expected
