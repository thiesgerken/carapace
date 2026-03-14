"""Tests for SessionManager (no LLM tokens needed)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from carapace.bootstrap import ensure_data_dir
from carapace.config import load_config, load_security_md
from carapace.sandbox.manager import SandboxManager
from carapace.session import SessionEngine, SessionManager
from carapace.skills import SkillRegistry
from carapace.ws_models import ApprovalRequest, TurnUsage


def test_create_session(tmp_path: Path):
    mgr = SessionManager(tmp_path)
    state = mgr.create_session()
    assert len(state.session_id) == 25  # 2026-03-08-10-22-abcd1234
    assert state.channel_type == "cli"


def test_resume_session(tmp_path: Path):
    mgr = SessionManager(tmp_path)
    state = mgr.create_session()
    resumed = mgr.resume_session(state.session_id)
    assert resumed is not None
    assert resumed.session_id == state.session_id


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
    state.approved_credentials.append("test-cred")
    mgr.save_state(state)

    resumed = mgr.resume_session(state.session_id)
    assert resumed is not None
    assert "test-cred" in resumed.approved_credentials


# ---------------------------------------------------------------------------
# SessionEngine: on_user_message from_self tests
# ---------------------------------------------------------------------------


class _FakeSubscriber:
    """Minimal subscriber that records calls."""

    def __init__(self) -> None:
        self.user_messages: list[tuple[str, bool]] = []
        self.errors: list[str] = []
        self.cancelled: int = 0

    async def on_user_message(self, content: str, *, from_self: bool) -> None:
        self.user_messages.append((content, from_self))

    async def on_tool_call(self, tool: str, args: dict[str, Any], detail: str) -> None:
        pass

    async def on_tool_result(self, tool: str, result: str) -> None:
        pass

    async def on_done(self, content: str, usage: TurnUsage) -> None:
        pass

    async def on_error(self, detail: str) -> None:
        self.errors.append(detail)

    async def on_cancelled(self) -> None:
        self.cancelled += 1

    async def on_approval_request(self, req: ApprovalRequest) -> None:
        pass

    async def on_proxy_approval_request(self, request_id: str, domain: str, command: str) -> None:
        pass

    async def on_title_update(self, title: str) -> None:
        pass

    async def on_domain_info(self, domain: str, detail: str) -> None:
        pass


def _make_engine(tmp_path: Path) -> SessionEngine:
    ensure_data_dir(tmp_path)
    config = load_config(tmp_path)
    security_md = load_security_md(tmp_path)
    session_mgr = SessionManager(tmp_path)
    registry = SkillRegistry(tmp_path / "skills")
    skill_catalog = registry.scan()
    sandbox_mgr = MagicMock(spec=SandboxManager)
    sandbox_mgr.get_domain_info.return_value = []
    return SessionEngine(
        config=config,
        data_dir=tmp_path,
        security_md=security_md,
        session_mgr=session_mgr,
        skill_catalog=skill_catalog,
        agent_model=None,
        sandbox_mgr=sandbox_mgr,
    )


def test_user_message_from_self(tmp_path: Path):
    """Origin subscriber gets from_self=True, others get from_self=False."""

    async def _run() -> None:
        engine = _make_engine(tmp_path)
        state = engine.session_mgr.create_session()
        sid = state.session_id

        origin = _FakeSubscriber()
        other = _FakeSubscriber()
        engine.subscribe(sid, origin)
        engine.subscribe(sid, other)

        # Mock run_agent_turn to avoid needing LLM
        async def _noop_turn(*_a: Any, **_kw: Any) -> str:
            return "ok"

        with patch("carapace.agent_loop.run_agent_turn", new=_noop_turn):
            await engine.submit_message(sid, "hello", origin=origin)
            await asyncio.sleep(0.1)

        assert origin.user_messages == [("hello", True)]
        assert other.user_messages == [("hello", False)]

    with patch("carapace.session_engine.Sentinel"):
        asyncio.run(_run())


def test_user_message_no_origin(tmp_path: Path):
    """When origin is None, all subscribers get from_self=False."""

    async def _run() -> None:
        engine = _make_engine(tmp_path)
        state = engine.session_mgr.create_session()
        sid = state.session_id

        sub_a = _FakeSubscriber()
        sub_b = _FakeSubscriber()
        engine.subscribe(sid, sub_a)
        engine.subscribe(sid, sub_b)

        async def _noop_turn(*_a: Any, **_kw: Any) -> str:
            return "ok"

        with patch("carapace.agent_loop.run_agent_turn", new=_noop_turn):
            await engine.submit_message(sid, "hi")
            await asyncio.sleep(0.1)

        assert sub_a.user_messages == [("hi", False)]
        assert sub_b.user_messages == [("hi", False)]

    with patch("carapace.session_engine.Sentinel"):
        asyncio.run(_run())


# ---------------------------------------------------------------------------
# SessionEngine lifecycle tests
# ---------------------------------------------------------------------------


def test_subscribe_duplicate_prevention(tmp_path: Path):
    """Subscribing the same subscriber twice does not duplicate it."""
    with patch("carapace.session_engine.Sentinel"):
        engine = _make_engine(tmp_path)
        state = engine.session_mgr.create_session()
        sid = state.session_id

        sub = _FakeSubscriber()
        engine.subscribe(sid, sub)
        engine.subscribe(sid, sub)

        active = engine.get_active(sid)
        assert active is not None
        assert active.subscribers.count(sub) == 1


def test_get_active_returns_none_before_activation(tmp_path: Path):
    """get_active returns None for a session that hasn't been activated."""
    engine = _make_engine(tmp_path)
    state = engine.session_mgr.create_session()
    assert engine.get_active(state.session_id) is None


def test_get_or_activate_loads_session(tmp_path: Path):
    """get_or_activate loads the session from disk and makes it active."""
    with patch("carapace.session_engine.Sentinel"):
        engine = _make_engine(tmp_path)
        state = engine.session_mgr.create_session()
        sid = state.session_id

        assert engine.get_active(sid) is None
        active = engine.get_or_activate(sid)
        assert active is not None
        assert active.state.session_id == sid
        assert engine.get_active(sid) is active


def test_get_or_activate_unknown_session_raises(tmp_path: Path):
    """get_or_activate raises KeyError for a nonexistent session."""
    import pytest as _pytest

    engine = _make_engine(tmp_path)
    with _pytest.raises(KeyError):
        engine.get_or_activate("nonexistent")


def test_deactivate_removes_session(tmp_path: Path):
    """deactivate removes the session from active memory."""
    with patch("carapace.session_engine.Sentinel"):
        engine = _make_engine(tmp_path)
        state = engine.session_mgr.create_session()
        sid = state.session_id

        engine.get_or_activate(sid)
        assert engine.get_active(sid) is not None

        engine.deactivate(sid)
        assert engine.get_active(sid) is None


def test_deactivate_idempotent(tmp_path: Path):
    """Deactivating an already-deactivated session does not raise."""
    engine = _make_engine(tmp_path)
    engine.deactivate("nonexistent")  # should not raise


def test_unsubscribe_removes_subscriber(tmp_path: Path):
    """unsubscribe removes the subscriber from the list."""
    with patch("carapace.session_engine.Sentinel"):
        engine = _make_engine(tmp_path)
        state = engine.session_mgr.create_session()
        sid = state.session_id

        sub = _FakeSubscriber()
        engine.subscribe(sid, sub)
        active = engine.get_active(sid)
        assert sub in active.subscribers

        engine.unsubscribe(sid, sub)
        assert sub not in active.subscribers


def test_unsubscribe_nonexistent_is_safe(tmp_path: Path):
    """Unsubscribing a subscriber that was never added does not raise."""
    with patch("carapace.session_engine.Sentinel"):
        engine = _make_engine(tmp_path)
        state = engine.session_mgr.create_session()
        sid = state.session_id

        engine.get_or_activate(sid)
        engine.unsubscribe(sid, _FakeSubscriber())  # should not raise


def test_unsubscribe_saves_usage_when_last(tmp_path: Path):
    """Usage is persisted to disk when the last subscriber disconnects."""
    with patch("carapace.session_engine.Sentinel"):
        engine = _make_engine(tmp_path)
        state = engine.session_mgr.create_session()
        sid = state.session_id

        sub = _FakeSubscriber()
        engine.subscribe(sid, sub)

        # Modify usage so we can detect whether it was saved
        active = engine.get_active(sid)
        from carapace.models import ModelUsage

        active.usage_tracker.models["test-model"] = ModelUsage(input_tokens=42)

        engine.unsubscribe(sid, sub)

        # Reload from disk
        reloaded = engine.session_mgr.load_usage(sid)
        assert reloaded.total_input == 42


def test_submit_message_busy_broadcasts_error(tmp_path: Path):
    """submit_message rejects with an error if agent is already running."""

    async def _run() -> None:
        engine = _make_engine(tmp_path)
        state = engine.session_mgr.create_session()
        sid = state.session_id

        sub = _FakeSubscriber()
        engine.subscribe(sid, sub)

        # Simulate a running agent task that never finishes
        active = engine.get_active(sid)
        active.agent_task = asyncio.create_task(asyncio.sleep(999))

        await engine.submit_message(sid, "should fail")

        assert any("busy" in e.lower() for e in sub.errors)

        active.agent_task.cancel()
        with __import__("contextlib").suppress(asyncio.CancelledError):
            await active.agent_task

    with patch("carapace.session_engine.Sentinel"):
        asyncio.run(_run())


def test_submit_cancel_stops_task(tmp_path: Path):
    """submit_cancel cancels the running agent task."""

    async def _run() -> None:
        engine = _make_engine(tmp_path)
        state = engine.session_mgr.create_session()
        sid = state.session_id

        engine.subscribe(sid, _FakeSubscriber())
        active = engine.get_active(sid)

        # Simulate a running agent task
        active.agent_task = asyncio.create_task(asyncio.sleep(999))

        await engine.submit_cancel(sid)
        assert active.agent_task is None

    with patch("carapace.session_engine.Sentinel"):
        asyncio.run(_run())


def test_submit_cancel_noop_when_inactive(tmp_path: Path):
    """submit_cancel is a no-op when session is not active."""

    async def _run() -> None:
        engine = _make_engine(tmp_path)
        await engine.submit_cancel("nonexistent")  # should not raise

    asyncio.run(_run())


def test_handle_slash_command_session(tmp_path: Path):
    """handle_slash_command /session returns session metadata."""
    with patch("carapace.session_engine.Sentinel"):
        engine = _make_engine(tmp_path)
        state = engine.session_mgr.create_session()
        sid = state.session_id
        engine.get_or_activate(sid)

        result = engine.handle_slash_command(sid, "/session")
        assert result is not None
        assert result["command"] == "session"
        assert result["data"]["session_id"] == sid


def test_handle_slash_command_unknown(tmp_path: Path):
    """handle_slash_command returns None for unknown commands."""
    with patch("carapace.session_engine.Sentinel"):
        engine = _make_engine(tmp_path)
        state = engine.session_mgr.create_session()
        sid = state.session_id
        engine.get_or_activate(sid)

        assert engine.handle_slash_command(sid, "/nonexistent") is None


def test_handle_slash_command_inactive_session(tmp_path: Path):
    """handle_slash_command returns None for a session that isn't active."""
    engine = _make_engine(tmp_path)
    state = engine.session_mgr.create_session()
    assert engine.handle_slash_command(state.session_id, "/session") is None
