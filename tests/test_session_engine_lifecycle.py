"""SessionEngine lifecycle, cancellation, retry, and reset tests."""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart

import carapace.usage as usage_mod
from carapace.session.open_approvals import ORPHANED_APPROVAL_MESSAGE
from carapace.usage import LlmRequestState, ModelUsage
from carapace.ws_models import ApprovalRequest
from tests.session_helpers import _FakeSubscriber, _make_engine, _patch_sentinel, _without_timestamps


def test_subscribe_duplicate_prevention(tmp_path: Path, db_factory):
    """Subscribing the same subscriber twice does not duplicate it."""
    with _patch_sentinel():
        engine = _make_engine(tmp_path, session_factory=db_factory)
        state = engine.session_mgr.create_session(user="thies")
        sid = state.session_id

        sub = _FakeSubscriber()
        engine.subscribe(sid, sub)
        engine.subscribe(sid, sub)

        active = engine.get_active(sid)
        assert active is not None
        assert active.subscribers.count(sub) == 1


def test_get_active_returns_none_before_activation(tmp_path: Path, db_factory):
    """get_active returns None for a session that hasn't been activated."""
    engine = _make_engine(tmp_path, session_factory=db_factory)
    state = engine.session_mgr.create_session(user="thies")
    assert engine.get_active(state.session_id) is None


def test_get_or_activate_loads_session(tmp_path: Path, db_factory):
    """get_or_activate loads the session from disk and makes it active."""
    with _patch_sentinel():
        engine = _make_engine(tmp_path, session_factory=db_factory)
        state = engine.session_mgr.create_session(user="thies")
        sid = state.session_id

        assert engine.get_active(sid) is None
        active = engine.get_or_activate(sid)
        assert active is not None
        assert active.state.session_id == sid
        assert engine.get_active(sid) is active


def test_get_or_activate_unknown_session_raises(tmp_path: Path, db_factory):
    """get_or_activate raises KeyError for a nonexistent session."""
    engine = _make_engine(tmp_path, session_factory=db_factory)
    with pytest.raises(KeyError):
        engine.get_or_activate("nonexistent")


def test_deactivate_removes_session(tmp_path: Path, db_factory):
    """deactivate removes the session from active memory."""
    with _patch_sentinel():
        engine = _make_engine(tmp_path, session_factory=db_factory)
        state = engine.session_mgr.create_session(user="thies")
        sid = state.session_id

        engine.get_or_activate(sid)
        assert engine.get_active(sid) is not None

        engine.deactivate(sid)
        assert engine.get_active(sid) is None


def test_deactivate_idempotent(tmp_path: Path, db_factory):
    """Deactivating an already-deactivated session does not raise."""
    engine = _make_engine(tmp_path, session_factory=db_factory)
    engine.deactivate("nonexistent")


def test_unsubscribe_removes_subscriber(tmp_path: Path, db_factory):
    """unsubscribe removes the subscriber from the list."""
    with _patch_sentinel():
        engine = _make_engine(tmp_path, session_factory=db_factory)
        state = engine.session_mgr.create_session(user="thies")
        sid = state.session_id

        sub = _FakeSubscriber()
        engine.subscribe(sid, sub)
        active = engine.get_active(sid)
        assert active is not None
        assert sub in active.subscribers

        engine.unsubscribe(sid, sub)
        assert sub not in active.subscribers


def test_unsubscribe_nonexistent_is_safe(tmp_path: Path, db_factory):
    """Unsubscribing a subscriber that was never added does not raise."""
    with _patch_sentinel():
        engine = _make_engine(tmp_path, session_factory=db_factory)
        state = engine.session_mgr.create_session(user="thies")
        sid = state.session_id

        engine.get_or_activate(sid)
        engine.unsubscribe(sid, _FakeSubscriber())


def test_unsubscribe_saves_usage_when_last(tmp_path: Path, db_factory):
    """Usage is persisted to disk when the last subscriber disconnects."""
    with _patch_sentinel():
        engine = _make_engine(tmp_path, session_factory=db_factory)
        state = engine.session_mgr.create_session(user="thies")
        sid = state.session_id

        sub = _FakeSubscriber()
        engine.subscribe(sid, sub)

        active = engine.get_active(sid)
        assert active is not None
        active.usage_tracker.models["test-model"] = ModelUsage(input_tokens=42)

        engine.unsubscribe(sid, sub)

        reloaded = engine.session_mgr.load_usage(sid)
        assert reloaded.total_input == 42


def test_submit_message_busy_broadcasts_error(tmp_path: Path, db_factory):
    """submit_message rejects with an error if agent is already running."""

    async def _run() -> None:
        engine = _make_engine(tmp_path, session_factory=db_factory)
        state = engine.session_mgr.create_session(user="thies")
        sid = state.session_id

        sub = _FakeSubscriber()
        engine.subscribe(sid, sub)

        active = engine.get_active(sid)
        assert active is not None
        active.agent_task = asyncio.create_task(asyncio.sleep(999))

        await engine.submit_message(sid, "should fail")

        assert any("busy" in e.lower() for e in sub.errors)

        active.agent_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await active.agent_task

    with _patch_sentinel():
        asyncio.run(_run())


def test_submit_cancel_stops_task(tmp_path: Path, db_factory):
    """submit_cancel cancels the running agent task."""

    async def _run() -> None:
        engine = _make_engine(tmp_path, session_factory=db_factory)
        state = engine.session_mgr.create_session(user="thies")
        sid = state.session_id

        engine.subscribe(sid, _FakeSubscriber())
        active = engine.get_active(sid)
        assert active is not None

        active.agent_task = asyncio.create_task(asyncio.sleep(999))

        await engine.submit_cancel(sid)
        assert active.agent_task is None

    with _patch_sentinel():
        asyncio.run(_run())


def test_submit_cancel_persists_interruption_marker(tmp_path: Path, db_factory):
    """Cancelled turns are persisted with a terminal assistant message."""

    async def _run() -> None:
        engine = _make_engine(tmp_path, session_factory=db_factory)
        state = engine.session_mgr.create_session(user="thies")
        sid = state.session_id

        sub = _FakeSubscriber()
        engine.subscribe(sid, sub)

        async def _hanging_turn(*_args: Any, **_kwargs: Any) -> tuple[list[Any], str, str]:
            await asyncio.sleep(999)
            return [], "unreachable", ""

        with patch("carapace.session.engine.run_agent_turn", new=_hanging_turn):
            await engine.submit_message(sid, "hello")
            await asyncio.sleep(0.05)
            await engine.submit_cancel(sid)

        history = engine.session_mgr.load_history(sid)
        assert len(history) == 2
        assert isinstance(history[0], ModelRequest)
        assert any(isinstance(part, UserPromptPart) and part.content == "hello" for part in history[0].parts)
        assert isinstance(history[1], ModelResponse)
        assert any(
            isinstance(part, TextPart) and part.content == "The previous turn was interrupted before completion."
            for part in history[1].parts
        )

        events = engine.session_mgr.load_events(sid)
        assert all("timestamp" in event for event in events[-2:])
        assert _without_timestamps(events[-2:]) == [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "The previous turn was interrupted before completion."},
        ]
        assert sub.cancelled == 1

    with _patch_sentinel():
        asyncio.run(_run())


def test_submit_cancel_persists_interrupted_llm_request_log(tmp_path: Path, db_factory):
    """Cancelled in-flight LLM requests are saved in the request log as interrupted."""

    async def _run() -> None:
        engine = _make_engine(tmp_path, session_factory=db_factory)
        state = engine.session_mgr.create_session(user="thies")
        sid = state.session_id

        engine.subscribe(sid, _FakeSubscriber())

        started_at = datetime(2026, 5, 2, 12, 0, tzinfo=UTC)

        request_state = LlmRequestState(
            request_id="req-1",
            source="agent",
            model_name="anthropic:claude-haiku-4-5",
            started_at=started_at,
            phase="thinking",
            first_thinking_at=started_at,
            last_thinking_at=started_at + timedelta(seconds=1),
        )

        async def _hanging_turn(*_args: Any, **_kwargs: Any) -> tuple[list[Any], str, str]:
            sink = usage_mod._llm_request_sink.get()
            assert sink is not None
            await sink.on_request_started(request_state)
            await asyncio.sleep(999)
            return [], "unreachable", ""

        with patch("carapace.session.engine.run_agent_turn", new=_hanging_turn):
            await engine.submit_message(sid, "hello")
            await asyncio.sleep(0.05)
            await engine.submit_cancel(sid)

        log = engine.session_mgr.load_llm_request_log(sid)
        assert len(log.records) == 1
        record = log.records[0]
        assert record.request_id == "req-1"
        assert record.source == "agent"
        assert record.model_name == "anthropic:claude-haiku-4-5"
        assert record.outcome == "interrupted"
        assert record.input_tokens == 0
        assert record.output_tokens == 0
        assert record.started_at == started_at
        assert record.first_thinking_at == started_at
        assert record.last_thinking_at == started_at + timedelta(seconds=1)
        assert record.completed_at is None
        assert engine.session_mgr.load_llm_request_state(sid) is None

    with _patch_sentinel():
        asyncio.run(_run())


def test_submit_cancel_noop_when_inactive(tmp_path: Path, db_factory):
    """submit_cancel is a no-op when session is not active."""

    async def _run() -> None:
        engine = _make_engine(tmp_path, session_factory=db_factory)
        await engine.submit_cancel("nonexistent")

    asyncio.run(_run())


def test_submit_cancel_closes_pending_tool_approval(tmp_path: Path, db_factory):
    """A tool approval the cancelled turn waited on is denied by the system inside the turn."""

    async def _run() -> None:
        engine = _make_engine(tmp_path, session_factory=db_factory)
        sid = engine.session_mgr.create_session(user="thies").session_id
        engine.subscribe(sid, _FakeSubscriber())
        active = engine.get_active(sid)
        assert active is not None

        async def _turn_awaiting_approval(*_args: Any, **kwargs: Any) -> tuple[list[Any], str, str]:
            await kwargs["send_approval_request"](ApprovalRequest(tool_call_id="call-1", tool="exec", args={}))
            await kwargs["collect_approvals"]({"call-1"})
            return [], "unreachable", ""

        with patch("carapace.session.engine.run_agent_turn", new=_turn_awaiting_approval):
            await engine.submit_message(sid, "hello")
            await asyncio.sleep(0.05)
            assert active.pending_approval_requests
            await engine.submit_cancel(sid)

        events = _without_timestamps(engine.session_mgr.load_events(sid))
        assert [event["role"] for event in events] == ["user", "approval_request", "approval_response", "assistant"]
        assert events[2] == {
            "role": "approval_response",
            "tool_call_id": "call-1",
            "decision": "denied",
            "decision_source": "system",
            "message": ORPHANED_APPROVAL_MESSAGE,
        }
        assert active.pending_approval_requests == []

    with _patch_sentinel():
        asyncio.run(_run())


def test_failed_turn_closes_pending_escalation_and_releases_its_waiter(tmp_path: Path, db_factory):
    """An escalation still open when the turn fails is denied and its callback stops waiting."""

    async def _run() -> None:
        engine = _make_engine(tmp_path, session_factory=db_factory)
        sid = engine.session_mgr.create_session(user="thies").session_id
        engine.subscribe(sid, _FakeSubscriber())
        active = engine.get_active(sid)
        assert active is not None
        escalate = engine._make_escalation_cb(active)
        waiters: list[asyncio.Task[Any]] = []

        async def _turn_failing_during_escalation(*_args: Any, **_kwargs: Any) -> tuple[list[Any], str, str]:
            # Escalations block in proxy/git/credential request tasks, not in the turn task.
            waiters.append(
                asyncio.create_task(escalate(sid, "evil.example", {"kind": "domain_access", "command": "curl"}))
            )
            await asyncio.sleep(0)
            raise RuntimeError("model exploded")

        with patch("carapace.session.engine.run_agent_turn", new=_turn_failing_during_escalation):
            await engine.submit_message(sid, "hello")
            assert active.agent_task is not None
            await active.agent_task

        decision = await asyncio.wait_for(waiters[0], timeout=1)
        assert decision.allowed is False
        assert active.pending_escalations == []

        events = _without_timestamps(engine.session_mgr.load_events(sid))
        assert [event["role"] for event in events] == [
            "user",
            "domain_access_approval",
            "domain_access_approval",
            "assistant",
        ]
        assert events[2] == {
            "role": "domain_access_approval",
            "request_id": events[1]["request_id"],
            "domain": "evil.example",
            "command": "curl",
            "decision": "deny",
            "decision_source": "system",
            "message": ORPHANED_APPROVAL_MESSAGE,
        }

    with _patch_sentinel():
        asyncio.run(_run())


def test_cancel_closes_escalation_whose_waiter_saw_the_cancel_first(tmp_path: Path, db_factory):
    """The escalation waiter can consume submit_cancel's signal before the turn finalizes.

    It then drops its pending entry without writing a response, so only the event log still
    shows the request as open.
    """

    async def _run() -> None:
        engine = _make_engine(tmp_path, session_factory=db_factory)
        sid = engine.session_mgr.create_session(user="thies").session_id
        engine.subscribe(sid, _FakeSubscriber())
        active = engine.get_active(sid)
        assert active is not None
        escalate = engine._make_escalation_cb(active)
        waiters: list[asyncio.Task[Any]] = []

        async def _turn_with_suspending_cleanup(*_args: Any, **_kwargs: Any) -> tuple[list[Any], str, str]:
            waiters.append(
                asyncio.create_task(escalate(sid, "evil.example", {"kind": "domain_access", "command": "curl"}))
            )
            try:
                await asyncio.sleep(999)
            finally:
                # Tool and stream cleanup suspends while the cancellation unwinds.
                await asyncio.sleep(0.01)
            return [], "unreachable", ""

        with patch("carapace.session.engine.run_agent_turn", new=_turn_with_suspending_cleanup):
            await engine.submit_message(sid, "hello")
            await asyncio.sleep(0.05)
            await engine.submit_cancel(sid)

        assert (await asyncio.wait_for(waiters[0], timeout=1)).allowed is False
        assert active.pending_escalations == []
        events = _without_timestamps(engine.session_mgr.load_events(sid))
        assert [event["role"] for event in events] == [
            "user",
            "domain_access_approval",
            "domain_access_approval",
            "assistant",
        ]
        assert events[2]["decision"] == "deny"
        assert events[2]["decision_source"] == "system"

    with _patch_sentinel():
        asyncio.run(_run())


def test_turn_without_approvals_leaves_events_alone(tmp_path: Path, db_factory):
    """A turn that raised no approval request appends no closing events."""

    async def _run() -> None:
        engine = _make_engine(tmp_path, session_factory=db_factory)
        sid = engine.session_mgr.create_session(user="thies").session_id
        engine.subscribe(sid, _FakeSubscriber())
        active = engine.get_active(sid)
        assert active is not None

        async def _plain_turn(*_args: Any, **_kwargs: Any) -> tuple[list[Any], str, str, None]:
            return [], "done", "", None

        with patch("carapace.session.engine.run_agent_turn", new=_plain_turn):
            await engine.submit_message(sid, "hello")
            assert active.agent_task is not None
            await active.agent_task

        events = _without_timestamps(engine.session_mgr.load_events(sid))
        assert [event["role"] for event in events] == ["user", "assistant"]

    with _patch_sentinel():
        asyncio.run(_run())


def test_retry_latest_turn_rewinds_and_restarts(tmp_path: Path, db_factory):
    async def _run() -> None:
        engine = _make_engine(tmp_path, session_factory=db_factory)
        state = engine.session_mgr.create_session(user="thies")
        sid = state.session_id

        sub = _FakeSubscriber()
        engine.subscribe(sid, sub)

        engine.session_mgr.save_events(
            sid,
            [
                {"role": "user", "content": "first"},
                {"role": "assistant", "content": "first answer"},
                {"role": "user", "content": "second"},
                {"role": "assistant", "content": "second answer"},
            ],
        )
        engine.session_mgr.save_history(
            sid,
            [
                ModelRequest(parts=[UserPromptPart(content="first")]),
                ModelResponse(parts=[TextPart(content="first answer")]),
                ModelRequest(parts=[UserPromptPart(content="second")]),
                ModelResponse(parts=[TextPart(content="second answer")]),
            ],
        )

        async def _fake_run_turn(
            user_input: str,
            _deps: Any,
            message_history: list[Any],
            **_kwargs: Any,
        ) -> tuple[list[Any], str, str, None]:
            assert user_input == "second"
            assert len(message_history) == 2
            assert isinstance(message_history[0], ModelRequest)
            assert isinstance(message_history[1], ModelResponse)
            return (
                [
                    *message_history,
                    ModelRequest(parts=[UserPromptPart(content=user_input)]),
                    ModelResponse(parts=[TextPart(content="retried answer")]),
                ],
                "retried answer",
                "",
                None,
            )

        with patch("carapace.session.engine.run_agent_turn", new=_fake_run_turn):
            await engine.retry_latest_turn(sid, origin=sub)
            active = engine.get_active(sid)
            assert active is not None and active.agent_task is not None
            await active.agent_task

        events = engine.session_mgr.load_events(sid)
        assert _without_timestamps(events) == [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "first answer"},
            {"role": "user", "content": "second"},
            {"role": "assistant", "content": "retried answer"},
        ]

        history = engine.session_mgr.load_history(sid)
        assert len(history) == 4
        assert isinstance(history[-1], ModelResponse)
        assert any(isinstance(part, TextPart) and part.content == "retried answer" for part in history[-1].parts)

    with _patch_sentinel():
        asyncio.run(_run())


def test_retry_latest_turn_after_failure_uses_terminal_marker_history(tmp_path: Path, db_factory):
    async def _run() -> None:
        engine = _make_engine(tmp_path, session_factory=db_factory)
        sid = engine.session_mgr.create_session(user="thies").session_id

        engine.session_mgr.save_events(
            sid,
            [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "The previous turn failed before completion."},
            ],
        )
        engine.session_mgr.save_history(
            sid,
            [
                ModelRequest(parts=[UserPromptPart(content="hello")]),
                ModelResponse(parts=[TextPart(content="The previous turn failed before completion.")]),
            ],
        )

        async def _fake_run_turn(
            user_input: str,
            _deps: Any,
            message_history: list[Any],
            **_kwargs: Any,
        ) -> tuple[list[Any], str, str, None]:
            assert user_input == "hello"
            assert message_history == []
            return (
                [
                    ModelRequest(parts=[UserPromptPart(content=user_input)]),
                    ModelResponse(parts=[TextPart(content="recovered")]),
                ],
                "recovered",
                "",
                None,
            )

        with patch("carapace.session.engine.run_agent_turn", new=_fake_run_turn):
            await engine.retry_latest_turn(sid)
            active = engine.get_active(sid)
            assert active is not None and active.agent_task is not None
            await active.agent_task

        events = engine.session_mgr.load_events(sid)
        assert _without_timestamps(events) == [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "recovered"},
        ]

    with _patch_sentinel():
        asyncio.run(_run())


def test_reset_to_turn_rewinds_later_turns(tmp_path: Path, db_factory):
    async def _run() -> None:
        engine = _make_engine(tmp_path, session_factory=db_factory)
        sid = engine.session_mgr.create_session(user="thies").session_id

        engine.session_mgr.save_events(
            sid,
            [
                {"role": "user", "content": "first"},
                {"role": "assistant", "content": "first answer"},
                {"role": "user", "content": "second"},
                {"role": "assistant", "content": "second answer"},
            ],
        )
        engine.session_mgr.save_history(
            sid,
            [
                ModelRequest(parts=[UserPromptPart(content="first")]),
                ModelResponse(parts=[TextPart(content="first answer")]),
                ModelRequest(parts=[UserPromptPart(content="second")]),
                ModelResponse(parts=[TextPart(content="second answer")]),
            ],
        )

        reset_applied = await engine.reset_to_turn(sid, 1)

        assert reset_applied is True

        events = engine.session_mgr.load_events(sid)
        assert _without_timestamps(events) == [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "first answer"},
        ]

        history = engine.session_mgr.load_history(sid)
        assert len(history) == 2
        assert isinstance(history[0], ModelRequest)
        assert isinstance(history[1], ModelResponse)

    with _patch_sentinel():
        asyncio.run(_run())


def test_reset_to_turn_rejects_unknown_target(tmp_path: Path, db_factory):
    async def _run() -> None:
        engine = _make_engine(tmp_path, session_factory=db_factory)
        sid = engine.session_mgr.create_session(user="thies").session_id
        sub = _FakeSubscriber()
        engine.subscribe(sid, sub)

        engine.session_mgr.save_events(
            sid,
            [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "world"},
            ],
        )

        reset_applied = await engine.reset_to_turn(sid, 99)

        assert reset_applied is False
        assert sub.errors == ["Unknown reset target"]
        assert sub.error_events == [("Unknown reset target", False)]

    with _patch_sentinel():
        asyncio.run(_run())


def test_history_for_completed_turn_count_excludes_trailing_incomplete_request(tmp_path: Path, db_factory):
    with _patch_sentinel():
        engine = _make_engine(tmp_path, session_factory=db_factory)

    history = [
        ModelRequest(parts=[UserPromptPart(content="first")]),
        ModelResponse(parts=[TextPart(content="first answer")]),
        ModelRequest(parts=[UserPromptPart(content="second")]),
    ]

    assert engine._completed_model_turn_end_indexes(history) == [1]
    assert engine._history_for_completed_turn_count(history, 2) == history[:2]
