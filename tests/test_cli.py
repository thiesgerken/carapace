"""CLI smoke tests (no LLM tokens needed)."""

import asyncio
import re
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from carapace.cli import _render_escalation_request, app

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
    assert "--token" in output


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
