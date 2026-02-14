"""CLI smoke tests (no LLM tokens needed)."""

from typer.testing import CliRunner

from carapace.cli import app

runner = CliRunner()


def test_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Carapace" in result.output


def test_chat_help():
    result = runner.invoke(app, ["chat", "--help"])
    assert result.exit_code == 0
    assert "--session" in result.output
    assert "--data-dir" in result.output
