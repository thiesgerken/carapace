"""Tests for pydantic models (no LLM tokens needed)."""

from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIResponsesModel
from pydantic_ai.models.openrouter import OpenRouterModel
from pydantic_ai.providers.openai_codex import OpenAICodexProvider
from pydantic_ai.providers.openrouter import OpenRouterProvider

from carapace.llm import make_model_factory, model_settings_for_config, normalize_provider_prefix
from carapace.models.config import (
    AgentConfig,
    AvailableModelEntry,
    Config,
    agent_available_model_entries,
)
from carapace.models.jobs import JobCronTrigger, JobDefinition, JobsFile
from carapace.models.session import SessionBudget, SessionState
from carapace.models.user import UserConfig
from carapace.notifications.models import (
    NotificationsConfig,
    NotificationSubscription,
)
from carapace.security.context import (
    AuditEntry,
    SentinelVerdict,
    ToolCallEntry,
    UserMessageEntry,
)


def test_config_defaults():
    cfg = Config()
    assert cfg.carapace.log_level == "info"
    assert cfg.agent.model == "anthropic:claude-sonnet-4-6"
    assert cfg.agent.default_session_budget.has_any_limit is False
    assert cfg.agent.sentinel_timeout_seconds == 600
    assert cfg.agent.tool_output_max_chars == 16_000
    assert cfg.notifications.enabled is True
    assert cfg.notifications.presence_ttl_seconds == 60
    assert cfg.sandbox.network_name == "carapace-sandbox"
    ids = {e.model_id for e in cfg.agent.available_models}
    assert ids == {"anthropic:claude-sonnet-4-6", "anthropic:claude-haiku-4-5"}


def test_notification_subscription_rejects_non_normalized_user() -> None:
    with pytest.raises(ValidationError, match="username must not contain leading or trailing whitespace"):
        NotificationSubscription.model_validate(
            {
                "id": "sub-1",
                "user": " Thies ",
                "endpoint": "https://push.example.test/sub-1",
                "p256dh": "key",
                "auth": "auth",
                "subscribed_at": "2026-05-12T00:00:00Z",
                "expires_at": "2026-06-12T00:00:00Z",
            }
        )


def test_notifications_config_allows_missing_vapid_fields() -> None:
    config = NotificationsConfig.model_validate({})

    assert config.vapid_private_key is None
    assert config.vapid_subject is None


def test_job_cron_trigger_accepts_valid_expression_and_timezone() -> None:
    trigger = JobCronTrigger.model_validate({"expression": "0 9 * * *", "timezone": "Europe/Berlin"})
    assert trigger.expression == "0 9 * * *"
    assert trigger.timezone == "Europe/Berlin"


def test_job_cron_trigger_rejects_empty_expression() -> None:
    with pytest.raises(ValidationError, match="must not be empty"):
        JobCronTrigger.model_validate({"expression": "   "})


def test_job_cron_trigger_rejects_invalid_expression() -> None:
    with pytest.raises(ValidationError, match="invalid cron expression"):
        JobCronTrigger.model_validate({"expression": "not-a-cron"})


def test_job_cron_trigger_rejects_invalid_timezone() -> None:
    with pytest.raises(ValidationError, match="IANA time zone"):
        JobCronTrigger.model_validate({"expression": "0 9 * * *", "timezone": "Mars/Phobos"})


def test_job_definition_rejects_persistent_session_for_unattended_job() -> None:
    with pytest.raises(ValidationError, match="unattended must be false"):
        JobDefinition.model_validate(
            {
                "id": "morning-briefing",
                "user": "thies",
                "name": "Morning Briefing",
                "prompt": "Summarize the day.",
                "unattended": True,
                "persistent_session_id": "2026-05-09-10-00-deadbeef",
            }
        )


def test_job_definition_accepts_attended_persistent_session() -> None:
    job = JobDefinition.model_validate(
        {
            "id": "team-planning",
            "user": "thies",
            "name": "Team Planning",
            "prompt": "Continue planning.",
            "unattended": False,
            "persistent_session_id": "2026-05-09-10-00-deadbeef",
        }
    )
    assert job.persistent_session_id == "2026-05-09-10-00-deadbeef"


def test_job_definition_rejects_model_overrides_for_persistent_session() -> None:
    with pytest.raises(ValidationError, match="model overrides cannot be used"):
        JobDefinition.model_validate(
            {
                "id": "team-planning",
                "user": "thies",
                "name": "Team Planning",
                "prompt": "Continue planning.",
                "unattended": False,
                "persistent_session_id": "2026-05-09-10-00-deadbeef",
                "agent_model_name": "openai:gpt-5.4",
            }
        )


def test_job_definition_rejects_session_mode_overrides_for_persistent_session() -> None:
    with pytest.raises(ValidationError, match="session mode overrides cannot be used"):
        JobDefinition.model_validate(
            {
                "id": "team-planning",
                "user": "thies",
                "name": "Team Planning",
                "prompt": "Continue planning.",
                "unattended": False,
                "persistent_session_id": "2026-05-09-10-00-deadbeef",
                "ask_mode": True,
            }
        )


def test_job_definition_rejects_conflicting_session_modes() -> None:
    with pytest.raises(ValidationError, match="ask_mode and yolo_mode are mutually exclusive"):
        JobDefinition.model_validate(
            {
                "id": "daily-briefing",
                "user": "thies",
                "name": "Daily Briefing",
                "prompt": "Summarize the day.",
                "ask_mode": True,
                "yolo_mode": True,
            }
        )


def test_job_definition_normalizes_optional_model_overrides() -> None:
    job = JobDefinition.model_validate(
        {
            "id": "daily-briefing",
            "name": "Daily Briefing",
            "prompt": "Summarize the day.",
            "agent_model_name": "  openai:gpt-5.4  ",
            "sentinel_model_name": "   ",
            "title_model_name": " openai:gpt-5.4-mini ",
            "user": "thies",
        }
    )

    assert job.agent_model_name == "openai:gpt-5.4"
    assert job.sentinel_model_name is None
    assert job.title_model_name == "openai:gpt-5.4-mini"


def test_jobs_file_rejects_duplicate_job_ids() -> None:
    with pytest.raises(ValidationError, match="duplicate job id"):
        JobsFile.model_validate(
            {
                "jobs": [
                    {"id": "daily", "user": "thies", "name": "Daily", "prompt": "First."},
                    {"id": "daily", "user": "thies", "name": "Daily Again", "prompt": "Second."},
                ]
            }
        )


def test_session_budget_zero_values_normalize_to_unlimited() -> None:
    budget = SessionBudget.model_validate(
        {"input_tokens": 0, "output_tokens": 0, "cost_usd": "0", "tool_calls": 0},
    )
    assert budget.input_tokens is None
    assert budget.output_tokens is None
    assert budget.cost_usd is None
    assert budget.tool_calls is None
    assert budget.has_any_limit is False


def test_session_budget_accepts_decimal_cost() -> None:
    budget = SessionBudget(cost_usd=Decimal("1.25"))
    assert budget.cost_usd == Decimal("1.25")


def test_session_budget_accepts_tool_call_limit() -> None:
    budget = SessionBudget(tool_calls=7)
    assert budget.tool_calls == 7
    assert budget.has_any_limit is True


def test_user_config_types_default_models_and_budget() -> None:
    config = UserConfig.model_validate(
        {
            "default_models": {"agent": " anthropic:test ", "sentinel": "", "title": None},
            "budgets": {"cost_usd": "1.25", "tool_calls": 5},
        }
    )

    assert config.default_models.agent == "anthropic:test"
    assert config.default_models.sentinel is None
    assert config.default_models.title is None
    assert config.budgets.cost_usd == Decimal("1.25")
    assert config.budgets.tool_calls == 5


def test_available_model_entry_shorthand_string():
    e = AvailableModelEntry.model_validate("anthropic:claude-haiku-4-5")
    assert e.provider == "anthropic"
    assert e.name == "claude-haiku-4-5"
    assert e.model_id == "anthropic:claude-haiku-4-5"
    assert e.max_input_tokens is None


def test_available_model_entry_mapping_with_max_input():
    e = AvailableModelEntry.model_validate(
        {"provider": "anthropic", "name": "claude-opus-4-6", "max_input_tokens": 200_000}
    )
    assert e.model_id == "anthropic:claude-opus-4-6"
    assert e.max_input_tokens == 200_000


def test_available_model_entry_rejects_string_without_colon():
    with pytest.raises(ValidationError):
        AvailableModelEntry.model_validate("no-colon-model-id")


def test_available_model_entry_explicit_id():
    e = AvailableModelEntry.model_validate(
        {"provider": "openai", "name": "gpt-4o", "id": "corp:gpt-4o", "max_input_tokens": 128_000}
    )
    assert e.model_id == "corp:gpt-4o"
    dumped = e.model_dump(mode="json")
    assert dumped["id"] == "corp:gpt-4o"


def test_available_model_entry_dump_omits_api_key():
    e = AvailableModelEntry.model_validate(
        {"provider": "openai", "name": "llama", "api_key": {"raw": "secret"}, "base_url": "http://localhost:8000/v1"}
    )
    dumped = e.model_dump(mode="json")
    assert "api_key" not in dumped
    assert dumped["id"] == "openai:llama"


def test_available_model_entry_rejects_base_url_for_non_openai_provider():
    with pytest.raises(ValidationError):
        AvailableModelEntry.model_validate(
            {"provider": "anthropic", "name": "claude-opus-4-6", "base_url": "http://localhost:8000/v1"}
        )


def test_available_model_entry_rejects_api_key_for_non_openai_provider():
    with pytest.raises(ValidationError):
        AvailableModelEntry.model_validate(
            {"provider": "google-gla", "name": "gemini-2.5-pro", "api_key": {"raw": "secret"}}
        )


def test_available_model_entry_allows_api_key_for_openrouter_provider():
    e = AvailableModelEntry.model_validate(
        {"provider": "openrouter", "name": "anthropic/claude-sonnet-4.5", "api_key": {"raw": "secret"}}
    )

    assert e.model_id == "openrouter:anthropic/claude-sonnet-4.5"
    assert e.api_key is not None


def test_available_model_entry_rejects_base_url_for_openrouter_provider():
    with pytest.raises(ValidationError):
        AvailableModelEntry.model_validate(
            {
                "provider": "openrouter",
                "name": "anthropic/claude-sonnet-4.5",
                "base_url": "https://openrouter.ai/api/v1",
            }
        )


def test_available_model_entry_rejects_thinking_budget_tokens_for_non_openai_provider():
    with pytest.raises(ValidationError):
        AvailableModelEntry.model_validate(
            {"provider": "anthropic", "name": "claude-opus-4-6", "thinking_budget_tokens": 2048}
        )


def test_agent_config_requires_model_sentinel_title_in_available_list():
    with pytest.raises(ValidationError):
        AgentConfig.model_validate({"available_models": []})


def test_bare_id_model_when_listed_in_available_models():
    agent = AgentConfig.model_validate(
        {
            "model": "qwen3.5-35b",
            "sentinel_model": "qwen3.5-35b",
            "title_model": "qwen3.5-35b",
            "available_models": [
                {
                    "provider": "openai",
                    "name": "qwen/qwen3.5-35b-a3b",
                    "id": "qwen3.5-35b",
                    "base_url": "http://localhost:1234/v1",
                }
            ],
        }
    )
    rows = agent_available_model_entries(agent)
    by_id = {e.model_id: e for e in rows}
    assert by_id["qwen3.5-35b"].name == "qwen/qwen3.5-35b-a3b"


def test_agent_available_model_entries_last_duplicate_id_wins():
    agent = AgentConfig.model_validate(
        {
            "model": "local-b:gpt-4o",
            "sentinel_model": "local-b:gpt-4o",
            "title_model": "local-b:gpt-4o",
            "available_models": [
                {"provider": "openai", "name": "gpt-4o", "id": "local-a:gpt-4o", "base_url": "http://a/v1"},
                {"provider": "openai", "name": "gpt-4o", "id": "local-b:gpt-4o", "base_url": "http://b/v1"},
            ],
        }
    )
    rows = agent_available_model_entries(agent)
    by_id = {e.model_id: e for e in rows}
    assert by_id["local-b:gpt-4o"].base_url == "http://b/v1"
    ids = [e.model_id for e in rows]
    assert ids == sorted(ids)


def _no_codex_provider(user: str) -> OpenAICodexProvider:
    raise AssertionError(f"unexpected Codex provider lookup for {user!r}")


def test_make_model_factory_openai_compatible_row():
    cfg = Config.model_validate(
        {
            "agent": {
                "model": "anthropic:claude-sonnet-4-6",
                "sentinel_model": "anthropic:claude-sonnet-4-6",
                "title_model": "anthropic:claude-sonnet-4-6",
                "available_models": [
                    "anthropic:claude-sonnet-4-6",
                    {
                        "provider": "openai",
                        "name": "custom",
                        "id": "on-prem:custom",
                        "base_url": "http://llm/v1",
                        "api_key": {"raw": "x"},
                    },
                ],
            }
        }
    )
    factory = make_model_factory(cfg, _no_codex_provider)
    m = factory("on-prem:custom", user="thies")
    assert isinstance(m, OpenAIChatModel)


def test_make_model_factory_openai_responses_row_forces_responses_api():
    cfg = Config.model_validate(
        {
            "agent": {
                "model": "anthropic:claude-sonnet-4-6",
                "sentinel_model": "anthropic:claude-sonnet-4-6",
                "title_model": "anthropic:claude-sonnet-4-6",
                "available_models": [
                    "anthropic:claude-sonnet-4-6",
                    {
                        "provider": "openai-responses",
                        "name": "custom",
                        "id": "on-prem:custom",
                        "base_url": "http://llm/v1",
                        "api_key": {"raw": "x"},
                    },
                ],
            }
        }
    )
    factory = make_model_factory(cfg, _no_codex_provider)
    m = factory("on-prem:custom", user="thies")
    assert isinstance(m, OpenAIResponsesModel)


def test_make_model_factory_openrouter_row():
    cfg = Config.model_validate(
        {
            "agent": {
                "model": "openrouter:anthropic/claude-sonnet-4.5",
                "sentinel_model": "openrouter:anthropic/claude-sonnet-4.5",
                "title_model": "openrouter:anthropic/claude-sonnet-4.5",
                "available_models": [
                    {
                        "provider": "openrouter",
                        "name": "anthropic/claude-sonnet-4.5",
                        "api_key": {"raw": "x"},
                    },
                ],
            }
        }
    )
    factory = make_model_factory(cfg, _no_codex_provider)
    m = factory("openrouter:anthropic/claude-sonnet-4.5", user="thies")
    assert isinstance(m, OpenRouterModel)
    assert isinstance(m.provider, OpenRouterProvider)


def test_make_model_factory_rejects_unregistered_model():
    cfg = Config()
    factory = make_model_factory(cfg, _no_codex_provider)
    with pytest.raises(ValueError, match="not registered"):
        factory("openai:gpt-4o", user="thies")


def test_model_settings_for_config_enables_openrouter_usage_accounting():
    cfg = Config.model_validate(
        {
            "agent": {
                "model": "openrouter:openai/gpt-5.2",
                "sentinel_model": "openrouter:openai/gpt-5.2",
                "title_model": "openrouter:openai/gpt-5.2",
                "available_models": [
                    {
                        "provider": "openrouter",
                        "name": "openai/gpt-5.2",
                    },
                ],
            }
        }
    )

    settings = model_settings_for_config(cfg, "openrouter:openai/gpt-5.2")

    assert settings == {"openrouter_usage": {"include": True}}


def test_make_model_factory_resolves_registered_alias(monkeypatch: pytest.MonkeyPatch):
    cfg = Config.model_validate(
        {
            "agent": {
                "model": "alias:opus",
                "sentinel_model": "alias:opus",
                "title_model": "alias:opus",
                "available_models": [{"provider": "anthropic", "name": "claude-opus-4-6", "id": "alias:opus"}],
            }
        }
    )
    seen: list[str] = []

    def _fake_infer(model_name: str) -> MagicMock:
        seen.append(model_name)
        return MagicMock()

    monkeypatch.setattr("carapace.llm.infer_model_with_retry_transport", _fake_infer)
    factory = make_model_factory(cfg, _no_codex_provider)
    _ = factory("alias:opus", user="thies")
    assert seen == ["anthropic:claude-opus-4-6"]


def test_model_settings_for_config_uses_thinking_and_budget():
    cfg = Config.model_validate(
        {
            "agent": {
                "model": "local:qwen",
                "sentinel_model": "local:qwen",
                "title_model": "local:qwen",
                "available_models": [
                    {
                        "provider": "openai",
                        "name": "qwen/qwen3-32b",
                        "id": "local:qwen",
                        "base_url": "http://llm/v1",
                        "thinking": "low",
                        "thinking_budget_tokens": 2048,
                    }
                ],
            }
        }
    )

    settings = model_settings_for_config(cfg, "local:qwen", default_thinking=True)

    assert settings == {
        "thinking": "low",
        "extra_body": {"thinking_budget_tokens": 2048},
    }


def test_model_settings_for_config_defaults_thinking_when_unset():
    cfg = Config.model_validate(
        {
            "agent": {
                "model": "local:qwen",
                "sentinel_model": "local:qwen",
                "title_model": "local:qwen",
                "available_models": [
                    {
                        "provider": "openai",
                        "name": "qwen/qwen3-32b",
                        "id": "local:qwen",
                        "base_url": "http://llm/v1",
                    }
                ],
            }
        }
    )

    settings = model_settings_for_config(cfg, "local:qwen", default_thinking=True)

    assert settings == {"thinking": True}


def test_model_settings_for_config_preserves_explicit_thinking_false():
    cfg = Config.model_validate(
        {
            "agent": {
                "model": "local:qwen",
                "sentinel_model": "local:qwen",
                "title_model": "local:qwen",
                "available_models": [
                    {
                        "provider": "openai",
                        "name": "qwen/qwen3-32b",
                        "id": "local:qwen",
                        "base_url": "http://llm/v1",
                        "thinking": False,
                    }
                ],
            }
        }
    )

    settings = model_settings_for_config(cfg, "local:qwen", default_thinking=True)

    assert settings == {"thinking": False}


def test_model_settings_for_config_sets_max_tokens_for_anthropic_thinking():
    # Budget-based Anthropic thinking (haiku has no adaptive thinking) maps True -> 10000
    # budget; without a raised max_tokens, Anthropic rejects the request because
    # pydantic_ai defaults max_tokens to 4096 (<= budget).
    cfg = Config.model_validate(
        {
            "agent": {
                "model": "anthropic:claude-haiku-4-5",
                "sentinel_model": "anthropic:claude-haiku-4-5",
                "title_model": "anthropic:claude-haiku-4-5",
                "available_models": [{"provider": "anthropic", "name": "claude-haiku-4-5"}],
            }
        }
    )

    settings = model_settings_for_config(cfg, "anthropic:claude-haiku-4-5", default_thinking=True)

    assert settings == {"thinking": True, "max_tokens": 10000 + 8192}


def test_model_settings_for_config_no_max_tokens_for_non_anthropic_thinking():
    cfg = Config.model_validate(
        {
            "agent": {
                "model": "local:qwen",
                "sentinel_model": "local:qwen",
                "title_model": "local:qwen",
                "available_models": [
                    {
                        "provider": "openai",
                        "name": "qwen/qwen3-32b",
                        "id": "local:qwen",
                        "base_url": "http://llm/v1",
                    }
                ],
            }
        }
    )

    settings = model_settings_for_config(cfg, "local:qwen", default_thinking=True)

    assert "max_tokens" not in (settings or {})


def test_agent_config_mixed_available_models():
    ac = AgentConfig.model_validate(
        {
            "model": "google-gla:gemini-3-flash-preview",
            "sentinel_model": "google-gla:gemini-3-flash-preview",
            "title_model": "google-gla:gemini-3-flash-preview",
            "available_models": [
                "google-gla:gemini-3-flash-preview",
                {"provider": "anthropic", "name": "claude-opus-4-6", "max_input_tokens": 128_000},
            ],
        }
    )
    assert len(ac.available_models) == 2
    assert ac.available_models[0].model_id == "google-gla:gemini-3-flash-preview"
    assert ac.available_models[1].max_input_tokens == 128_000


def test_session_state_defaults():
    state = SessionState.now(session_id="abc123")
    assert state.channel_type == "cli"
    assert state.context_grants == {}
    assert state.attributes.private is False
    assert state.knowledge_last_committed_at is None


def test_sentinel_verdict():
    v = SentinelVerdict(decision="allow", explanation="safe operation", risk_level="low")
    assert v.decision == "allow"
    assert v.risk_level == "low"


def test_tool_call_entry():
    entry = ToolCallEntry(tool="exec", args={"command": "ls"}, decision="auto_allowed")
    assert entry.type == "tool_call"
    assert entry.tool == "exec"


def test_user_message_entry():
    entry = UserMessageEntry(content="hello")
    assert entry.type == "user_message"
    assert entry.content == "hello"


def test_audit_entry():
    entry = AuditEntry.now(kind="tool_call", tool="exec", final_decision="auto_allowed")
    assert entry.kind == "tool_call"
    assert entry.sentinel_verdict is None


def test_normalize_provider_prefix():
    # Legacy v1 google prefixes rewrite to their v2 names.
    assert normalize_provider_prefix("google-gla:gemini-2.0-flash") == "google:gemini-2.0-flash"
    assert normalize_provider_prefix("google-vertex:gemini-2.0-flash") == "google-cloud:gemini-2.0-flash"
    # Everything else (including current names and colons in the model name) is untouched.
    assert normalize_provider_prefix("anthropic:claude-opus-4-8") == "anthropic:claude-opus-4-8"
    assert normalize_provider_prefix("google:gemini-2.0-flash") == "google:gemini-2.0-flash"
    assert normalize_provider_prefix("openai:gpt-4o") == "openai:gpt-4o"


def test_model_construction_without_provider_key(monkeypatch):
    # A fresh install has no credentials yet; construction must still succeed so the admin can
    # boot the server and configure the catalog (the auth failure lands on the first request).
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from carapace.llm import infer_model_with_retry_transport

    model = infer_model_with_retry_transport("anthropic:claude-sonnet-4-6")
    assert model.model_name == "claude-sonnet-4-6"
