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
from carapace.usage import LlmRequestState, ModelUsage
from tests.session_helpers import _FakeSubscriber, _make_engine, _patch_sentinel, _without_timestamps


def test_subscribe_duplicate_prevention(tmp_path: Path):
    """Subscribing the same subscriber twice does not duplicate it."""
    with _patch_sentinel():
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
    with _patch_sentinel():
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
    engine = _make_engine(tmp_path)
    with pytest.raises(KeyError):
        engine.get_or_activate("nonexistent")


def test_deactivate_removes_session(tmp_path: Path):
    """deactivate removes the session from active memory."""
    with _patch_sentinel():
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
    engine.deactivate("nonexistent")


def test_unsubscribe_removes_subscriber(tmp_path: Path):
    """unsubscribe removes the subscriber from the list."""
    with _patch_sentinel():
        engine = _make_engine(tmp_path)
        state = engine.session_mgr.create_session()
        sid = state.session_id

        sub = _FakeSubscriber()
        engine.subscribe(sid, sub)
        active = engine.get_active(sid)
        assert active is not None
        assert sub in active.subscribers

        engine.unsubscribe(sid, sub)
        assert sub not in active.subscribers


def test_unsubscribe_nonexistent_is_safe(tmp_path: Path):
    """Unsubscribing a subscriber that was never added does not raise."""
    with _patch_sentinel():
        engine = _make_engine(tmp_path)
        state = engine.session_mgr.create_session()
        sid = state.session_id

        engine.get_or_activate(sid)
        engine.unsubscribe(sid, _FakeSubscriber())


def test_unsubscribe_saves_usage_when_last(tmp_path: Path):
    """Usage is persisted to disk when the last subscriber disconnects."""
    with _patch_sentinel():
        engine = _make_engine(tmp_path)
        state = engine.session_mgr.create_session()
        sid = state.session_id

        sub = _FakeSubscriber()
        engine.subscribe(sid, sub)

        active = engine.get_active(sid)
        assert active is not None
        active.usage_tracker.models["test-model"] = ModelUsage(input_tokens=42)

        engine.unsubscribe(sid, sub)

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


def test_submit_cancel_stops_task(tmp_path: Path):
    """submit_cancel cancels the running agent task."""

    async def _run() -> None:
        engine = _make_engine(tmp_path)
        state = engine.session_mgr.create_session()
        sid = state.session_id

        engine.subscribe(sid, _FakeSubscriber())
        active = engine.get_active(sid)
        assert active is not None

        active.agent_task = asyncio.create_task(asyncio.sleep(999))

        await engine.submit_cancel(sid)
        assert active.agent_task is None

    with _patch_sentinel():
        asyncio.run(_run())


def test_submit_cancel_persists_interruption_marker(tmp_path: Path):
    """Cancelled turns are persisted with a terminal assistant message."""

    async def _run() -> None:
        engine = _make_engine(tmp_path)
        state = engine.session_mgr.create_session()
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


def test_submit_cancel_persists_interrupted_llm_request_log(tmp_path: Path):
    """Cancelled in-flight LLM requests are saved in the request log as interrupted."""

    async def _run() -> None:
        engine = _make_engine(tmp_path)
        state = engine.session_mgr.create_session()
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


def test_submit_cancel_noop_when_inactive(tmp_path: Path):
    """submit_cancel is a no-op when session is not active."""

    async def _run() -> None:
        engine = _make_engine(tmp_path)
        await engine.submit_cancel("nonexistent")

    asyncio.run(_run())


def test_retry_latest_turn_rewinds_and_restarts(tmp_path: Path):
    async def _run() -> None:
        engine = _make_engine(tmp_path)
        state = engine.session_mgr.create_session()
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
        ) -> tuple[list[Any], str, str]:
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


def test_retry_latest_turn_after_failure_uses_terminal_marker_history(tmp_path: Path):
    async def _run() -> None:
        engine = _make_engine(tmp_path)
        sid = engine.session_mgr.create_session().session_id

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
        ) -> tuple[list[Any], str, str]:
            assert user_input == "hello"
            assert message_history == []
            return (
                [
                    ModelRequest(parts=[UserPromptPart(content=user_input)]),
                    ModelResponse(parts=[TextPart(content="recovered")]),
                ],
                "recovered",
                "",
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


def test_reset_to_turn_rewinds_later_turns(tmp_path: Path):
    async def _run() -> None:
        engine = _make_engine(tmp_path)
        sid = engine.session_mgr.create_session().session_id

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


def test_reset_to_turn_rejects_unknown_target(tmp_path: Path):
    async def _run() -> None:
        engine = _make_engine(tmp_path)
        sid = engine.session_mgr.create_session().session_id
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


def test_history_for_completed_turn_count_excludes_trailing_incomplete_request(tmp_path: Path):
    with _patch_sentinel():
        engine = _make_engine(tmp_path)

    history = [
        ModelRequest(parts=[UserPromptPart(content="first")]),
        ModelResponse(parts=[TextPart(content="first answer")]),
        ModelRequest(parts=[UserPromptPart(content="second")]),
    ]

    assert engine._completed_model_turn_end_indexes(history) == [1]
    assert engine._history_for_completed_turn_count(history, 2) == history[:2]
