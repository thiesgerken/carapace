"""Tests for config loading (no LLM tokens needed)."""

from pathlib import Path

from carapace.config import load_config, load_security_md


def test_load_config_defaults(tmp_path: Path):
    cfg = load_config(tmp_path)
    assert cfg.carapace.log_level == "info"
    assert cfg.agent.model == "openai:gpt-4o-mini"


def test_load_config_from_yaml(tmp_path: Path):
    (tmp_path / "config.yaml").write_text(
        "agent:\n  model: anthropic:claude-sonnet-4-5\n  bouncer_model: anthropic:claude-haiku-4-5\n"
    )
    cfg = load_config(tmp_path)
    assert cfg.agent.model == "anthropic:claude-sonnet-4-5"
    assert cfg.agent.bouncer_model == "anthropic:claude-haiku-4-5"


def test_load_security_md_missing(tmp_path: Path):
    result = load_security_md(tmp_path)
    assert result == ""


def test_load_security_md(tmp_path: Path):
    (tmp_path / "SECURITY.md").write_text("# Test Policy\nBe safe.")
    result = load_security_md(tmp_path)
    assert "Test Policy" in result
