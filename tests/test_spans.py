"""Turn timing spans: the span helper, the flush at turn end, and the timeline read model and API."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.usage import RequestUsage

from carapace.session.engine import SessionEngine
from carapace.session.timeline import session_turns, turn_timeline
from carapace.spans import Span, TurnTrace, attach, current_span_ref, span
from carapace.usage import LlmRequestLogCapability, LlmRequestState
from tests.session_helpers import _FakeSubscriber, _make_engine, _patch_sentinel


def _trace() -> tuple[TurnTrace, Span, list[tuple[str, str]]]:
    changes: list[tuple[str, str]] = []
    trace = TurnTrace("t1", on_change=lambda s: changes.append((s.name, s.status)))
    root = trace.start("turn", "turn", parent_id=None, attrs={})
    return trace, root, changes


def test_span_outside_a_turn_is_recorded_nowhere() -> None:
    with span("exec", "ls") as detached:
        detached.attrs["exit_code"] = 0
    assert detached.parent_id is None
    assert current_span_ref() is None


def test_spans_nest_and_end_with_how_their_block_exits() -> None:
    trace, root, changes = _trace()
    with attach(trace, root.span_id):
        with span("tool", "exec", command="ls") as tool:
            assert current_span_ref() == ("t1", tool.span_id)
            with pytest.raises(RuntimeError), span("sandbox", "ensure"):
                raise RuntimeError("boom")
        assert current_span_ref() == ("t1", root.span_id)

    by_name = {s.name: s for s in trace.spans.values()}
    assert by_name["exec"].parent_id == root.span_id
    assert by_name["exec"].attrs == {"command": "ls"}
    assert by_name["ensure"].parent_id == tool.span_id
    assert (by_name["exec"].status, by_name["ensure"].status) == ("ok", "error")
    assert by_name["ensure"].ended_at is not None
    assert changes[1:] == [("exec", "running"), ("ensure", "running"), ("ensure", "error"), ("exec", "ok")]


@pytest.mark.asyncio
async def test_cancelled_span_is_interrupted() -> None:
    trace, root, _ = _trace()

    async def _work() -> None:
        with span("exec", "sleep"):
            await asyncio.sleep(10)

    with attach(trace, root.span_id):
        task = asyncio.create_task(_work())
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert [s.status for s in trace.spans.values() if s.name == "sleep"] == ["interrupted"]


def test_close_interrupts_open_spans_and_later_ends_keep_that() -> None:
    trace, root, _ = _trace()
    with attach(trace, root.span_id), span("exec", "late") as late:
        trace.end(root, "ok")
        flushed = trace.close()
        # A span started after the flush would be lost, so it is not recorded.
        with span("exec", "after") as after:
            assert current_span_ref() is None
    assert {s.name: s.status for s in flushed} == {"turn": "ok", "late": "interrupted"}
    assert late.status == "interrupted"
    assert after.span_id not in trace.spans
    with pytest.raises(RuntimeError):
        trace.start("exec", "x", parent_id=None, attrs={})


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _reply(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
    return ModelResponse(parts=[TextPart("pong")], usage=RequestUsage(input_tokens=100, output_tokens=5))


def _engine(tmp_path: Path, db_factory) -> tuple[SessionEngine, str, _FakeSubscriber]:
    engine = _make_engine(tmp_path, session_factory=db_factory)
    sid = engine.session_mgr.create_session(user="thies").session_id
    sub = _FakeSubscriber()
    engine.subscribe(sid, sub)
    return engine, sid, sub


def test_turn_flushes_its_spans_and_joins_its_llm_requests(tmp_path: Path, db_factory) -> None:
    async def _run() -> None:
        engine, sid, sub = _engine(tmp_path, db_factory)
        model = Agent(FunctionModel(_reply), capabilities=[LlmRequestLogCapability(source="agent", model_id="test:m")])

        async def _fake_turn(user_input: str, _deps: Any, history: list[Any], **_kwargs: Any) -> Any:
            with span("tool", "exec", command="ls"):
                result = await model.run(user_input)
            return [*history, *result.new_messages()], result.output, "", None

        with patch("carapace.session.engine.run_agent_turn", new=_fake_turn):
            await engine.submit_message(sid, "  hello\n  world  ")
            active = engine.get_active(sid)
            assert active is not None and active.agent_task is not None
            await active.agent_task
        await asyncio.sleep(0)

        assert active.turn_trace is None
        (turn,) = session_turns(engine.session_mgr, sid, active)
        assert (turn.prompt_preview, turn.status) == ("hello world", "ok")
        assert turn.ended_at is not None
        user_event = next(e for e in engine.session_mgr.load_events(sid) if e["role"] == "user")
        assert user_event["turn_id"] == turn.turn_id

        timeline = turn_timeline(engine.session_mgr, sid, turn.turn_id, active)
        assert timeline is not None
        root, tool, llm = timeline.spans
        assert (root.kind, root.parent_id) == ("turn", None)
        assert (tool.kind, tool.parent_id, tool.status) == ("tool", root.span_id, "ok")
        assert (llm.kind, llm.parent_id, llm.status) == ("llm", tool.span_id, "ok")
        assert llm.llm is not None and (llm.llm.role, llm.llm.input_tokens) == ("agent", 100)
        assert {(span_id, status) for _, span_id, status in sub.span_updates} == {
            (s.span_id, status) for s in (root, tool) for status in ("running", "ok")
        }
        assert turn_timeline(engine.session_mgr, sid, "nope", active) is None

    with _patch_sentinel():
        asyncio.run(_run())


def test_running_turn_is_read_live_and_a_stop_interrupts_it(tmp_path: Path, db_factory) -> None:
    async def _run() -> None:
        engine, sid, _ = _engine(tmp_path, db_factory)
        started = asyncio.Event()

        async def _hanging_turn(*_args: Any, **_kwargs: Any) -> Any:
            with span("exec", "sleep"):
                started.set()
                await asyncio.sleep(999)

        with patch("carapace.session.engine.run_agent_turn", new=_hanging_turn):
            await engine.submit_message(sid, "wait")
            await started.wait()
            active = engine.get_active(sid)
            assert active is not None and active.turn_trace is not None
            (turn,) = session_turns(engine.session_mgr, sid, active)
            assert turn.status == "running" and turn.ended_at is None
            exec_span = next(s for s in active.turn_trace.spans.values() if s.kind == "exec")
            active.llm_request_state = LlmRequestState(
                request_id="r1", source="sentinel", turn_id=turn.turn_id, span_id=exec_span.span_id, started_at=_now()
            )
            live = turn_timeline(engine.session_mgr, sid, turn.turn_id, active)
            assert live is not None
            assert [s.kind for s in live.spans] == ["turn", "exec", "llm"]
            assert {s.status for s in live.spans} == {"running"}
            assert live.spans[2].parent_id == exec_span.span_id
            active.llm_request_state = None
            await engine.submit_cancel(sid)

        flushed = turn_timeline(engine.session_mgr, sid, turn.turn_id, active)
        assert flushed is not None and [s.status for s in flushed.spans] == ["interrupted", "interrupted"]

    with _patch_sentinel():
        asyncio.run(_run())
