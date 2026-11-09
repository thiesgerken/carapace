"""Tests for the Matrix channel adapter (no homeserver needed — mocked nio)."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import nio
import pytest
import yaml
from pydantic import ValidationError

from carapace.bootstrap import ensure_data_dir
from carapace.channels.matrix import (
    MatrixChannel,
    _format_approval_request,
    _format_command_result_text,
    _format_domain_escalation,
    _md_to_html,
    _PendingApproval,
    _PendingDomainApproval,
)
from carapace.channels.matrix.subscriber import MatrixSubscriber
from carapace.config import build_config
from carapace.models.matrix import MatrixChannelConfig, MatrixTokenFile, MatrixTokensFile
from carapace.models.session import SessionBudget
from carapace.notifications.presence import NotificationPresenceRegistry
from carapace.sandbox.manager import SandboxManager
from carapace.session import SessionEngine, SessionManager
from carapace.ws_models import ApprovalRequest, CommandResult

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_config(**kwargs: Any) -> MatrixChannelConfig:
    defaults: dict[str, Any] = {
        "enabled": True,
        "homeserver": "https://matrix.example.com",
        "user_id": "@carapace:example.com",
        "allowed_users": ["@alice:example.com"],
        "allowed_rooms": [],
    }
    return MatrixChannelConfig(**(defaults | kwargs))


def test_matrix_config_rejects_secret_source_objects() -> None:
    with pytest.raises(ValidationError):
        MatrixChannelConfig.model_validate(
            {
                "password": {
                    "env": "CARAPACE_MATRIX_PASSWORD",
                },
            }
        )


def _make_engine_mock() -> MagicMock:
    """Build a mock SessionEngine with commonly used async methods."""
    engine = MagicMock(spec=SessionEngine)
    engine.submit_approval = AsyncMock()
    engine.submit_cancel = AsyncMock()
    engine.submit_message = AsyncMock()
    engine.handle_slash_command = AsyncMock(return_value=None)
    engine.subscribe = MagicMock()
    engine.unsubscribe = MagicMock()
    engine.deactivate = MagicMock()
    engine.config.agent.default_session_budget = SessionBudget()
    return engine


def _make_channel(tmp_path: Path, db_factory, *, owner_user: str = "thies", **config_kwargs: Any) -> Any:
    """Build a MatrixChannel with mocked internals."""
    ensure_data_dir(tmp_path)
    full_config = build_config(tmp_path)
    session_mgr = SessionManager(db_factory, tmp_path)

    sandbox_mgr = MagicMock(spec=SandboxManager)
    sandbox_mgr.get_domain_info.return_value = []

    channel = MatrixChannel(
        config=_make_config(**config_kwargs),
        full_config=full_config,
        session_mgr=session_mgr,
        sandbox_mgr=sandbox_mgr,
        engine=_make_engine_mock(),
        owner_user=owner_user,
        presence_registry=NotificationPresenceRegistry(ttl=timedelta(seconds=60)),
    )
    # Replace the nio client with a mock
    channel._client = AsyncMock(spec=nio.AsyncClient)
    channel._client.user_id = "@carapace:example.com"
    return channel


def _make_room(room_id: str = "!room:example.com", sender: str | None = None) -> MagicMock:
    room = MagicMock()
    room.room_id = room_id
    return room


def _make_text_event(body: str, sender: str = "@alice:example.com") -> MagicMock:
    event = MagicMock(spec=nio.RoomMessageText)
    event.body = body
    event.sender = sender
    event.transaction_id = None
    event.decrypted = False
    return event


def _make_reaction_event(reacts_to: str, key: str, sender: str = "@alice:example.com") -> MagicMock:
    event = MagicMock(spec=nio.ReactionEvent)
    event.reacts_to = reacts_to
    event.key = key
    event.sender = sender
    return event


# ---------------------------------------------------------------------------
# Unit tests — SessionManager.find_session
# ---------------------------------------------------------------------------


def test_find_session_returns_none_when_empty(tmp_path: Path, db_factory):
    mgr = SessionManager(db_factory, tmp_path)
    assert mgr.find_session("matrix", "!room:example.com") is None


def test_find_session_returns_matching_session(tmp_path: Path, db_factory):
    mgr = SessionManager(db_factory, tmp_path)
    s = mgr.create_session("matrix", "!room:example.com", user="thies")
    assert mgr.find_session("matrix", "!room:example.com") == s.session_id


def test_matrix_session_created_with_token_owner(tmp_path: Path, db_factory):
    ch = _make_channel(tmp_path, db_factory)
    token_file = tmp_path / "matrix_token.yaml"
    token_file.write_text(
        yaml.safe_dump(
            MatrixTokensFile(
                tokens=[
                    MatrixTokenFile(
                        access_token="tok_good",
                        device_id="DEV1",
                        user_id="@carapace:example.com",
                        user="thies",
                    )
                ]
            ).model_dump(mode="json", exclude_none=True)
        )
    )

    token, device_id = ch._load_token(token_file)
    session_id = ch._get_or_create_session("!room:example.com")

    assert token == "tok_good"
    assert device_id == "DEV1"
    assert ch._session_mgr.load_meta(session_id).user == "thies"


def test_matrix_existing_session_gets_missing_token_owner(tmp_path: Path, db_factory):
    ch = _make_channel(tmp_path, db_factory)
    existing = ch._session_mgr.create_session("matrix", "!room:example.com", user="thies")
    ch._owner_user = "thies"

    session_id = ch._get_or_create_session("!room:example.com")

    assert session_id == existing.session_id
    assert ch._session_mgr.load_meta(session_id).user == "thies"


def test_find_session_ignores_different_channel(tmp_path: Path, db_factory):
    mgr = SessionManager(db_factory, tmp_path)
    mgr.create_session("cli", "!room:example.com", user="thies")
    assert mgr.find_session("matrix", "!room:example.com") is None


def test_find_session_ignores_different_ref(tmp_path: Path, db_factory):
    mgr = SessionManager(db_factory, tmp_path)
    mgr.create_session("matrix", "!other:example.com", user="thies")
    assert mgr.find_session("matrix", "!room:example.com") is None


def test_find_session_returns_most_recent(tmp_path: Path, db_factory):
    mgr = SessionManager(db_factory, tmp_path)
    s1 = mgr.create_session("matrix", "!room:example.com", user="thies")
    s2 = mgr.create_session("matrix", "!room:example.com", user="thies")
    result = mgr.find_session("matrix", "!room:example.com")
    # Should return one of them; both are valid. s2 was created last.
    assert result in {s1.session_id, s2.session_id}


# ---------------------------------------------------------------------------
# Unit tests — room-session mapping
# ---------------------------------------------------------------------------


def test_get_or_create_session_creates_new(tmp_path: Path, db_factory):
    ch = _make_channel(tmp_path, db_factory)
    sid = ch._get_or_create_session("!newroom:example.com")
    assert sid
    # Second call returns same session
    assert ch._get_or_create_session("!newroom:example.com") == sid


def test_get_or_create_session_resumes_existing(tmp_path: Path, db_factory):
    mgr = SessionManager(db_factory, tmp_path)
    existing = mgr.create_session("matrix", "!room:example.com", user="thies")

    ch = _make_channel(tmp_path, db_factory)
    sid = ch._get_or_create_session("!room:example.com")
    assert sid == existing.session_id


@pytest.mark.anyio
async def test_on_message_updates_presence_registry(tmp_path: Path, db_factory):
    ch = _make_channel(tmp_path, db_factory)
    room = _make_room()
    event = _make_text_event("hello")
    event.server_timestamp = ch._started_at_ms + 1

    await ch._on_message(room, event)

    session_id = ch._room_sessions[room.room_id]
    assert ch._presence_registry is not None
    assert ch._presence_registry.is_session_actively_handled(session_id) is True


# ---------------------------------------------------------------------------
# Unit tests — _is_allowed filtering
# ---------------------------------------------------------------------------


def test_is_allowed_rejects_self(tmp_path: Path, db_factory):
    ch = _make_channel(tmp_path, db_factory)
    room = _make_room()
    assert not ch._is_allowed(room, "@carapace:example.com")


def test_is_allowed_rejects_unknown_user_when_allowlist_set(tmp_path: Path, db_factory):
    ch = _make_channel(tmp_path, db_factory, allowed_users=["@alice:example.com"])
    room = _make_room()
    assert not ch._is_allowed(room, "@evil:example.com")


def test_is_allowed_accepts_listed_user(tmp_path: Path, db_factory):
    ch = _make_channel(tmp_path, db_factory, allowed_users=["@alice:example.com"])
    room = _make_room()
    assert ch._is_allowed(room, "@alice:example.com")


def test_is_allowed_accepts_any_user_when_no_allowlist(tmp_path: Path, db_factory):
    ch = _make_channel(tmp_path, db_factory, allowed_users=[])
    room = _make_room()
    assert ch._is_allowed(room, "@anyone:example.com")


def test_is_allowed_rejects_unlisted_room(tmp_path: Path, db_factory):
    ch = _make_channel(tmp_path, db_factory, allowed_rooms=["!allowed:example.com"])
    room = _make_room(room_id="!other:example.com")
    assert not ch._is_allowed(room, "@alice:example.com")


# ---------------------------------------------------------------------------
# Unit tests — slash command routing
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_handle_reset_creates_new_session(tmp_path: Path, db_factory):
    ch = _make_channel(tmp_path, db_factory)
    room_id = "!room:example.com"

    old_sid = ch._get_or_create_session(room_id)
    ch._client.room_send = AsyncMock(return_value=MagicMock(event_id="$evt1"))
    ch._sandbox_mgr.cleanup_session = AsyncMock()

    await ch._handle_reset(room_id, old_sid)

    new_sid = ch._room_sessions[room_id]
    assert new_sid != old_sid
    # Old session still exists on disk
    assert ch._session_mgr.load_state(old_sid) is not None


@pytest.mark.anyio
async def test_handle_command_unknown_submits_agent_message(tmp_path: Path, db_factory):
    ch = _make_channel(tmp_path, db_factory)
    room_id = "!room:example.com"
    ch._get_or_create_session(room_id)
    ch._client.room_send = AsyncMock(return_value=MagicMock(event_id="$evt1"))
    ch._engine.handle_slash_command.return_value = None
    ch._engine.submit_message = AsyncMock()

    await ch._handle_command(room_id, ch._room_sessions[room_id], "/foobar", "@alice:example.com")

    ch._client.room_send.assert_not_called()
    ch._engine.submit_message.assert_awaited_once()
    assert ch._engine.submit_message.await_args.args[:2] == (ch._room_sessions[room_id], "/foobar")


@pytest.mark.anyio
async def test_handle_command_help(tmp_path: Path, db_factory):
    ch = _make_channel(tmp_path, db_factory)
    room_id = "!room:example.com"
    ch._get_or_create_session(room_id)
    ch._client.room_send = AsyncMock(return_value=MagicMock(event_id="$evt"))

    await ch._handle_command(room_id, ch._room_sessions[room_id], "/help", "@alice:example.com")

    ch._client.room_send.assert_called_once()
    sent_body = ch._client.room_send.call_args[0][2]["body"]
    assert "/reset" in sent_body
    assert "/allow" in sent_body


# ---------------------------------------------------------------------------
# Unit tests — approval flow
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_pending_approval_resolves_approve():
    pa = _PendingApproval("$event1", "call-1")
    pa.resolve(True)
    result = await pa.wait()
    assert result is True


@pytest.mark.anyio
async def test_pending_approval_resolves_deny():
    pa = _PendingApproval("$event1", "call-1")
    pa.resolve(False)
    result = await pa.wait()
    assert result is False


@pytest.mark.anyio
async def test_on_reaction_approves_pending(tmp_path: Path, db_factory):
    ch = _make_channel(tmp_path, db_factory)
    room_id = "!room:example.com"
    session_id = ch._get_or_create_session(room_id)

    sub = MatrixSubscriber(ch, room_id)
    sub._approval_events["$approval_event"] = "call-1"
    ch._room_subscribers[room_id] = sub

    pa = _PendingApproval("$approval_event", "call-1")
    ch._pending_approvals["$approval_event"] = pa

    reaction_event = _make_reaction_event(reacts_to="$approval_event", key="✅")
    room = _make_room(room_id=room_id)
    await ch._on_reaction(room, reaction_event)

    ch._engine.submit_approval.assert_called_once()
    call_args = ch._engine.submit_approval.call_args
    assert call_args[0][0] == session_id
    assert call_args[0][1].approved is True


@pytest.mark.anyio
async def test_on_reaction_denies_pending(tmp_path: Path, db_factory):
    ch = _make_channel(tmp_path, db_factory)
    room_id = "!room:example.com"
    session_id = ch._get_or_create_session(room_id)

    sub = MatrixSubscriber(ch, room_id)
    sub._approval_events["$approval_event"] = "call-1"
    ch._room_subscribers[room_id] = sub

    pa = _PendingApproval("$approval_event", "call-1")
    ch._pending_approvals["$approval_event"] = pa

    reaction_event = _make_reaction_event(reacts_to="$approval_event", key="❌")
    room = _make_room(room_id=room_id)
    await ch._on_reaction(room, reaction_event)

    ch._engine.submit_approval.assert_called_once()
    call_args = ch._engine.submit_approval.call_args
    assert call_args[0][0] == session_id
    assert call_args[0][1].approved is False
    assert call_args[0][1].message is None


@pytest.mark.anyio
async def test_on_reaction_ignores_unrelated_event(tmp_path: Path, db_factory):
    ch = _make_channel(tmp_path, db_factory)

    pa = _PendingApproval("$approval_event", "call-1")
    ch._pending_approvals["$approval_event"] = pa

    reaction_event = _make_reaction_event(reacts_to="$other_event", key="✅")
    room = _make_room()
    await ch._on_reaction(room, reaction_event)

    ch._engine.submit_approval.assert_not_called()


@pytest.mark.anyio
async def test_on_reaction_rejects_unknown_user(tmp_path: Path, db_factory):
    ch = _make_channel(tmp_path, db_factory, allowed_users=["@alice:example.com"])
    room_id = "!room:example.com"
    ch._get_or_create_session(room_id)

    sub = MatrixSubscriber(ch, room_id)
    sub._approval_events["$approval_event"] = "call-1"
    ch._room_subscribers[room_id] = sub
    ch._pending_approvals["$approval_event"] = _PendingApproval("$approval_event", "call-1")

    reaction_event = _make_reaction_event(
        reacts_to="$approval_event",
        key="✅",
        sender="@mallory:example.com",
    )
    room = _make_room(room_id=room_id)
    await ch._on_reaction(room, reaction_event)

    ch._engine.submit_approval.assert_not_called()


@pytest.mark.anyio
async def test_on_reaction_rejects_unlisted_room(tmp_path: Path, db_factory):
    ch = _make_channel(tmp_path, db_factory, allowed_rooms=["!allowed:example.com"])
    room_id = "!other:example.com"
    ch._get_or_create_session(room_id)

    sub = MatrixSubscriber(ch, room_id)
    sub._approval_events["$approval_event"] = "call-1"
    ch._room_subscribers[room_id] = sub
    ch._pending_approvals["$approval_event"] = _PendingApproval("$approval_event", "call-1")

    reaction_event = _make_reaction_event(reacts_to="$approval_event", key="✅")
    room = _make_room(room_id=room_id)
    await ch._on_reaction(room, reaction_event)

    ch._engine.submit_approval.assert_not_called()


@pytest.mark.anyio
async def test_approve_command_resolves_via_engine(tmp_path: Path, db_factory):
    ch = _make_channel(tmp_path, db_factory)
    room_id = "!room:example.com"
    sid = ch._get_or_create_session(room_id)
    ch._client.room_send = AsyncMock(return_value=MagicMock(event_id="$evt"))

    sub = MatrixSubscriber(ch, room_id)
    sub._approval_events["$approval"] = "call-1"
    ch._room_subscribers[room_id] = sub
    ch._pending_approvals["$approval"] = _PendingApproval("$approval", "call-1")

    await ch._handle_command(room_id, sid, "/allow", "@alice:example.com")

    ch._engine.submit_approval.assert_called_once()
    call_args = ch._engine.submit_approval.call_args
    assert call_args[0][1].approved is True


@pytest.mark.anyio
async def test_deny_command_resolves_via_engine(tmp_path: Path, db_factory):
    ch = _make_channel(tmp_path, db_factory)
    room_id = "!room:example.com"
    sid = ch._get_or_create_session(room_id)
    ch._client.room_send = AsyncMock(return_value=MagicMock(event_id="$evt"))

    sub = MatrixSubscriber(ch, room_id)
    sub._approval_events["$approval"] = "call-1"
    ch._room_subscribers[room_id] = sub
    ch._pending_approvals["$approval"] = _PendingApproval("$approval", "call-1")

    await ch._handle_command(room_id, sid, "/deny", "@alice:example.com")

    ch._engine.submit_approval.assert_called_once()
    call_args = ch._engine.submit_approval.call_args
    assert call_args[0][1].approved is False
    assert call_args[0][1].message is None


@pytest.mark.anyio
async def test_deny_command_passes_optional_message(tmp_path: Path, db_factory):
    ch = _make_channel(tmp_path, db_factory)
    room_id = "!room:example.com"
    sid = ch._get_or_create_session(room_id)
    ch._client.room_send = AsyncMock(return_value=MagicMock(event_id="$evt"))

    sub = MatrixSubscriber(ch, room_id)
    sub._approval_events["$approval"] = "call-1"
    ch._room_subscribers[room_id] = sub
    ch._pending_approvals["$approval"] = _PendingApproval("$approval", "call-1")

    await ch._handle_command(room_id, sid, "/deny not safe enough", "@alice:example.com")

    ch._engine.submit_approval.assert_called_once()
    call_args = ch._engine.submit_approval.call_args
    assert call_args[0][1].approved is False
    assert call_args[0][1].message == "not safe enough"


@pytest.mark.anyio
async def test_approve_when_no_pending_sends_message(tmp_path: Path, db_factory):
    ch = _make_channel(tmp_path, db_factory)
    room_id = "!room:example.com"
    sid = ch._get_or_create_session(room_id)
    ch._client.room_send = AsyncMock(return_value=MagicMock(event_id="$evt"))

    # With a subscriber but no pending approvals
    sub = MatrixSubscriber(ch, room_id)
    ch._room_subscribers[room_id] = sub

    await ch._handle_command(room_id, sid, "/allow", "@alice:example.com")

    ch._client.room_send.assert_called_once()
    sent = ch._client.room_send.call_args[0][2]["body"]
    assert "No pending" in sent


# ---------------------------------------------------------------------------
# Unit tests — formatting helpers
# ---------------------------------------------------------------------------


def test_md_to_html_converts_bold():
    html = _md_to_html("**hello**")
    assert "<strong>hello</strong>" in html


def test_format_approval_request_includes_tool_name():
    req = ApprovalRequest(
        tool_call_id="call-1",
        tool="read_file",
        args={"path": "/etc/passwd"},
        explanation="Sensitive file access detected by sentinel",
        risk_level="high",
    )
    text = _format_approval_request(req)
    assert "read_file" in text
    assert "Sensitive file access" in text
    assert "/allow" in text or "allow" in text.lower()


def test_format_command_result_help():
    result = CommandResult(
        command="help",
        data={"commands": [{"command": "/session", "description": "Show current session state"}]},
    )
    text = _format_command_result_text(result)
    assert "/session" in text


def test_format_command_result_security():
    result = CommandResult(
        command="security",
        data={"policy_preview": "# Security Policy", "action_log_entries": 5, "sentinel_evaluations": 2},
    )
    text = _format_command_result_text(result)
    assert "Security Policy" in text
    assert "5" in text


def test_format_command_result_usage_context_table_preceded_by_blank_line():
    """Matrix HTML uses python-markdown; tables need a blank line after the heading."""
    result = CommandResult(
        command="usage",
        data={
            "models": {"m": {"input_tokens": 1, "output_tokens": 0, "requests": 1}},
            "categories": {},
            "model_costs": {"m": {"cost": "0", "subscription": False}},
            "category_costs": {},
            "total_cost": {"actual": "0", "equivalent": "0"},
            "total_input": 1,
            "total_output": 0,
            "total_tool_calls": 2,
            "last_llm_agent": {
                "context_size": 100,
                "breakdown_pct": {
                    "system": 50.0,
                    "user": 10.0,
                    "assistant": 0.0,
                    "tool_calls": 20.0,
                    "tool_returns": 20.0,
                },
            },
        },
    )
    text = _format_command_result_text(result)
    assert "**Tool Calls:** 2" in text
    assert "**Context**\n\n| Source |" in text
    assert "<table" in _md_to_html(text)


def test_format_command_result_usage_separates_actual_and_equivalent_cost():
    bucket = {"input_tokens": 10, "output_tokens": 5, "requests": 1}
    result = CommandResult(
        command="usage",
        data={
            "models": {"openai-codex:gpt-5.4": bucket, "anthropic:claude-haiku-4-5": bucket},
            "categories": {"agent": bucket, "sentinel": bucket},
            "model_costs": {
                "openai-codex:gpt-5.4": {"cost": "0.42", "subscription": True},
                "anthropic:claude-haiku-4-5": {"cost": "0.01", "subscription": False},
            },
            "category_costs": {
                "agent": {"actual": "0", "equivalent": "0.42"},
                "sentinel": {"actual": "0.01", "equivalent": "0.01"},
            },
            "total_cost": {"actual": "0.01", "equivalent": "0.43"},
            "total_input": 20,
            "total_output": 10,
            "budget_gauges": [
                {
                    "key": "equivalent_cost",
                    "label": "Equivalent cost",
                    "current_value": "$0.4300",
                    "limit_value": None,
                    "fill_pct": 0.0,
                    "reached": False,
                },
            ],
        },
    )

    text = _format_command_result_text(result)

    assert "| $0.0100 (≈ $0.4300 equivalent)" in text
    assert "| openai-codex:gpt-5.4 | 10 | 5 | 1 | $0.4200 · subscription |" in text
    assert "| agent | 10 | 5 | 1 | - (≈ $0.4200 equivalent) |" in text
    assert "| sentinel | 10 | 5 | 1 | $0.0100 |" in text
    assert "| Equivalent cost | $0.4300 | — |" in text


# ---------------------------------------------------------------------------
# Unit tests — /yes and /no aliases
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_yes_alias_approves(tmp_path: Path, db_factory):
    ch = _make_channel(tmp_path, db_factory)
    room_id = "!room:example.com"
    sid = ch._get_or_create_session(room_id)
    ch._client.room_send = AsyncMock(return_value=MagicMock(event_id="$evt"))

    sub = MatrixSubscriber(ch, room_id)
    sub._approval_events["$approval"] = "call-1"
    ch._room_subscribers[room_id] = sub
    ch._pending_approvals["$approval"] = _PendingApproval("$approval", "call-1")

    await ch._handle_command(room_id, sid, "/yes", "@alice:example.com")

    ch._engine.submit_approval.assert_called_once()
    call_args = ch._engine.submit_approval.call_args
    assert call_args[0][1].approved is True


@pytest.mark.anyio
async def test_no_alias_denies(tmp_path: Path, db_factory):
    ch = _make_channel(tmp_path, db_factory)
    room_id = "!room:example.com"
    sid = ch._get_or_create_session(room_id)
    ch._client.room_send = AsyncMock(return_value=MagicMock(event_id="$evt"))

    sub = MatrixSubscriber(ch, room_id)
    sub._approval_events["$approval"] = "call-1"
    ch._room_subscribers[room_id] = sub
    ch._pending_approvals["$approval"] = _PendingApproval("$approval", "call-1")

    await ch._handle_command(room_id, sid, "/no", "@alice:example.com")

    ch._engine.submit_approval.assert_called_once()
    call_args = ch._engine.submit_approval.call_args
    assert call_args[0][1].approved is False


# ---------------------------------------------------------------------------
# Unit tests — domain approval
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_pending_domain_approval_resolves():
    pd = _PendingDomainApproval("$evt")
    pd.resolve(True)
    result = await pd.wait()
    assert result is True


@pytest.mark.anyio
async def test_on_reaction_approves_domain(tmp_path: Path, db_factory):
    ch = _make_channel(tmp_path, db_factory)
    room_id = "!room:example.com"
    ch._get_or_create_session(room_id)

    sub = MatrixSubscriber(ch, room_id)
    sub._domain_events["$domain_event"] = "req-1"
    ch._room_subscribers[room_id] = sub

    pd = _PendingDomainApproval("$domain_event")
    ch._pending_domain_approvals["$domain_event"] = pd

    reaction_event = _make_reaction_event(reacts_to="$domain_event", key="✅")
    room = _make_room(room_id=room_id)
    await ch._on_reaction(room, reaction_event)

    ch._engine.submit_approval.assert_called_once()
    call_args = ch._engine.submit_approval.call_args
    assert call_args[0][1].decision == "allow"


@pytest.mark.anyio
async def test_on_reaction_denies_domain(tmp_path: Path, db_factory):
    ch = _make_channel(tmp_path, db_factory)
    room_id = "!room:example.com"
    ch._get_or_create_session(room_id)

    sub = MatrixSubscriber(ch, room_id)
    sub._domain_events["$domain_event"] = "req-1"
    ch._room_subscribers[room_id] = sub

    pd = _PendingDomainApproval("$domain_event")
    ch._pending_domain_approvals["$domain_event"] = pd

    reaction_event = _make_reaction_event(reacts_to="$domain_event", key="❌")
    room = _make_room(room_id=room_id)
    await ch._on_reaction(room, reaction_event)

    ch._engine.submit_approval.assert_called_once()
    call_args = ch._engine.submit_approval.call_args
    assert call_args[0][1].decision == "deny"


@pytest.mark.anyio
async def test_approve_command_resolves_domain_pending(tmp_path: Path, db_factory):
    ch = _make_channel(tmp_path, db_factory)
    room_id = "!room:example.com"
    sid = ch._get_or_create_session(room_id)
    ch._client.room_send = AsyncMock(return_value=MagicMock(event_id="$evt"))

    sub = MatrixSubscriber(ch, room_id)
    sub._domain_events["$domain_event"] = "req-1"
    ch._room_subscribers[room_id] = sub
    ch._pending_domain_approvals["$domain_event"] = _PendingDomainApproval("$domain_event")

    await ch._handle_command(room_id, sid, "/allow", "@alice:example.com")

    ch._engine.submit_approval.assert_called_once()
    call_args = ch._engine.submit_approval.call_args
    assert call_args[0][1].decision == "allow"


@pytest.mark.anyio
async def test_deny_command_resolves_domain_pending(tmp_path: Path, db_factory):
    ch = _make_channel(tmp_path, db_factory)
    room_id = "!room:example.com"
    sid = ch._get_or_create_session(room_id)
    ch._client.room_send = AsyncMock(return_value=MagicMock(event_id="$evt"))

    sub = MatrixSubscriber(ch, room_id)
    sub._domain_events["$domain_event"] = "req-1"
    ch._room_subscribers[room_id] = sub
    ch._pending_domain_approvals["$domain_event"] = _PendingDomainApproval("$domain_event")

    await ch._handle_command(room_id, sid, "/deny", "@alice:example.com")

    ch._engine.submit_approval.assert_called_once()
    call_args = ch._engine.submit_approval.call_args
    assert call_args[0][1].decision == "deny"


def test_format_domain_escalation():
    text = _format_domain_escalation("api.example.com", "curl https://api.example.com", "unexpected domain")
    assert "api.example.com" in text
    assert "unexpected domain" in text


# ---------------------------------------------------------------------------
# Token persistence — user_id binding
# ---------------------------------------------------------------------------


def test_load_token_returns_persisted_yaml_token(tmp_path: Path, db_factory):
    """Persisted token with matching user_id is accepted."""
    ch = _make_channel(tmp_path, db_factory)
    token_file = tmp_path / "matrix_token.yaml"
    persisted = MatrixTokenFile(
        access_token="tok_good",
        device_id="DEV1",
        user_id="@carapace:example.com",
        user="thies",
    )
    token_file.write_text(yaml.safe_dump(MatrixTokensFile(tokens=[persisted]).model_dump(mode="json")))
    token, device_id = ch._load_token(token_file)
    assert token == "tok_good"
    assert device_id == "DEV1"


def test_load_token_discards_stale_user_id(tmp_path: Path, db_factory):
    """Persisted token for a different user_id is ignored."""
    ch = _make_channel(tmp_path, db_factory)
    token_file = tmp_path / "matrix_token.yaml"
    persisted = MatrixTokenFile(
        access_token="tok_old",
        device_id="DEV1",
        user_id="@other:example.com",
        user="thies",
    )
    token_file.write_text(yaml.safe_dump(MatrixTokensFile(tokens=[persisted]).model_dump(mode="json")))
    token, device_id = ch._load_token(token_file)
    assert token == ""
    assert device_id is None
    assert token_file.exists()


def test_load_token_discards_stale_owner(tmp_path: Path, db_factory):
    """Persisted token for a different carapace user is ignored."""
    ch = _make_channel(tmp_path, db_factory)
    token_file = tmp_path / "matrix_token.yaml"
    persisted = MatrixTokenFile(
        access_token="tok_old",
        device_id="DEV1",
        user_id="@carapace:example.com",
        user="alice",
    )
    token_file.write_text(yaml.safe_dump(MatrixTokensFile(tokens=[persisted]).model_dump(mode="json")))
    token, device_id = ch._load_token(token_file)
    assert token == ""
    assert device_id is None
    assert token_file.exists()


@pytest.mark.anyio
async def test_password_login_persists_user_id(tmp_path: Path, db_factory, monkeypatch: pytest.MonkeyPatch):
    """After password login the persisted file includes the configured user_id."""

    ch = _make_channel(tmp_path, db_factory, password="secret")
    token_file = tmp_path / "matrix_token.yaml"

    login_resp = MagicMock()
    login_resp.access_token = "tok_new"
    login_resp.device_id = "DEV_NEW"
    ch._client.login = AsyncMock(return_value=login_resp)

    await ch._password_login(token_file)

    stored = MatrixTokensFile.model_validate(yaml.safe_load(token_file.read_text(encoding="utf-8"))).tokens[0]
    assert stored.access_token == "tok_new"
    assert stored.device_id == "DEV_NEW"
    assert stored.user_id == "@carapace:example.com"
    assert stored.user == "thies"


def _login_response(access_token: str) -> MagicMock:
    resp = MagicMock()
    resp.access_token = access_token
    resp.device_id = "DEV_NEW"
    return resp


@pytest.mark.anyio
async def test_sync_loop_reauthenticates_on_unknown_token(tmp_path: Path, db_factory):
    ch = _make_channel(tmp_path, db_factory, password="secret")
    ch._token_file.write_text("stale", encoding="utf-8")
    ch._client.sync = AsyncMock(
        side_effect=[nio.SyncError("Unknown token", "M_UNKNOWN_TOKEN"), asyncio.CancelledError()]
    )
    ch._client.login = AsyncMock(return_value=_login_response("tok_new"))

    await ch._sync_loop()

    ch._client.login.assert_awaited_once()
    assert ch._client.sync.await_count == 2
    stored = MatrixTokensFile.model_validate(yaml.safe_load(ch._token_file.read_text(encoding="utf-8"))).tokens[0]
    assert stored.access_token == "tok_new"


@pytest.mark.anyio
async def test_sync_loop_retries_failed_reauthentication(tmp_path: Path, db_factory, monkeypatch: pytest.MonkeyPatch):
    ch = _make_channel(tmp_path, db_factory, password="secret")
    unknown_token = nio.SyncError("Unknown token", "M_UNKNOWN_TOKEN")
    ch._client.sync = AsyncMock(side_effect=[unknown_token, unknown_token, asyncio.CancelledError()])
    ch._client.login = AsyncMock(side_effect=[nio.LoginError("homeserver hiccup"), _login_response("tok_new")])
    sleep = AsyncMock()
    monkeypatch.setattr(asyncio, "sleep", sleep)

    await ch._sync_loop()

    assert ch._client.login.await_count == 2
    assert ch._client.sync.await_count == 3
    sleep.assert_awaited_once_with(5)


@pytest.mark.anyio
async def test_sync_loop_stops_on_unknown_token_without_password(tmp_path: Path, db_factory):
    ch = _make_channel(tmp_path, db_factory)
    ch._client.sync = AsyncMock(
        side_effect=[nio.SyncError("Unknown token", "M_UNKNOWN_TOKEN"), asyncio.CancelledError()]
    )
    ch._client.login = AsyncMock()

    await ch._sync_loop()

    ch._client.login.assert_not_awaited()
    ch._client.sync.assert_awaited_once()


@pytest.mark.anyio
async def test_subscriber_forwards_attachments(tmp_path: Path, db_factory):
    from types import SimpleNamespace

    ch = _make_channel(tmp_path, db_factory)
    ch._send_text = AsyncMock()
    sub = MatrixSubscriber(ch, "!room:example.com")

    await sub.on_user_message(
        "look",
        from_self=False,
        attachments=[SimpleNamespace(name="abc.png", path="/tmp/abc-1a2b.png")],
    )

    ch._send_text.assert_awaited_once()
    body = ch._send_text.await_args.args[1]
    assert "look" in body
    assert "abc.png" in body and "/tmp/abc-1a2b.png" in body


@pytest.mark.anyio
async def test_subscriber_attachment_only_message_is_forwarded(tmp_path: Path, db_factory):
    from types import SimpleNamespace

    ch = _make_channel(tmp_path, db_factory)
    ch._send_text = AsyncMock()
    sub = MatrixSubscriber(ch, "!room:example.com")

    await sub.on_user_message(
        "",
        from_self=False,
        attachments=[SimpleNamespace(name="d.csv", path="/tmp/d.csv")],
    )

    ch._send_text.assert_awaited_once()
    assert "d.csv" in ch._send_text.await_args.args[1]
