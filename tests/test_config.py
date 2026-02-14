"""Tests for config loading (no LLM tokens needed)."""

from pathlib import Path

from carapace.config import load_config, load_rules


def test_load_config_defaults(tmp_path: Path):
    cfg = load_config(tmp_path)
    assert cfg.carapace.log_level == "info"
    assert cfg.agent.model == "openai:gpt-4o-mini"


def test_load_config_from_yaml(tmp_path: Path):
    (tmp_path / "config.yaml").write_text(
        "agent:\n  model: anthropic:claude-sonnet-4-5\n  classifier_model: anthropic:claude-haiku-4-5\n"
    )
    cfg = load_config(tmp_path)
    assert cfg.agent.model == "anthropic:claude-sonnet-4-5"
    assert cfg.agent.classifier_model == "anthropic:claude-haiku-4-5"


def test_load_rules_empty(tmp_path: Path):
    rules = load_rules(tmp_path)
    assert rules == []


def test_load_rules_from_yaml(tmp_path: Path):
    (tmp_path / "rules.yaml").write_text(
        "rules:\n"
        "  - id: test-rule\n"
        "    trigger: always\n"
        "    effect: require approval for all writes\n"
        "    mode: approve\n"
        "    description: Test rule\n"
    )
    rules = load_rules(tmp_path)
    assert len(rules) == 1
    assert rules[0].id == "test-rule"
    assert rules[0].trigger == "always"
