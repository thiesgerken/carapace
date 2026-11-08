"""Autonomy limit: streak counting, reset rules, attended pause, unattended soft and hard stop."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from pydantic_ai import ToolDenied
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, DeltaToolCalls, FunctionModel

from carapace.agent.autonomy import (
    AUTONOMY_WRAP_UP,
    AutonomyLimitReachedError,
    AutonomyStreak,
    resolve_user_approvals,
)
from carapace.models.session import SessionBudget
from carapace.security.context import ApprovalEntry, SentinelVerdict
from carapace.session import SessionEngine
from carapace.session.types import ActiveSession
from carapace.ws_models import ApprovalResponse, EscalationResponse
from tests.session_helpers import _FakeSubscriber, _make_engine, _patch_sentinel

# --- streak and reset rules ---


def test_streak_counts_attempts_and_reports_over_limit() -> None:
    streak = AutonomyStreak()

    assert [streak.count_attempt(f"c{i}", 2) for i in range(3)] == [False, False, True]
    assert streak.count == 3


def test_streak_without_limit_never_stops() -> None:
    streak = AutonomyStreak(count=500)
    streak.stop_after(frozenset({"c1"}), 2)

    assert streak.count_attempt("c2", None) is False
    assert streak.stop is None


def test_stopped_streak_lets_its_own_batch_through_and_stops_the_next_call() -> None:
    streak = AutonomyStreak(count=3)
    streak.stop_after(frozenset({"c3", "c4"}), 2)

    assert streak.count_attempt("c4", 2) is True
    with pytest.raises(AutonomyLimitReachedError, match="/budget autonomy N"):
        streak.count_attempt("c5", 2)


def test_stopped_streak_continues_after_the_limit_was_changed() -> None:
    streak = AutonomyStreak(count=3)
    streak.stop_after(frozenset({"c3"}), 2)

    assert streak.count_attempt("c4", 10) is False
    assert streak.stop is None


def test_only_a_user_message_lifts_a_stop() -> None:
    streak = AutonomyStreak(count=99)
    streak.note_user_decision()  # an escalation answered while the batch was waiting for its cards
    resolve_user_approvals(streak, {"b": ToolDenied("User denied this operation.")}, {"b"}, 100)
    streak.note_user_decision()  # another escalation answered before the next tool call

    with pytest.raises(AutonomyLimitReachedError):
        streak.count_attempt("c", 100)

    streak.start_over()
    assert streak.count_attempt("c", 100) is False


def test_user_allow_of_an_autonomy_approval_resets_the_streak() -> None:
    streak = AutonomyStreak(count=7)

    decisions = resolve_user_approvals(
        streak, {"a": True, "b": ToolDenied("User denied this operation.")}, {"a", "b"}, 5
    )

    assert streak == AutonomyStreak()
    assert decisions["a"] is True
    assert decisions["b"] == ToolDenied(f"User denied this operation. {AUTONOMY_WRAP_UP}")


def test_user_deny_of_a_sentinel_escalation_resets_the_streak() -> None:
    streak = AutonomyStreak(count=7)

    decisions = resolve_user_approvals(streak, {"a": ToolDenied("User denied this operation.")}, set(), 5)

    assert streak == AutonomyStreak()
    assert decisions == {"a": ToolDenied("User denied this operation.")}


def test_user_deny_of_every_autonomy_approval_keeps_the_streak_and_stops_after_it() -> None:
    streak = AutonomyStreak(count=7)

    resolve_user_approvals(
        streak,
        {"a": ToolDenied("User denied this operation. enough"), "b": ToolDenied("User denied this operation.")},
        {"a", "b"},
        5,
    )

    assert streak.count == 7
    with pytest.raises(AutonomyLimitReachedError):
        streak.count_attempt("c", 5)


def test_other_decisions_in_the_batch_do_not_lift_the_stop() -> None:
    streak = AutonomyStreak(count=7)

    resolve_user_approvals(
        streak,
        {"a": ToolDenied("User denied this operation."), "sentinel": True},
        {"a"},
        5,
    )

    with pytest.raises(AutonomyLimitReachedError):
        streak.count_attempt("c", 5)


def test_user_resolved_escalation_resets_the_streak(tmp_path: Path, db_factory) -> None:
    async def _run() -> None:
        with _patch_sentinel():
            engine = _make_engine(tmp_path, session_factory=db_factory)
        sid = engine.session_mgr.create_session(user="thies").session_id
        active = engine.get_or_activate(sid)
        active.autonomy.count = 7
        escalate = engine._make_escalation_cb(active)

        task = asyncio.create_task(escalate(sid, "example.com", {"kind": "domain_access", "command": "curl"}))
        await asyncio.sleep(0)
        assert active.autonomy.count == 7
        request_id = active.pending_escalations[0]["request_id"]
        await engine.submit_approval(sid, EscalationResponse(request_id=request_id, decision="deny"))
        await task

        assert active.autonomy.count == 0

    asyncio.run(_run())


# --- full turns through the engine ---


def _read_calls(*call_ids: str) -> ModelResponse:
    return ModelResponse(
        parts=[
            ToolCallPart(tool_name="read", args={"path": f"{call_id}.txt"}, tool_call_id=call_id)
            for call_id in call_ids
        ]
    )


def _tool_returns(messages: list[ModelMessage]) -> list[ToolReturnPart]:
    return [
        part
        for message in messages
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, ToolReturnPart)
    ]


def _streaming_model(respond: Callable[[list[ModelMessage], AgentInfo], ModelResponse]) -> FunctionModel:
    """The agent streams its requests, so replay each scripted response as one chunk per part."""

    async def stream(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str | DeltaToolCalls]:
        for index, part in enumerate(respond(messages, info).parts):
            if isinstance(part, TextPart):
                yield part.content
            elif isinstance(part, ToolCallPart):
                yield {
                    index: DeltaToolCall(
                        name=part.tool_name, json_args=json.dumps(part.args), tool_call_id=part.tool_call_id
                    )
                }

    return FunctionModel(stream_function=stream)


def _engine_with_model(
    tmp_path: Path,
    db_factory: Any,
    respond: Callable[[list[ModelMessage], AgentInfo], ModelResponse],
    *,
    limit: int,
    unattended: bool = False,
    yolo_mode: bool = False,
) -> tuple[SessionEngine, ActiveSession, _FakeSubscriber]:
    with _patch_sentinel():
        engine = _make_engine(tmp_path, session_factory=db_factory)
    engine._model_factory = lambda _name, *, user: _streaming_model(respond)
    engine.sandbox_mgr.file_read = AsyncMock(return_value="content")
    sid = engine.session_mgr.create_session(
        user="thies",
        unattended=unattended,
        yolo_mode=yolo_mode,
        budget=SessionBudget(autonomous_tool_calls=limit),
    ).session_id
    sub = _FakeSubscriber()
    active = engine.subscribe(sid, sub)
    return engine, active, sub


async def _wait_until(condition: Callable[[], bool]) -> None:
    async with asyncio.timeout(5):
        while not condition():
            await asyncio.sleep(0.01)


async def _finish_turn(active: ActiveSession) -> None:
    await _wait_until(lambda: active.agent_task is None)


def _sole_pending_approval(active: ActiveSession) -> dict[str, Any]:
    [request] = active.pending_approval_requests
    return request


def test_attended_allow_resets_the_streak_and_runs_the_call(tmp_path: Path, db_factory) -> None:
    def respond(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        done = len(_tool_returns(messages))
        return _read_calls(f"c{done + 1}") if done < 3 else ModelResponse(parts=[TextPart(content="done")])

    async def _run() -> None:
        engine, active, sub = _engine_with_model(tmp_path, db_factory, respond, limit=2)
        sid = active.state.session_id

        await engine.submit_message(sid, "go")
        await _wait_until(lambda: bool(active.pending_approval_requests))
        request = _sole_pending_approval(active)
        assert request["tool_call_id"] == "c3"
        assert request["explanation"] == "Autonomy limit reached (2 tool calls without you)"
        await engine.submit_approval(sid, ApprovalResponse(tool_call_id="c3", approved=True))
        await _finish_turn(active)

        assert [content for content, _usage in sub.done_messages] == ["done"]
        assert engine.sandbox_mgr.file_read.await_count == 3
        assert active.autonomy.count == 0

    asyncio.run(_run())


def test_attended_deny_wraps_up_and_the_next_tool_call_ends_the_turn(tmp_path: Path, db_factory) -> None:
    seen_returns: list[str] = []

    def respond(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        returns = _tool_returns(messages)
        seen_returns[:] = [str(part.content) for part in returns]
        return _read_calls(f"c{len(returns) + 1}")

    async def _run() -> None:
        engine, active, sub = _engine_with_model(tmp_path, db_factory, respond, limit=2)
        sid = active.state.session_id

        await engine.submit_message(sid, "go")
        await _wait_until(lambda: bool(active.pending_approval_requests))
        await engine.submit_approval(sid, ApprovalResponse(tool_call_id="c3", approved=False))
        await _finish_turn(active)

        assert seen_returns[-1] == f"User denied this operation. {AUTONOMY_WRAP_UP}"
        assert engine.sandbox_mgr.file_read.await_count == 2
        [error] = sub.errors
        assert error.startswith("Session budget reached: autonomy 3 tool calls / 2 tool calls.")
        assert "/budget autonomy N" in error
        last_event = engine.session_mgr.load_events(sid)[-1]
        assert last_event["role"] == "error"

    asyncio.run(_run())


def test_unattended_denies_the_crossing_batch_and_lets_the_agent_report(tmp_path: Path, db_factory) -> None:
    seen_returns: list[str] = []

    def respond(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        returns = _tool_returns(messages)
        seen_returns[:] = [str(part.content) for part in returns]
        if len(returns) < 2:
            return _read_calls(f"c{len(returns) + 1}")
        if len(returns) == 2:
            return _read_calls("c3", "c4")
        return ModelResponse(parts=[ToolCallPart(tool_name="task_done", args={"result": "partial report"})])

    async def _run() -> None:
        engine, active, sub = _engine_with_model(tmp_path, db_factory, respond, limit=2, unattended=True)
        sid = active.state.session_id

        await engine.submit_message(sid, "go")
        await _finish_turn(active)

        assert seen_returns[2:] == [AUTONOMY_WRAP_UP, AUTONOMY_WRAP_UP]
        assert [content for content, _usage in sub.done_messages] == ["partial report"]
        assert engine.sandbox_mgr.file_read.await_count == 2
        denied = [
            event
            for event in engine.session_mgr.load_events(sid)
            if event["role"] == "tool_call" and event.get("approval_source") == "autonomy"
        ]
        assert [event["approval_verdict"] for event in denied] == ["deny", "deny"]

    asyncio.run(_run())


def test_unattended_hard_stops_on_the_next_tool_call(tmp_path: Path, db_factory) -> None:
    def respond(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        return _read_calls(f"c{len(_tool_returns(messages)) + 1}")

    async def _run() -> None:
        engine, active, sub = _engine_with_model(tmp_path, db_factory, respond, limit=2, unattended=True)

        await engine.submit_message(active.state.session_id, "go")
        await _finish_turn(active)

        [error] = sub.errors
        assert error.startswith("Session budget reached: autonomy 3 tool calls / 2 tool calls.")

    asyncio.run(_run())


def test_sentinel_denied_attempts_count_toward_the_streak(tmp_path: Path, db_factory) -> None:
    def respond(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        call_id = f"c{len(_tool_returns(messages)) + 1}"
        return ModelResponse(
            parts=[ToolCallPart(tool_name="exec", args={"command": "rm -rf build"}, tool_call_id=call_id)]
        )

    async def _run() -> None:
        engine, active, _sub = _engine_with_model(tmp_path, db_factory, respond, limit=2)
        assert active.sentinel is not None
        active.sentinel.evaluate_tool_call = AsyncMock(
            return_value=SentinelVerdict(decision="deny", explanation="no", risk_level="high")
        )

        await engine.submit_message(active.state.session_id, "go")
        await _wait_until(lambda: bool(active.pending_approval_requests))

        assert _sole_pending_approval(active)["tool_call_id"] == "c3"
        assert active.sentinel.evaluate_tool_call.await_count == 2
        await engine.submit_cancel(active.state.session_id)

    asyncio.run(_run())


def _exec_call(call_id: str) -> ToolCallPart:
    return ToolCallPart(tool_name="exec", args={"command": "rm -rf build"}, tool_call_id=call_id)


def test_an_allowed_autonomy_approval_still_goes_through_the_security_gate(tmp_path: Path, db_factory) -> None:
    seen_returns: list[str] = []

    def respond(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        returns = _tool_returns(messages)
        seen_returns[:] = [str(part.content) for part in returns]
        if len(returns) < 3:
            return ModelResponse(parts=[_exec_call(f"c{len(returns) + 1}")])
        return ModelResponse(parts=[TextPart(content="done")])

    async def _run() -> None:
        engine, active, _sub = _engine_with_model(tmp_path, db_factory, respond, limit=2)
        sid = active.state.session_id
        assert active.sentinel is not None and active.security is not None
        active.sentinel.evaluate_tool_call = AsyncMock(
            return_value=SentinelVerdict(decision="deny", explanation="destructive", risk_level="high")
        )

        await engine.submit_message(sid, "go")
        await _wait_until(lambda: bool(active.pending_approval_requests))
        await engine.submit_approval(sid, ApprovalResponse(tool_call_id="c3", approved=True))
        await _finish_turn(active)

        assert active.sentinel.evaluate_tool_call.await_count == 3
        assert seen_returns[-1] == "Sentinel denied this operation. destructive"
        assert not any(isinstance(entry, ApprovalEntry) for entry in active.security.action_log)

    asyncio.run(_run())


def test_denying_the_autonomy_approval_stops_even_when_the_batch_had_other_decisions(
    tmp_path: Path, db_factory
) -> None:
    def respond(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        match len(_tool_returns(messages)):
            case 0:
                return _read_calls("c1")
            case 1:
                return ModelResponse(parts=[_exec_call("c2"), _exec_call("c3")])
            case _:
                return _read_calls("c4")

    async def _run() -> None:
        engine, active, sub = _engine_with_model(tmp_path, db_factory, respond, limit=2)
        sid = active.state.session_id
        assert active.sentinel is not None
        active.sentinel.evaluate_tool_call = AsyncMock(
            return_value=SentinelVerdict(decision="escalate", explanation="check", risk_level="medium")
        )

        await engine.submit_message(sid, "go")
        await _wait_until(lambda: len(active.pending_approval_requests) == 2)
        explanations = {request["explanation"] for request in active.pending_approval_requests}
        assert explanations == {"check", "Autonomy limit reached (2 tool calls without you)"}
        for request in list(active.pending_approval_requests):
            await engine.submit_approval(sid, ApprovalResponse(tool_call_id=request["tool_call_id"], approved=False))
        await _finish_turn(active)

        [error] = sub.errors
        assert error.startswith("Session budget reached: autonomy")

    asyncio.run(_run())


def test_yolo_sessions_are_limited_too(tmp_path: Path, db_factory) -> None:
    def respond(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        return _read_calls(f"c{len(_tool_returns(messages)) + 1}")

    async def _run() -> None:
        engine, active, _sub = _engine_with_model(tmp_path, db_factory, respond, limit=1, yolo_mode=True)

        await engine.submit_message(active.state.session_id, "go")
        await _wait_until(lambda: bool(active.pending_approval_requests))

        assert _sole_pending_approval(active)["tool_call_id"] == "c2"
        await engine.submit_cancel(active.state.session_id)

    asyncio.run(_run())


def test_a_user_message_resets_the_streak(tmp_path: Path, db_factory) -> None:
    def respond(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart(content="hi")])

    async def _run() -> None:
        engine, active, _sub = _engine_with_model(tmp_path, db_factory, respond, limit=2)
        active.autonomy.count = 9
        active.autonomy.stop_after(frozenset({"old"}), 2)

        await engine.submit_message(active.state.session_id, "hello")
        await _finish_turn(active)

        assert active.autonomy == AutonomyStreak()

    asyncio.run(_run())


def test_a_total_budget_stop_does_not_mention_the_autonomy_limit(tmp_path: Path, db_factory) -> None:
    async def _two_tool_calls(_user_input: str, deps: Any, *_args: Any, **_kwargs: Any) -> Any:
        deps.autonomy.count = 5
        callback = deps.tool_call_callback
        callback("read", {"path": "a"}, "[safe-list] auto-allowed", "safe-list", "allow", "ok")
        callback("read", {"path": "b"}, "[safe-list] auto-allowed", "safe-list", "allow", "ok")
        return [], "done", "", None

    async def _run() -> None:
        with _patch_sentinel():
            engine = _make_engine(tmp_path, session_factory=db_factory)
        sid = engine.session_mgr.create_session(
            user="thies", budget=SessionBudget(tool_calls=1, autonomous_tool_calls=5)
        ).session_id
        sub = _FakeSubscriber()
        active = engine.subscribe(sid, sub)

        with patch("carapace.session.engine.run_agent_turn", new=_two_tool_calls):
            await engine.submit_message(sid, "go")
            await _finish_turn(active)

        [error] = sub.errors
        assert error == (
            "Session budget reached: tool calls 1 tool call / 1 tool call. "
            "Raise the limit to continue: /budget tool_calls N"
        )

    asyncio.run(_run())
