"""Tests for config building (env-only, no config file; no LLM tokens needed)."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from carapace.config import (
    build_config,
    load_workspace_file,
    resolve_knowledge_repos_dir,
    resolve_user_knowledge_dir,
)
from carapace.llm import resolve_available_model_entry
from carapace.models.config import AgentConfig, AuthConfig, AvailableModelEntry, Config, SandboxConfig
from carapace.notifications.models import NotificationsConfig


def test_build_config_defaults(tmp_path: Path):
    cfg = build_config(tmp_path)
    assert cfg.data_dir == str(tmp_path)
    assert cfg.carapace.log_level == "info"
    assert cfg.cache.ttl_seconds == 1800
    assert cfg.cache.redis_url == "redis://localhost:6379/0"
    assert cfg.agent.model == "anthropic:claude-sonnet-4-6"
    assert cfg.sessions.commit.enabled is True
    assert cfg.sandbox.k8s_session_pvc_size == "1Gi"
    assert cfg.sandbox.skill_activator is None
    assert cfg.sandbox.skill_activator_timeout_seconds == 600


def test_build_config_reads_data_dir_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CARAPACE_DATA_DIR", str(tmp_path))
    assert build_config().data_dir == str(tmp_path.resolve())


def test_auth_cookie_secure_from_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CARAPACE_AUTH_COOKIE__SECURE", "true")
    assert AuthConfig().cookie.secure is True


def test_build_config_applies_subsection_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Regression: env set after import must reach the subsections (default_factory, not a
    # shared import-time instance). load_dotenv() in the server module runs before any
    # build_config() call, so .env values must apply too.
    monkeypatch.setenv("CARAPACE_AUTH_COOKIE__SECURE", "true")
    monkeypatch.setenv("CARAPACE_NOTIFICATIONS_VAPID_SUBJECT", "mailto:ops@example.com")
    cfg = build_config(tmp_path)
    assert cfg.auth.cookie.secure is True
    assert cfg.notifications.vapid_subject == "mailto:ops@example.com"


def test_notifications_vapid_subject_from_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CARAPACE_NOTIFICATIONS_VAPID_SUBJECT", "mailto:ops@example.com")
    assert NotificationsConfig().vapid_subject == "mailto:ops@example.com"


def test_sandbox_skill_activator_from_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CARAPACE_SANDBOX_SKILL_ACTIVATOR", "/usr/local/bin/activate-skill")
    monkeypatch.setenv("CARAPACE_SANDBOX_SKILL_ACTIVATOR_TIMEOUT_SECONDS", "900")
    config = SandboxConfig()
    assert config.skill_activator == "/usr/local/bin/activate-skill"
    assert config.skill_activator_timeout_seconds == 900


@pytest.mark.parametrize(
    "path",
    ["activate-skill", "/workspace/activate-skill", "/tmp/activate-skill", "/usr/../tmp/x"],
)
def test_sandbox_skill_activator_rejects_untrusted_paths(path: str):
    with pytest.raises(ValidationError):
        SandboxConfig(skill_activator=path)


@pytest.mark.parametrize(
    "raw",
    [
        {"channels": {"matrix": {"enabled": True}}},
        {"git": {"remote": "https://gitea.example.com/team/knowledge.git"}},
        {"credentials": {"backends": {"vault": {"type": "bitwarden"}}}},
        {"agent": {"unexpected_key": True}},
    ],
)
def test_config_rejects_unknown_keys(raw: dict):
    with pytest.raises(ValidationError):
        Config.model_validate(raw)


def test_load_workspace_file_missing(tmp_path: Path):
    result = load_workspace_file(tmp_path, "SECURITY.md")
    assert result == ""


def test_load_workspace_file(tmp_path: Path):
    (tmp_path / "SECURITY.md").write_text("# Test Policy\nBe safe.")
    result = load_workspace_file(tmp_path, "SECURITY.md")
    assert "Test Policy" in result


def test_resolve_knowledge_repos_dir_uses_knowledges_under_data_dir(tmp_path: Path) -> None:
    assert resolve_knowledge_repos_dir(tmp_path) == (tmp_path / "knowledges").resolve()


def test_resolve_knowledge_repos_dir_uses_explicit_root(tmp_path: Path) -> None:
    explicit = tmp_path / "legacy-knowledge"
    assert resolve_knowledge_repos_dir(tmp_path, explicit) == explicit.resolve()


def test_resolve_user_knowledge_dir_uses_normalized_username(tmp_path: Path) -> None:
    assert resolve_user_knowledge_dir(tmp_path, "thies") == (tmp_path / "knowledges" / "thies").resolve()


def test_resolve_user_knowledge_dir_uses_explicit_root(tmp_path: Path) -> None:
    explicit = tmp_path / "legacy-knowledge"
    assert resolve_user_knowledge_dir(tmp_path, "thies", knowledge_repos_dir=explicit) == (explicit / "thies").resolve()


def test_resolve_user_knowledge_dir_rejects_noncanonical_username(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="username must be lowercase"):
        resolve_user_knowledge_dir(tmp_path, "Thies")


def test_disabled_model_is_rejected_by_the_llm_path(tmp_path: Path) -> None:
    cfg = build_config(tmp_path)
    cfg.agent.available_models.append(
        AvailableModelEntry.model_validate({"provider": "anthropic", "name": "claude-opus-4-1", "enabled": False})
    )
    with pytest.raises(ValueError, match="is disabled"):
        resolve_available_model_entry(cfg, "anthropic:claude-opus-4-1")


def test_platform_default_cannot_point_at_a_disabled_model() -> None:
    with pytest.raises(ValidationError, match="refers to a disabled model"):
        AgentConfig.model_validate(
            {
                "model": "anthropic:claude-sonnet-4-6",
                "sentinel_model": "anthropic:claude-sonnet-4-6",
                "title_model": "anthropic:claude-sonnet-4-6",
                "available_models": [{"provider": "anthropic", "name": "claude-sonnet-4-6", "enabled": False}],
            }
        )
