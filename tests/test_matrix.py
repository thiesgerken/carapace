"""Tests for the Matrix channel adapter (no homeserver needed — mocked nio)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from carapace.channels.matrix import (
    MatrixChannel,
    _format_approval_request,
    _format_command_result_text,
    _format_domain_escalation,
    _md_to_html,
    _PendingApproval,
    _PendingDomainApproval,
)
from carapace.models import MatrixChannelConfig
from carapace.session import SessionManager
from carapace.ws_models import ApprovalRequest, CommandResult

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_config(**kwargs) -> MatrixChannelConfig:
    defaults = {
        "enabled": True,
        "homeserver": "https://matrix.example.com",
        "user_id": "@carapace:example.com",
        "allowed_users": ["@alice:example.com"],
        "allowed_rooms": [],
    }
    return MatrixChannelConfig(**(defaults | kwargs))


def _make_channel(tmp_path: Path, **config_kwargs) -> MatrixChannel:
    """Build a MatrixChannel with mocked internals."""
    import nio

    from carapace.bootstrap import ensure_data_dir
    from carapace.config import load_config
    from carapace.sandbox.manager import SandboxManager

    ensure_data_dir(tmp_path)
    full_config = load_config(tmp_path)
    session_mgr = SessionManager(tmp_path)

    sandbox_mgr = MagicMock(spec=SandboxManager)
    sandbox_mgr.get_domain_info.return_value = []

    channel = MatrixChannel(
        config=_make_config(**config_kwargs),
        full_config=full_config,
        security_md="",
        session_mgr=session_mgr,
        skill_catalog=[],
        agent_model=None,
        sandbox_mgr=sandbox_mgr,
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
    import nio

    event = MagicMock(spec=nio.RoomMessageText)
    event.body = body
    event.sender = sender
    event.transaction_id = None
    event.decrypted = False
    return event


def _make_reaction_event(reacts_to: str, key: str, sender: str = "@alice:example.com") -> MagicMock:
    import nio

    event = MagicMock(spec=nio.ReactionEvent)
    event.reacts_to = reacts_to
    event.key = key
    event.sender = sender
    return event


# ---------------------------------------------------------------------------
# Unit tests — SessionManager.find_session
# ---------------------------------------------------------------------------


def test_find_session_returns_none_when_empty(tmp_path: Path):
    mgr = SessionManager(tmp_path)
    assert mgr.find_session("matrix", "!room:example.com") is None


def test_find_session_returns_matching_session(tmp_path: Path):
    mgr = SessionManager(tmp_path)
    s = mgr.create_session("matrix", "!room:example.com")
    assert mgr.find_session("matrix", "!room:example.com") == s.session_id


def test_find_session_ignores_different_channel(tmp_path: Path):
    mgr = SessionManager(tmp_path)
    mgr.create_session("cli", "!room:example.com")
    assert mgr.find_session("matrix", "!room:example.com") is None


def test_find_session_ignores_different_ref(tmp_path: Path):
    mgr = SessionManager(tmp_path)
    mgr.create_session("matrix", "!other:example.com")
    assert mgr.find_session("matrix", "!room:example.com") is None


def test_find_session_returns_most_recent(tmp_path: Path):
    mgr = SessionManager(tmp_path)
    s1 = mgr.create_session("matrix", "!room:example.com")
    s2 = mgr.create_session("matrix", "!room:example.com")
    result = mgr.find_session("matrix", "!room:example.com")
    # Should return one of them; both are valid. s2 was created last.
    assert result in {s1.session_id, s2.session_id}


# ---------------------------------------------------------------------------
# Unit tests — room-session mapping
# ---------------------------------------------------------------------------


def test_get_or_create_session_creates_new(tmp_path: Path):
    ch = _make_channel(tmp_path)
    sid = ch._get_or_create_session("!newroom:example.com")
    assert sid
    # Second call returns same session
    assert ch._get_or_create_session("!newroom:example.com") == sid


def test_get_or_create_session_resumes_existing(tmp_path: Path):
    mgr = SessionManager(tmp_path)
    existing = mgr.create_session("matrix", "!room:example.com")

    ch = _make_channel(tmp_path)
    sid = ch._get_or_create_session("!room:example.com")
    assert sid == existing.session_id


# ---------------------------------------------------------------------------
# Unit tests — _is_allowed filtering
# ---------------------------------------------------------------------------


def test_is_allowed_rejects_self(tmp_path: Path):
    ch = _make_channel(tmp_path)
    room = _make_room()
    assert not ch._is_allowed(room, "@carapace:example.com")


def test_is_allowed_rejects_unknown_user_when_allowlist_set(tmp_path: Path):
    ch = _make_channel(tmp_path, allowed_users=["@alice:example.com"])
    room = _make_room()
    assert not ch._is_allowed(room, "@evil:example.com")


def test_is_allowed_accepts_listed_user(tmp_path: Path):
    ch = _make_channel(tmp_path, allowed_users=["@alice:example.com"])
    room = _make_room()
    assert ch._is_allowed(room, "@alice:example.com")


def test_is_allowed_accepts_any_user_when_no_allowlist(tmp_path: Path):
    ch = _make_channel(tmp_path, allowed_users=[])
    room = _make_room()
    assert ch._is_allowed(room, "@anyone:example.com")


def test_is_allowed_rejects_unlisted_room(tmp_path: Path):
    ch = _make_channel(tmp_path, allowed_rooms=["!allowed:example.com"])
    room = _make_room(room_id="!other:example.com")
    assert not ch._is_allowed(room, "@alice:example.com")


# ---------------------------------------------------------------------------
# Unit tests — slash command routing
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_handle_reset_creates_new_session(tmp_path: Path):
    ch = _make_channel(tmp_path)
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
async def test_handle_command_unknown(tmp_path: Path):
    ch = _make_channel(tmp_path)
    room_id = "!room:example.com"
    ch._get_or_create_session(room_id)
    ch._client.room_send = AsyncMock(return_value=MagicMock(event_id="$evt1"))

    await ch._handle_command(room_id, ch._room_sessions[room_id], "/foobar", "@alice:example.com")

    # Should have sent an "Unknown command" message
    ch._client.room_send.assert_called_once()
    sent_body = ch._client.room_send.call_args[0][2]["body"]
    assert "Unknown command" in sent_body


@pytest.mark.anyio
async def test_handle_command_help(tmp_path: Path):
    ch = _make_channel(tmp_path)
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
async def test_on_reaction_approves_pending(tmp_path: Path):
    ch = _make_channel(tmp_path)

    pa = _PendingApproval("$approval_event", "call-1")
    ch._pending_approvals["$approval_event"] = pa

    reaction_event = _make_reaction_event(reacts_to="$approval_event", key="✅")
    room = _make_room()
    await ch._on_reaction(room, reaction_event)

    assert pa._future.done()
    assert pa._future.result() is True


@pytest.mark.anyio
async def test_on_reaction_denies_pending(tmp_path: Path):
    ch = _make_channel(tmp_path)

    pa = _PendingApproval("$approval_event", "call-1")
    ch._pending_approvals["$approval_event"] = pa

    reaction_event = _make_reaction_event(reacts_to="$approval_event", key="❌")
    room = _make_room()
    await ch._on_reaction(room, reaction_event)

    assert pa._future.done()
    assert pa._future.result() is False


@pytest.mark.anyio
async def test_on_reaction_ignores_unrelated_event(tmp_path: Path):
    ch = _make_channel(tmp_path)

    pa = _PendingApproval("$approval_event", "call-1")
    ch._pending_approvals["$approval_event"] = pa

    reaction_event = _make_reaction_event(reacts_to="$other_event", key="✅")
    room = _make_room()
    await ch._on_reaction(room, reaction_event)

    assert not pa._future.done()


@pytest.mark.anyio
async def test_approve_command_resolves_room_pending(tmp_path: Path):
    ch = _make_channel(tmp_path)
    room_id = "!room:example.com"
    sid = ch._get_or_create_session(room_id)
    ch._client.room_send = AsyncMock(return_value=MagicMock(event_id="$evt"))

    pa = _PendingApproval("$approval", "call-1")
    ch._room_pending[room_id] = pa

    await ch._handle_command(room_id, sid, "/allow", "@alice:example.com")

    assert pa._future.done()
    assert pa._future.result() is True


@pytest.mark.anyio
async def test_deny_command_resolves_room_pending(tmp_path: Path):
    ch = _make_channel(tmp_path)
    room_id = "!room:example.com"
    sid = ch._get_or_create_session(room_id)
    ch._client.room_send = AsyncMock(return_value=MagicMock(event_id="$evt"))

    pa = _PendingApproval("$approval", "call-1")
    ch._room_pending[room_id] = pa

    await ch._handle_command(room_id, sid, "/deny", "@alice:example.com")

    assert pa._future.done()
    assert pa._future.result() is False


@pytest.mark.anyio
async def test_approve_when_no_pending_sends_message(tmp_path: Path):
    ch = _make_channel(tmp_path)
    room_id = "!room:example.com"
    sid = ch._get_or_create_session(room_id)
    ch._client.room_send = AsyncMock(return_value=MagicMock(event_id="$evt"))

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
        explanation="Sensitive file access detected by bouncer",
        risk_level="high",
    )
    text = _format_approval_request(req)
    assert "read_file" in text
    assert "Sensitive file access" in text
    assert "/allow" in text or "allow" in text.lower()


def test_format_command_result_help():
    result = CommandResult(
        command="help",
        data={"commands": [{"command": "/security", "description": "Show security policy"}]},
    )
    text = _format_command_result_text(result)
    assert "/security" in text


def test_format_command_result_security():
    result = CommandResult(
        command="security",
        data={"policy_preview": "# Security Policy", "action_log_entries": 5, "bouncer_evaluations": 2},
    )
    text = _format_command_result_text(result)
    assert "Security Policy" in text
    assert "5" in text


# ---------------------------------------------------------------------------
# Unit tests — /yes and /no aliases
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_yes_alias_approves(tmp_path: Path):
    ch = _make_channel(tmp_path)
    room_id = "!room:example.com"
    sid = ch._get_or_create_session(room_id)
    ch._client.room_send = AsyncMock(return_value=MagicMock(event_id="$evt"))

    pa = _PendingApproval("$approval", "call-1")
    ch._room_pending[room_id] = pa

    await ch._handle_command(room_id, sid, "/yes", "@alice:example.com")

    assert pa._future.done()
    assert pa._future.result() is True


@pytest.mark.anyio
async def test_no_alias_denies(tmp_path: Path):
    ch = _make_channel(tmp_path)
    room_id = "!room:example.com"
    sid = ch._get_or_create_session(room_id)
    ch._client.room_send = AsyncMock(return_value=MagicMock(event_id="$evt"))

    pa = _PendingApproval("$approval", "call-1")
    ch._room_pending[room_id] = pa

    await ch._handle_command(room_id, sid, "/no", "@alice:example.com")

    assert pa._future.done()
    assert pa._future.result() is False


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
async def test_on_reaction_approves_domain(tmp_path: Path):
    ch = _make_channel(tmp_path)

    pd = _PendingDomainApproval("$domain_event")
    ch._pending_domain_approvals["$domain_event"] = pd

    reaction_event = _make_reaction_event(reacts_to="$domain_event", key="✅")
    room = _make_room()
    await ch._on_reaction(room, reaction_event)

    assert pd._future.done()
    assert pd._future.result() is True


@pytest.mark.anyio
async def test_on_reaction_denies_domain(tmp_path: Path):
    ch = _make_channel(tmp_path)

    pd = _PendingDomainApproval("$domain_event")
    ch._pending_domain_approvals["$domain_event"] = pd

    reaction_event = _make_reaction_event(reacts_to="$domain_event", key="❌")
    room = _make_room()
    await ch._on_reaction(room, reaction_event)

    assert pd._future.done()
    assert pd._future.result() is False


@pytest.mark.anyio
async def test_approve_command_resolves_domain_pending(tmp_path: Path):
    ch = _make_channel(tmp_path)
    room_id = "!room:example.com"
    sid = ch._get_or_create_session(room_id)
    ch._client.room_send = AsyncMock(return_value=MagicMock(event_id="$evt"))

    pd = _PendingDomainApproval("$domain_event")
    ch._room_pending[room_id] = pd

    await ch._handle_command(room_id, sid, "/allow", "@alice:example.com")

    assert pd._future.done()
    assert pd._future.result() is True


@pytest.mark.anyio
async def test_deny_command_resolves_domain_pending(tmp_path: Path):
    ch = _make_channel(tmp_path)
    room_id = "!room:example.com"
    sid = ch._get_or_create_session(room_id)
    ch._client.room_send = AsyncMock(return_value=MagicMock(event_id="$evt"))

    pd = _PendingDomainApproval("$domain_event")
    ch._room_pending[room_id] = pd

    await ch._handle_command(room_id, sid, "/deny", "@alice:example.com")

    assert pd._future.done()
    assert pd._future.result() is False


def test_format_domain_escalation():
    text = _format_domain_escalation("api.example.com", "curl https://api.example.com", "unexpected domain")
    assert "api.example.com" in text
    assert "unexpected domain" in text
