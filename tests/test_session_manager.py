"""Tests for SessionManager persistence and small session helpers."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from carapace.models import ContextGrant, SessionAttributes, SessionBudget, SkillCredentialDecl
from carapace.sandbox.state import SessionSandboxSnapshot
from carapace.security.context import (
    SessionSecurity,
    UserEscalationDecision,
    format_denial_message,
    normalize_optional_message,
)
from carapace.session import SessionManager
from carapace.usage import LlmRequestState


def test_create_session(tmp_path: Path):
    mgr = SessionManager(tmp_path)
    state = mgr.create_session()
    assert len(state.session_id) == 25  # 2026-03-08-10-22-abcd1234
    assert state.channel_type == "cli"
    assert state.attributes == SessionAttributes()


def test_create_session_persists_budget(tmp_path: Path):
    mgr = SessionManager(tmp_path)
    budget = SessionBudget(input_tokens=1_000, cost_usd=Decimal("5.00"), tool_calls=4)
    state = mgr.create_session(budget=budget)

    resumed = mgr.resume_session(state.session_id)
    assert resumed is not None
    assert resumed.budget.input_tokens == 1_000
    assert resumed.budget.cost_usd == Decimal("5.00")
    assert resumed.budget.tool_calls == 4


def test_create_session_persists_private_attribute(tmp_path: Path):
    mgr = SessionManager(tmp_path)
    state = mgr.create_session(private=True)

    resumed = mgr.resume_session(state.session_id)
    assert resumed is not None
    assert resumed.attributes.private is True


def test_resume_session(tmp_path: Path):
    mgr = SessionManager(tmp_path)
    state = mgr.create_session()
    resumed = mgr.resume_session(state.session_id)
    assert resumed is not None
    assert resumed.session_id == state.session_id


def test_update_events_timestamps_inserted_and_replaced_entries(tmp_path: Path):
    mgr = SessionManager(tmp_path)
    state = mgr.create_session()
    mgr.save_events(
        state.session_id,
        [
            {"role": "user", "content": "first", "timestamp": "2026-01-01T00:00:00+00:00"},
            {"role": "assistant", "content": "second", "timestamp": "2026-01-01T00:00:01+00:00"},
        ],
    )

    def _mutate(events: list[dict[str, object]]) -> None:
        events.insert(0, {"role": "thinking", "content": "inserted"})
        events[2] = {"role": "assistant", "content": "replaced"}

    mgr.update_events(state.session_id, _mutate)

    events = mgr.load_events(state.session_id)
    assert events[0]["role"] == "thinking"
    assert "timestamp" in events[0]
    assert events[1]["timestamp"] == "2026-01-01T00:00:00+00:00"
    assert events[2]["role"] == "assistant"
    assert events[2]["content"] == "replaced"
    assert "timestamp" in events[2]


def test_resume_nonexistent(tmp_path: Path):
    mgr = SessionManager(tmp_path)
    assert mgr.resume_session("doesnotexist") is None


def test_list_sessions(tmp_path: Path):
    mgr = SessionManager(tmp_path)
    s1 = mgr.create_session()
    s2 = mgr.create_session()
    sessions = mgr.list_sessions()
    assert s1.session_id in sessions
    assert s2.session_id in sessions


def test_save_and_resume_state(tmp_path: Path):
    mgr = SessionManager(tmp_path)
    state = mgr.create_session()
    state.context_grants["my-skill"] = ContextGrant(
        skill_name="my-skill",
        domains={"example.com"},
        credential_decls=[SkillCredentialDecl(vault_path="dev/test", description="test cred")],
    )
    mgr.save_state(state)

    resumed = mgr.resume_session(state.session_id)
    assert resumed is not None
    assert "my-skill" in resumed.context_grants
    assert "dev/test" in resumed.context_grants["my-skill"].vault_paths


def test_save_and_load_llm_request_state(tmp_path: Path) -> None:
    mgr = SessionManager(tmp_path)
    state = mgr.create_session()
    activity = LlmRequestState(
        request_id="req-1",
        source="agent",
        model_name="anthropic:claude-haiku-4-5",
        started_at=datetime.now(tz=UTC),
        phase="processing_prompt",
    )

    mgr.save_llm_request_state(state.session_id, activity)

    reloaded = mgr.load_llm_request_state(state.session_id)
    assert reloaded is not None
    assert reloaded.request_id == "req-1"
    assert reloaded.phase == "processing_prompt"

    mgr.clear_llm_request_state(state.session_id)
    assert mgr.load_llm_request_state(state.session_id) is None


def test_save_and_load_sandbox_snapshot(tmp_path: Path) -> None:
    mgr = SessionManager(tmp_path)
    state = mgr.create_session()
    snapshot = SessionSandboxSnapshot(
        exists=True,
        runtime="kubernetes",
        status="scaled_down",
        resource_id="carapace-sandbox-abc-0",
        resource_kind="statefulset",
        storage_present=True,
        provisioned_bytes=1_073_741_824,
        last_measured_used_bytes=123_456,
        last_measured_at=datetime.now(tz=UTC),
        updated_at=datetime.now(tz=UTC),
    )

    mgr.save_sandbox_snapshot(state.session_id, snapshot)

    reloaded = mgr.load_sandbox_snapshot(state.session_id)
    assert reloaded is not None
    assert reloaded.runtime == "kubernetes"
    assert reloaded.status == "scaled_down"
    assert reloaded.last_measured_used_bytes == 123_456

    mgr.clear_sandbox_snapshot(state.session_id)
    assert mgr.load_sandbox_snapshot(state.session_id) is None


def test_normalize_optional_message_strips_blank_values() -> None:
    assert normalize_optional_message(None) is None
    assert normalize_optional_message("   ") is None
    assert normalize_optional_message("  blocked by user  ") == "blocked by user"


def test_format_denial_message_includes_source_and_message() -> None:
    assert format_denial_message("sentinel", "dangerous command") == (
        "Sentinel denied this operation. dangerous command"
    )
    assert format_denial_message("user", None) == "User denied this operation."


def test_missing_user_escalation_callback_denies() -> None:
    security = SessionSecurity("session-1")
    result = asyncio.run(security.escalate_to_user("example.com", {"kind": "domain_access"}))
    assert result == UserEscalationDecision(allowed=False)
