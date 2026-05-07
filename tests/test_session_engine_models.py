"""SessionEngine model, title, truncation, and remaining integration tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai import ApprovalRequired
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, ToolCallPart, ToolReturnPart, UserPromptPart
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

import carapace.security as security_mod
import carapace.usage as usage_mod
from carapace.models import SessionBudget
from carapace.security.context import SentinelVerdict, SessionSecurity, ToolCallEntry
from carapace.security.sentinel import Sentinel
from carapace.session.turns import _non_slash_user_message_count
from carapace.usage import LlmRequestRecord, LlmRequestState, ModelUsage, SessionBudgetExceededError
from tests.session_helpers import (
    _FakeSubscriber,
    _make_engine,
    _patch_sentinel,
    _sandbox_reset_session_mock,
    _sentinel_set_model_mock,
)


def test_submit_message_budget_exceeded_persists_history(tmp_path: Path):
    async def _run() -> None:
        engine = _make_engine(tmp_path)
        state = engine.session_mgr.create_session(budget=SessionBudget(input_tokens=1_000))
        sid = state.session_id
        sub = _FakeSubscriber()
        engine.subscribe(sid, sub)

        async def _fail_run_agent_turn(*_args: Any, on_messages_snapshot=None, **_kwargs: Any):
            snapshot = [ModelRequest(parts=[UserPromptPart(content="hello")])]
            if on_messages_snapshot is not None:
                on_messages_snapshot(snapshot)
            raise SessionBudgetExceededError("Session budget reached: input 1.0k tokens / 1.0k tokens", gauges=[])

        with patch("carapace.session.engine.run_agent_turn", new=_fail_run_agent_turn):
            await engine.submit_message(sid, "hello")
            await asyncio.sleep(0.1)

        history = engine.session_mgr.load_history(sid)
        assert history
        assert isinstance(history[0], ModelRequest)
        assert any(isinstance(part, UserPromptPart) and part.content == "hello" for part in history[0].parts)
        assert isinstance(history[-1], ModelResponse)
        assert any(
            isinstance(part, TextPart) and part.content == "Session budget reached: input 1.0k tokens / 1.0k tokens"
            for part in history[-1].parts
        )

        events = engine.session_mgr.load_events(sid)
        assert "timestamp" in events[-1]
        assert events[-1]["role"] == "assistant"
        assert events[-1]["content"] == "Session budget reached: input 1.0k tokens / 1.0k tokens"
        assert any("Session budget reached" in err for err in sub.errors)
        assert any(
            detail.startswith("Session budget reached") and turn_terminal for detail, turn_terminal in sub.error_events
        )

    with _patch_sentinel():
        asyncio.run(_run())


def test_submit_message_unexpected_output_marks_terminal_error(tmp_path: Path):
    async def _run() -> None:
        engine = _make_engine(tmp_path)
        sid = engine.session_mgr.create_session().session_id
        sub = _FakeSubscriber()
        engine.subscribe(sid, sub)

        unexpected = "Unexpected agent output type: {'message': 'bad'}"

        async def _unexpected_run_agent_turn(*_args: Any, **_kwargs: Any):
            return (
                [
                    ModelRequest(parts=[UserPromptPart(content="hello")]),
                    ModelResponse(parts=[TextPart(content="placeholder")]),
                ],
                unexpected,
                "",
                None,
            )

        with patch("carapace.session.engine.run_agent_turn", new=_unexpected_run_agent_turn):
            await engine.submit_message(sid, "hello")
            active = engine.get_active(sid)
            assert active is not None and active.agent_task is not None
            await active.agent_task

        events = engine.session_mgr.load_events(sid)
        assert events[-1]["role"] == "assistant"
        assert events[-1]["content"] == unexpected
        assert sub.done_messages == []
        assert sub.error_events == [(unexpected, True)]

    with _patch_sentinel():
        asyncio.run(_run())


def test_evaluate_with_usage_limit_exceeded_escalates_to_user(tmp_path: Path):
    async def _run() -> None:
        session = SessionSecurity("test-session", audit_dir=tmp_path)
        sentinel = MagicMock(spec=Sentinel)
        sentinel.evaluate_tool_call = AsyncMock(
            side_effect=UsageLimitExceeded("The next request would exceed the request_limit of 5")
        )

        with pytest.raises(ApprovalRequired) as exc_info:
            await security_mod.evaluate_with(
                session,
                sentinel,
                "use_skill",
                {"skill_name": "paperless"},
            )

        metadata = exc_info.value.metadata
        assert metadata is not None
        assert metadata["tool"] == "use_skill"
        assert metadata["args"] == {"skill_name": "paperless"}
        assert metadata["risk_level"] == "high"
        assert isinstance(metadata["sentinel_verdict"], SentinelVerdict)
        assert metadata["sentinel_verdict"].decision == "escalate"
        assert "request limit" in metadata["explanation"].lower()

        entry = session.action_log[-1]
        assert isinstance(entry, ToolCallEntry)
        assert entry.decision == "escalated"
        assert entry.tool == "use_skill"
        assert entry.explanation is not None
        assert "request limit" in entry.explanation.lower()

    asyncio.run(_run())


def test_generate_title_skips_when_budget_exhausted(tmp_path: Path):
    async def _run() -> None:
        engine = _make_engine(tmp_path)
        state = engine.session_mgr.create_session(budget=SessionBudget(input_tokens=100))
        active = engine.get_or_activate(state.session_id)
        active.usage_tracker.models["test-model"] = ModelUsage(input_tokens=120)

        with patch("carapace.session.engine.generate_title", new=AsyncMock(return_value="ignored")) as mocked:
            title = await engine._generate_title(active, [{"role": "user", "content": "hello"}])

        assert title == ""
        mocked.assert_not_awaited()

    with _patch_sentinel():
        asyncio.run(_run())


def test_generate_title_persists_usage_and_broadcasts_usage(tmp_path: Path):
    async def _run() -> None:
        engine = _make_engine(tmp_path)
        state = engine.session_mgr.create_session(budget=SessionBudget(cost_usd=Decimal("5.00")))
        sid = state.session_id
        active = engine.get_or_activate(sid)
        sub = _FakeSubscriber()
        engine.subscribe(sid, sub)

        async def _fake_generate_title(*_args: Any, usage_tracker, **_kwargs: Any) -> str:
            usage_tracker.record(
                "anthropic:claude-haiku-4-5",
                "title",
                RunUsage(input_tokens=10, output_tokens=5, requests=1),
            )
            return "📌 hello"

        with patch("carapace.session.engine.generate_title", new=AsyncMock(side_effect=_fake_generate_title)):
            title = await engine._generate_title(active, [{"role": "user", "content": "hello"}])

        assert title == "📌 hello"
        stored_usage = engine.session_mgr.load_usage(sid)
        assert stored_usage.categories["title"].input_tokens == 10
        assert sub.title_updates
        assert sub.title_updates[0][0] == "📌 hello"
        assert sub.title_updates[0][1] is not None
        assert sub.title_updates[0][1].budget_gauges[0].key == "cost"

    with _patch_sentinel():
        asyncio.run(_run())


def test_generate_title_records_titler_request_log(tmp_path: Path):
    async def _run() -> None:
        engine = _make_engine(tmp_path)
        state = engine.session_mgr.create_session()
        sid = state.session_id
        active = engine.get_or_activate(sid)
        started_at = datetime.now(tz=UTC)

        async def _fake_generate_title(*_args: Any, **_kwargs: Any) -> str:
            observer = usage_mod._llm_request_sink.get()
            assert observer is not None

            request_state = LlmRequestState(
                request_id="req-title",
                source="titler",
                model_name="anthropic:claude-haiku-4-5",
                started_at=started_at,
            )
            record = LlmRequestRecord(
                ts=started_at + timedelta(seconds=1),
                request_id="req-title",
                source="titler",
                model_name="anthropic:claude-haiku-4-5",
                started_at=started_at,
                completed_at=started_at + timedelta(seconds=1),
            )

            await observer.on_request_started(request_state)
            await observer.on_request_completed(record)
            return "📌 hello"

        with patch("carapace.session.engine.generate_title", new=AsyncMock(side_effect=_fake_generate_title)):
            title = await engine._generate_title(active, [{"role": "user", "content": "hello"}])

        assert title == "📌 hello"
        assert active.llm_request_log.records[-1].request_id == "req-title"
        assert active.llm_request_log.records[-1].source == "titler"

        stored_log = engine.session_mgr.load_llm_request_log(sid)
        assert stored_log.records[-1].request_id == "req-title"
        assert stored_log.records[-1].source == "titler"

    with _patch_sentinel():
        asyncio.run(_run())


def test_handle_slash_command_inactive_session(tmp_path: Path):
    """handle_slash_command returns None for a session that isn't active."""
    engine = _make_engine(tmp_path)
    state = engine.session_mgr.create_session()

    async def _run() -> None:
        assert await engine.handle_slash_command(state.session_id, "/session") is None

    asyncio.run(_run())


def test_handle_slash_command_reload(tmp_path: Path):
    """handle_slash_command /reload calls reset_session and returns success."""
    with _patch_sentinel():
        engine = _make_engine(tmp_path)
        state = engine.session_mgr.create_session()
        sid = state.session_id
        engine.get_or_activate(sid)

        async def _run() -> None:
            result = await engine.handle_slash_command(sid, "/reload")
            assert result is not None
            assert result["command"] == "reload"
            assert "reset" in result["data"]["message"].lower() or "fresh" in result["data"]["message"].lower()
            _sandbox_reset_session_mock(engine).assert_awaited_once_with(sid)

        asyncio.run(_run())


def test_handle_slash_command_model_sets_all_three(tmp_path: Path):
    """``/model NAME`` applies the same id to agent, sentinel, and title."""
    with _patch_sentinel():
        engine = _make_engine(tmp_path)
        state = engine.session_mgr.create_session()
        sid = state.session_id
        active = engine.get_or_activate(sid)

        async def _run() -> None:
            result = await engine.handle_slash_command(sid, "/model openai:gpt-4o")
            assert result is not None
            assert result["command"] == "model"
            assert "models" in result["data"]
            for key in ("agent", "sentinel", "title"):
                assert result["data"]["models"][key]["current"] == "openai:gpt-4o"
            assert active.agent_model_name == "openai:gpt-4o"
            assert active.sentinel_model_name == "openai:gpt-4o"
            assert active.title_model_name == "openai:gpt-4o"

        asyncio.run(_run())


def test_handle_slash_command_model_agent_only(tmp_path: Path):
    """``/model-agent`` changes only the agent model."""
    with _patch_sentinel():
        engine = _make_engine(tmp_path)
        state = engine.session_mgr.create_session()
        sid = state.session_id
        active = engine.get_or_activate(sid)

        async def _run() -> None:
            result = await engine.handle_slash_command(sid, "/model-agent openai:gpt-4o")
            assert result is not None
            assert result["command"] == "model-agent"
            assert result["data"]["current"] == "openai:gpt-4o"
            assert active.agent_model_name == "openai:gpt-4o"
            assert active.sentinel_model_name is None
            assert active.title_model_name is None

        asyncio.run(_run())


def test_model_overrides_persist_across_restart(tmp_path: Path) -> None:
    with _patch_sentinel():
        engine = _make_engine(tmp_path)
        state = engine.session_mgr.create_session()
        sid = state.session_id
        engine.get_or_activate(sid)

        async def _run() -> None:
            result = await engine.handle_slash_command(sid, "/model openai:gpt-4o")
            assert result is not None
            assert result["command"] == "model"

        asyncio.run(_run())

    persisted = engine.session_mgr.load_state(sid)
    assert persisted is not None
    assert persisted.agent_model_name == "openai:gpt-4o"
    assert persisted.sentinel_model_name == "openai:gpt-4o"
    assert persisted.title_model_name == "openai:gpt-4o"

    with _patch_sentinel():
        restarted = _make_engine(tmp_path)
        active = restarted.get_or_activate(sid)
        deps = restarted._build_deps(active)

    assert active.agent_model_name == "openai:gpt-4o"
    assert active.sentinel_model_name == "openai:gpt-4o"
    assert active.title_model_name == "openai:gpt-4o"
    assert isinstance(deps.agent_model, TestModel)
    assert deps.agent_model_id == "openai:gpt-4o"
    assert active.agent_model is deps.agent_model
    _sentinel_set_model_mock(active).assert_called_once_with("openai:gpt-4o")


def test_invalid_model_overrides_fall_back_on_restart(tmp_path: Path) -> None:
    with _patch_sentinel():
        engine = _make_engine(tmp_path)
        state = engine.session_mgr.create_session()

    state.agent_model_name = "openai:missing-agent"
    state.sentinel_model_name = "openai:missing-sentinel"
    state.title_model_name = "openai:missing-title"
    engine.session_mgr.save_state(state)

    with _patch_sentinel() as sentinel_cls, patch("carapace.session.engine.logger.warning") as warning_mock:
        sentinel_instance = sentinel_cls.return_value

        def _set_model(name: str) -> None:
            if name == "openai:missing-sentinel":
                raise ValueError("missing sentinel model")

        sentinel_instance.set_model.side_effect = _set_model

        restarted = _make_engine(tmp_path)
        restarted._resolve_model = MagicMock(
            side_effect=lambda name: (
                TestModel()
                if name == restarted._config.agent.model
                else (_ for _ in ()).throw(ValueError("missing agent model"))
            )
        )

        active = restarted.get_or_activate(state.session_id)
        deps = restarted._build_deps(active)

    assert active.agent_model_name is None
    assert active.sentinel_model_name is None
    assert active.title_model_name is None
    assert isinstance(deps.agent_model, TestModel)
    assert deps.agent_model_id == restarted._config.agent.model

    persisted = restarted.session_mgr.load_state(state.session_id)
    assert persisted is not None
    assert persisted.agent_model_name is None
    assert persisted.sentinel_model_name is None
    assert persisted.title_model_name is None

    sentinel_instance.set_model.assert_any_call("openai:missing-sentinel")
    sentinel_instance.set_model.assert_any_call(restarted._config.agent.sentinel_model)
    assert warning_mock.call_count == 3


def test_non_slash_user_message_count_ignores_slash_lines() -> None:
    events: list[dict[str, Any]] = [
        {"role": "user", "content": "/model-agent openai:gpt-4o"},
        {"role": "command", "command": "model-agent", "data": {}},
        {"role": "user", "content": "hello"},
    ]
    assert _non_slash_user_message_count(events) == 1


def test_non_slash_user_message_count_plain_users() -> None:
    events: list[dict[str, Any]] = [
        {"role": "user", "content": "a"},
        {"role": "user", "content": "b"},
        {"role": "user", "content": "c"},
    ]
    assert _non_slash_user_message_count(events) == 3


def test_truncate_incomplete_model_history_drops_dangling_tool_tail(tmp_path: Path) -> None:
    with _patch_sentinel():
        engine = _make_engine(tmp_path)
        messages = [
            ModelRequest(parts=[UserPromptPart(content="hello")]),
            ModelResponse(parts=[ToolCallPart(tool_name="cmd", args={}, tool_call_id="call-1")]),
            ModelRequest(parts=[ToolReturnPart(tool_name="cmd", content="ok", tool_call_id="call-1")]),
            ModelResponse(parts=[TextPart(content="done")]),
            ModelResponse(parts=[ToolCallPart(tool_name="cmd", args={}, tool_call_id="call-2")]),
        ]

        truncated = engine._truncate_incomplete_model_history(messages)

        assert len(truncated) == 4
        assert isinstance(truncated[-1], ModelResponse)
        assert truncated[-1].parts[0].part_kind == "text"


def test_truncate_incomplete_model_history_keeps_complete_pairs(tmp_path: Path) -> None:
    with _patch_sentinel():
        engine = _make_engine(tmp_path)
        messages = [
            ModelRequest(parts=[UserPromptPart(content="hello")]),
            ModelResponse(parts=[ToolCallPart(tool_name="cmd", args={}, tool_call_id="call-1")]),
            ModelRequest(parts=[ToolReturnPart(tool_name="cmd", content="ok", tool_call_id="call-1")]),
            ModelResponse(parts=[TextPart(content="done")]),
        ]

        truncated = engine._truncate_incomplete_model_history(messages)
        assert truncated == messages


def test_truncate_incomplete_events_drops_dangling_tool_tail(tmp_path: Path) -> None:
    with _patch_sentinel():
        engine = _make_engine(tmp_path)
        events: list[dict[str, Any]] = [
            {"role": "user", "content": "hello"},
            {"role": "tool_call", "tool": "shell", "args": {"command": "echo ok"}, "detail": "run"},
            {"role": "tool_result", "tool": "shell", "result": "ok", "exit_code": 0},
            {"role": "assistant", "content": "done"},
            {"role": "tool_call", "tool": "shell", "args": {"command": "sleep 10"}, "detail": "run"},
        ]

        truncated = engine._truncate_incomplete_events(events)

        assert len(truncated) == 4
        assert truncated[-1]["role"] == "assistant"
