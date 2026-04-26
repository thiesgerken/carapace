"""Tests for config loading (no LLM tokens needed)."""

from pathlib import Path

from carapace.config import load_config, load_workspace_file


def test_load_config_defaults(tmp_path: Path):
    cfg = load_config(tmp_path)
    assert cfg.carapace.log_level == "info"
    assert cfg.agent.model == "anthropic:claude-sonnet-4-6"
    assert cfg.sessions.default_private is False
    assert cfg.sessions.commit.enabled is True
    assert cfg.sessions.commit.autosave_inactivity_hours == 4
    assert cfg.sandbox.k8s_session_pvc_size == "1Gi"
    assert cfg.sandbox.k8s_session_pvc_storage_class == ""


def test_load_config_from_yaml(tmp_path: Path):
    (tmp_path / "config.yaml").write_text(
        "agent:\n  model: anthropic:claude-sonnet-4-6\n  sentinel_model: anthropic:claude-haiku-4-5\n"
        "  tool_output_max_chars: 5000\n"
    )
    cfg = load_config(tmp_path)
    assert cfg.agent.model == "anthropic:claude-sonnet-4-6"
    assert cfg.agent.sentinel_model == "anthropic:claude-haiku-4-5"
    assert cfg.agent.tool_output_max_chars == 5000


def test_load_workspace_file_missing(tmp_path: Path):
    result = load_workspace_file(tmp_path, "SECURITY.md")
    assert result == ""


def test_load_workspace_file(tmp_path: Path):
    (tmp_path / "SECURITY.md").write_text("# Test Policy\nBe safe.")
    result = load_workspace_file(tmp_path, "SECURITY.md")
    assert "Test Policy" in result
