"""Tests for pydantic models (no LLM tokens needed)."""

from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError
from pydantic_ai.models.openai import OpenAIChatModel

from carapace.llm import make_model_factory
from carapace.models import (
    AgentConfig,
    AvailableModelEntry,
    Config,
    SessionBudget,
    SessionState,
    agent_available_model_entries,
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
    assert cfg.agent.tool_output_max_chars == 16_000
    assert cfg.sandbox.network_name == "carapace-sandbox"
    ids = {e.model_id for e in cfg.agent.available_models}
    assert ids == {"anthropic:claude-sonnet-4-6", "anthropic:claude-haiku-4-5"}


def test_session_budget_zero_values_normalize_to_unlimited() -> None:
    budget = SessionBudget.model_validate(
        {"input_tokens": 0, "output_tokens": 0, "cost_usd": "0"},
    )
    assert budget.input_tokens is None
    assert budget.output_tokens is None
    assert budget.cost_usd is None
    assert budget.has_any_limit is False


def test_session_budget_accepts_decimal_cost() -> None:
    budget = SessionBudget(cost_usd=Decimal("1.25"))
    assert budget.cost_usd == Decimal("1.25")


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
    factory = make_model_factory(cfg)
    m = factory("on-prem:custom")
    assert isinstance(m, OpenAIChatModel)


def test_make_model_factory_rejects_unregistered_model():
    cfg = Config()
    factory = make_model_factory(cfg)
    with pytest.raises(ValueError, match="not registered"):
        factory("openai:gpt-4o")


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
    factory = make_model_factory(cfg)
    _ = factory("alias:opus")
    assert seen == ["anthropic:claude-opus-4-6"]


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
    assert state.private is False
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
