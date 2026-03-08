"""Tests for pydantic models (no LLM tokens needed)."""

from carapace.models import (
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
    assert cfg.agent.model == "openai:gpt-4o-mini"
    assert cfg.credentials.backend == "mock"
    assert cfg.sandbox.network_name == "carapace-sandbox"
    assert cfg.memory.search.enabled is False
    assert cfg.sessions.history_retention_days == 90


def test_session_state_defaults():
    state = SessionState(session_id="abc123")
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
    entry = AuditEntry(kind="tool_call", tool="exec", final_decision="auto_allowed")
    assert entry.kind == "tool_call"
    assert entry.sentinel_verdict is None
