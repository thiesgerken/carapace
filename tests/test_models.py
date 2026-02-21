"""Tests for pydantic models (no LLM tokens needed)."""

from carapace.models import (
    Config,
    OperationClassification,
    Rule,
    RuleCheckResult,
    RuleMode,
    SessionState,
)


def test_rule_defaults():
    rule = Rule(id="r1", trigger="always", effect="require approval")
    assert rule.mode == RuleMode.approve
    assert rule.description == ""


def test_rule_block_mode():
    rule = Rule(id="r1", trigger="always", effect="block", mode=RuleMode.block)
    assert rule.mode == RuleMode.block


def test_config_defaults():
    cfg = Config()
    assert cfg.carapace.log_level == "info"
    assert cfg.agent.model == "openai:gpt-4o-mini"
    assert cfg.credentials.backend == "mock"
    assert cfg.sandbox.enabled is False
    assert cfg.sandbox.network_name == "carapace-sandbox"
    assert cfg.memory.search.enabled is False
    assert cfg.sessions.history_retention_days == 90


def test_session_state_defaults():
    state = SessionState(session_id="abc123")
    assert state.channel_type == "cli"
    assert state.activated_rules == []
    assert state.disabled_rules == []
    assert state.approved_credentials == []


def test_operation_classification():
    op = OperationClassification(
        operation_type="read_local",
        categories=["filesystem"],
        description="reading a file",
    )
    assert op.operation_type == "read_local"
    assert op.confidence == 1.0


def test_rule_check_result_defaults():
    result = RuleCheckResult()
    assert result.needs_approval is False
    assert result.triggered_rules == []
    assert result.newly_activated_rules == []
    assert result.descriptions == []
