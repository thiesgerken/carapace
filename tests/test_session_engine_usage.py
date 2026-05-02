"""SessionEngine slash command, usage, and budget-related tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import carapace.usage as usage_mod
from carapace.models import SessionBudget
from carapace.usage import LlmRequestRecord, LlmRequestState, ModelUsage
from tests.session_helpers import (
    _FakeSubscriber,
    _make_engine,
    _patch_sentinel,
    _sandbox_refresh_snapshot_mock,
    _without_timestamp,
)


def test_handle_slash_command_session(tmp_path: Path):
    """handle_slash_command /session returns session metadata."""
    with _patch_sentinel():
        engine = _make_engine(tmp_path)
        state = engine.session_mgr.create_session()
        sid = state.session_id
        engine.get_or_activate(sid)

        async def _run() -> None:
            result = await engine.handle_slash_command(sid, "/session")
            assert result is not None
            assert result["command"] == "session"
            assert result["data"]["session_id"] == sid

        asyncio.run(_run())


def test_handle_slash_command_unknown(tmp_path: Path):
    """handle_slash_command returns None for unknown commands."""
    with _patch_sentinel():
        engine = _make_engine(tmp_path)
        state = engine.session_mgr.create_session()
        sid = state.session_id
        engine.get_or_activate(sid)

        async def _run() -> None:
            assert await engine.handle_slash_command(sid, "/nonexistent") is None

        asyncio.run(_run())


def test_handle_slash_command_retitle_sets_title(tmp_path: Path):
    """``/retitle TEXT`` stores the title and returns a message."""
    with _patch_sentinel():
        engine = _make_engine(tmp_path)
        state = engine.session_mgr.create_session()
        sid = state.session_id
        active = engine.get_or_activate(sid)

        async def _run() -> None:
            result = await engine.handle_slash_command(sid, "/retitle Hello world")
            assert result is not None
            assert result["command"] == "retitle"
            assert "Hello world" in result["data"]["message"]
            assert active.state.title == "Hello world"
            reloaded = engine.session_mgr.load_state(sid)
            assert reloaded is not None
            assert reloaded.title == "Hello world"

        asyncio.run(_run())


def test_handle_slash_command_retitle_regenerates(tmp_path: Path):
    """``/retitle`` with no args runs title generation."""
    with _patch_sentinel():
        engine = _make_engine(tmp_path)
        state = engine.session_mgr.create_session()
        sid = state.session_id
        active = engine.get_or_activate(sid)
        engine.session_mgr.append_events(sid, [{"role": "user", "content": "talk about cats"}])

        async def _run() -> None:
            with patch(
                "carapace.session.engine.generate_title",
                new=AsyncMock(return_value="📌 Cats chat"),
            ):
                result = await engine.handle_slash_command(sid, "/retitle")
            assert result is not None
            assert result["command"] == "retitle"
            assert "Cats chat" in result["data"]["message"]
            assert active.state.title == "📌 Cats chat"

        asyncio.run(_run())


def test_handle_slash_command_budget_sets_and_clears(tmp_path: Path):
    with _patch_sentinel():
        engine = _make_engine(tmp_path)
        state = engine.session_mgr.create_session()
        sid = state.session_id
        engine.get_or_activate(sid)

        async def _run() -> None:
            initial = await engine.handle_slash_command(sid, "/budget")
            assert initial is not None
            assert "usage_hint" in initial["data"]
            assert "/budget input N" in initial["data"]["usage_hint"]
            assert "/budget tools N" in initial["data"]["usage_hint"]

            set_result = await engine.handle_slash_command(sid, "/budget input 1000")
            assert set_result is not None
            assert set_result["command"] == "budget"
            assert set_result["data"]["message"] == "Set input token budget to 1,000 tokens."
            assert set_result["data"]["gauges"][0]["key"] == "input"

            cleared = await engine.handle_slash_command(sid, "/budget input 0")
            assert cleared is not None
            assert cleared["data"]["message"] == "Cleared input token budget."
            assert cleared["data"]["gauges"] == []

            reloaded = engine.session_mgr.load_state(sid)
            assert reloaded is not None
            assert reloaded.budget.input_tokens is None

        asyncio.run(_run())


def test_handle_slash_command_budget_sets_tool_call_limit(tmp_path: Path):
    with _patch_sentinel():
        engine = _make_engine(tmp_path)
        state = engine.session_mgr.create_session()
        sid = state.session_id
        engine.get_or_activate(sid)

        async def _run() -> None:
            result = await engine.handle_slash_command(sid, "/budget tools 3")

            assert result is not None
            assert result["command"] == "budget"
            assert result["data"]["message"] == "Set tool call budget to 3 tool calls."
            assert result["data"]["gauges"][0]["key"] == "tool_calls"

            reloaded = engine.session_mgr.load_state(sid)
            assert reloaded is not None
            assert reloaded.budget.tool_calls == 3

        asyncio.run(_run())


def test_handle_slash_command_budget_accepts_k_and_m_suffixes(tmp_path: Path):
    with _patch_sentinel():
        engine = _make_engine(tmp_path)
        state = engine.session_mgr.create_session()
        sid = state.session_id
        engine.get_or_activate(sid)

        async def _run() -> None:
            input_result = await engine.handle_slash_command(sid, "/budget input 100k")
            assert input_result is not None
            assert input_result["data"]["message"] == "Set input token budget to 100,000 tokens."

            output_result = await engine.handle_slash_command(sid, "/budget output 2M")
            assert output_result is not None
            assert output_result["data"]["message"] == "Set output token budget to 2,000,000 tokens."

            reloaded = engine.session_mgr.load_state(sid)
            assert reloaded is not None
            assert reloaded.budget.input_tokens == 100_000
            assert reloaded.budget.output_tokens == 2_000_000

        asyncio.run(_run())


def test_handle_slash_command_help_lists_budget(tmp_path: Path):
    with _patch_sentinel():
        engine = _make_engine(tmp_path)
        state = engine.session_mgr.create_session()
        sid = state.session_id
        engine.get_or_activate(sid)

        async def _run() -> None:
            result = await engine.handle_slash_command(sid, "/help")
            assert result is not None
            commands = result["data"]["commands"]
            assert any(item["command"] == "/budget" for item in commands)

        asyncio.run(_run())


def test_handle_slash_command_usage_includes_tool_call_total(tmp_path: Path):
    with _patch_sentinel():
        engine = _make_engine(tmp_path)
        state = engine.session_mgr.create_session()
        sid = state.session_id
        active = engine.get_or_activate(sid)
        active.usage_tracker.record_tool_call()
        active.usage_tracker.record_tool_call()

        async def _run() -> None:
            result = await engine.handle_slash_command(sid, "/usage")

            assert result is not None
            assert result["command"] == "usage"
            assert result["data"]["total_tool_calls"] == 2

        asyncio.run(_run())


def test_turn_usage_payload_contains_budget_gauges_without_agent_usage(tmp_path: Path):
    with _patch_sentinel():
        engine = _make_engine(tmp_path)
        state = engine.session_mgr.create_session(budget=SessionBudget(input_tokens=1_000))
        active = engine.get_or_activate(state.session_id)

        payload = engine._turn_usage_payload(active)

        assert payload is not None
        assert payload.budget_gauges[0].key == "input"
        assert payload.budget_gauges[0].current_value == "0 tokens"


def test_turn_usage_payload_includes_reasoning_metrics(tmp_path: Path) -> None:
    with _patch_sentinel():
        engine = _make_engine(tmp_path)
        state = engine.session_mgr.create_session()
        active = engine.get_or_activate(state.session_id)
        started_at = datetime.now(tz=UTC)
        active.llm_request_log.records.append(
            LlmRequestRecord(
                ts=started_at + timedelta(seconds=5),
                source="agent",
                model_name="anthropic:claude-haiku-4-5",
                input_tokens=100,
                output_tokens=20,
                started_at=started_at,
                first_thinking_at=started_at + timedelta(seconds=1),
                last_thinking_at=started_at + timedelta(seconds=2),
                first_text_at=started_at + timedelta(seconds=3),
                completed_at=started_at + timedelta(seconds=5),
                reasoning_tokens=42,
            )
        )

        payload = engine._turn_usage_payload(active)

        assert payload is not None
        assert payload.ttft_ms == 3000
        assert payload.reasoning_duration_ms == 2000
        assert payload.total_duration_ms == 5000
        assert payload.reasoning_tokens == 42


def test_activate_clears_stale_llm_request_state(tmp_path: Path) -> None:
    with _patch_sentinel():
        engine = _make_engine(tmp_path)
        state = engine.session_mgr.create_session()
        engine.session_mgr.save_llm_request_state(
            state.session_id,
            LlmRequestState(
                request_id="stale",
                source="agent",
                model_name="anthropic:claude-haiku-4-5",
                started_at=datetime.now(tz=UTC),
                phase="thinking",
            ),
        )

        active = engine.get_or_activate(state.session_id)

        assert active.llm_request_state is None
        assert engine.session_mgr.load_llm_request_state(state.session_id) is None


def test_llm_request_recording_persists_request_level_thinking_event(tmp_path: Path) -> None:
    async def _run() -> None:
        with _patch_sentinel():
            engine = _make_engine(tmp_path)
            state = engine.session_mgr.create_session()
            active = engine.get_or_activate(state.session_id)
            started_at = datetime.now(tz=UTC)
            request_state = LlmRequestState(
                request_id="req-1",
                source="agent",
                model_name="anthropic:claude-haiku-4-5",
                started_at=started_at,
                phase="thinking",
                first_thinking_at=started_at,
            )
            record = LlmRequestRecord(
                ts=started_at + timedelta(seconds=2),
                request_id="req-1",
                source="agent",
                model_name="anthropic:claude-haiku-4-5",
                started_at=started_at,
                first_thinking_at=started_at,
                first_text_at=started_at + timedelta(seconds=1),
                completed_at=started_at + timedelta(seconds=2),
                reasoning_tokens=17,
            )

            with engine.llm_request_recording(active):
                observer = usage_mod._llm_request_sink.get()
                assert observer is not None
                await observer.on_request_started(request_state)
                active.llm_request_thinking["req-1"] = "first thought"
                await observer.on_request_completed(record)

            events = engine.session_mgr.load_events(state.session_id)
            assert "timestamp" in events[-1]
            assert _without_timestamp(events[-1]) == {
                "role": "thinking",
                "content": "first thought",
                "request_id": "req-1",
                "reasoning_duration_ms": 1000,
                "reasoning_tokens": 17,
            }

    asyncio.run(_run())


def test_llm_request_recording_persists_timing_for_tool_only_thinking_event(tmp_path: Path) -> None:
    async def _run() -> None:
        with _patch_sentinel():
            engine = _make_engine(tmp_path)
            state = engine.session_mgr.create_session()
            active = engine.get_or_activate(state.session_id)
            started_at = datetime.now(tz=UTC)
            request_state = LlmRequestState(
                request_id="req-tool",
                source="agent",
                model_name="anthropic:claude-haiku-4-5",
                started_at=started_at,
                phase="thinking",
                first_thinking_at=started_at,
            )
            record = LlmRequestRecord(
                ts=started_at + timedelta(seconds=3),
                request_id="req-tool",
                source="agent",
                model_name="anthropic:claude-haiku-4-5",
                started_at=started_at,
                first_thinking_at=started_at,
                completed_at=started_at + timedelta(seconds=3),
                reasoning_tokens=9,
            )

            with engine.llm_request_recording(active):
                observer = usage_mod._llm_request_sink.get()
                assert observer is not None
                await observer.on_request_started(request_state)
                active.llm_request_thinking["req-tool"] = "tool-only thought"
                await observer.on_request_completed(record)

            events = engine.session_mgr.load_events(state.session_id)
            assert "timestamp" in events[-1]
            assert _without_timestamp(events[-1]) == {
                "role": "thinking",
                "content": "tool-only thought",
                "request_id": "req-tool",
                "reasoning_duration_ms": 3000,
                "reasoning_tokens": 9,
            }

    asyncio.run(_run())


def test_submit_message_budget_exhausted_broadcasts_error(tmp_path: Path):
    async def _run() -> None:
        engine = _make_engine(tmp_path)
        state = engine.session_mgr.create_session(budget=SessionBudget(input_tokens=100))
        sid = state.session_id
        sub = _FakeSubscriber()
        engine.subscribe(sid, sub)
        active = engine.get_active(sid)
        assert active is not None
        active.usage_tracker.models["test-model"] = ModelUsage(input_tokens=120)

        with patch("carapace.session.engine.run_agent_turn", new=AsyncMock()) as mocked_turn:
            await engine.submit_message(sid, "hello")
            await asyncio.sleep(0.1)

        mocked_turn.assert_not_awaited()
        assert any("Session budget reached" in err for err in sub.errors)

    with _patch_sentinel():
        asyncio.run(_run())


def test_submit_message_tool_call_budget_exhausted_broadcasts_error(tmp_path: Path):
    async def _run() -> None:
        engine = _make_engine(tmp_path)
        state = engine.session_mgr.create_session(budget=SessionBudget(tool_calls=1))
        sid = state.session_id
        sub = _FakeSubscriber()
        engine.subscribe(sid, sub)

        async def _fail_on_second_tool_call(
            _user_input: str,
            deps: Any,
            _message_history: list[Any],
            *_args: Any,
            **_kwargs: Any,
        ) -> tuple[list[Any], str, str]:
            callback = deps.tool_call_callback
            assert callback is not None
            callback("read", {"path": "README.md"}, "[safe-list] auto-allowed", "safe-list", "allow", "ok")
            callback("read", {"path": "README.md"}, "[safe-list] auto-allowed", "safe-list", "allow", "ok")
            return [], "done", ""

        with patch("carapace.session.engine.run_agent_turn", new=_fail_on_second_tool_call):
            await engine.submit_message(sid, "hello")
            await asyncio.sleep(0.1)

        active = engine.get_active(sid)
        assert active is not None
        assert active.usage_tracker.tool_calls == 1
        assert any("Session budget reached: tool calls 1 tool calls / 1 tool calls" in err for err in sub.errors)

    with _patch_sentinel():
        asyncio.run(_run())


def test_submit_message_refreshes_sandbox_once_after_completed_turn(tmp_path: Path):
    async def _run() -> None:
        engine = _make_engine(tmp_path)
        state = engine.session_mgr.create_session()
        sid = state.session_id
        sub = _FakeSubscriber()
        engine.subscribe(sid, sub)

        async def _complete_turn(*_args: Any, **_kwargs: Any) -> tuple[list[Any], str, str]:
            return [], "done", "thinking"

        with patch("carapace.session.engine.run_agent_turn", new=_complete_turn):
            await engine.submit_message(sid, "hello")
            await asyncio.sleep(0.1)

        _sandbox_refresh_snapshot_mock(engine).assert_awaited_once_with(sid, measure_usage=True)

    with _patch_sentinel():
        asyncio.run(_run())


def test_submit_message_refresh_failure_does_not_block_completed_turn(tmp_path: Path):
    async def _run() -> None:
        engine = _make_engine(tmp_path)
        state = engine.session_mgr.create_session()
        sid = state.session_id
        sub = _FakeSubscriber()
        engine.subscribe(sid, sub)

        async def _complete_turn(*_args: Any, **_kwargs: Any) -> tuple[list[Any], str, str]:
            return [], "done", "thinking"

        _sandbox_refresh_snapshot_mock(engine).side_effect = RuntimeError("snapshot refresh failed")

        with patch("carapace.session.engine.run_agent_turn", new=_complete_turn):
            await engine.submit_message(sid, "hello")
            await asyncio.sleep(0.1)

        assert sub.errors == []
        event = engine.session_mgr.load_events(sid)[-1]
        assert "timestamp" in event
        assert _without_timestamp(event) == {"role": "assistant", "content": "done"}

    with _patch_sentinel():
        asyncio.run(_run())
