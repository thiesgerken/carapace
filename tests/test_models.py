"""Tests for pydantic models (no LLM tokens needed)."""

import pytest
from pydantic import ValidationError

from carapace.models import (
    AgentConfig,
    AvailableModelEntry,
    Config,
    SessionState,
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
    assert cfg.sandbox.network_name == "carapace-sandbox"


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


def test_agent_config_mixed_available_models():
    ac = AgentConfig.model_validate(
        {
            "available_models": [
                "google-gla:gemini-3-flash-preview",
                {"provider": "anthropic", "name": "claude-opus-4-6", "max_input_tokens": 128_000},
            ]
        }
    )
    assert len(ac.available_models) == 2
    assert ac.available_models[0].model_id == "google-gla:gemini-3-flash-preview"
    assert ac.available_models[1].max_input_tokens == 128_000


def test_session_state_defaults():
    state = SessionState.now(session_id="abc123")
    assert state.channel_type == "cli"
    assert state.approved_credentials == []


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
