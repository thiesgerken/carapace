"""Turn timing spans: the span helper, the flush at turn end, and the timeline read model and API."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from pydantic_ai import Agent, ApprovalRequired, DeferredToolRequests
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.usage import RequestUsage

from carapace.credentials.registry import SessionCredentialRegistry
from carapace.security.context import SENTINEL_VERDICT_TOOL, SessionSecurity
from carapace.security.sentinel import Sentinel
from carapace.session.engine import SessionEngine
from carapace.session.timeline import session_turns, turn_timeline
from carapace.spans import Span, ToolSpanCapability, TurnTrace, attach, current_span_ref, span
from carapace.usage import LlmRequestLogCapability, LlmRequestState
from carapace.ws_models import ApprovalResponse
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
        root, prepare, tool, llm = timeline.spans
        assert (root.kind, root.parent_id) == ("turn", None)
        assert (prepare.kind, prepare.parent_id, prepare.status) == ("turn.prepare", root.span_id, "ok")
        assert (tool.kind, tool.parent_id, tool.status) == ("tool", root.span_id, "ok")
        assert (llm.kind, llm.parent_id, llm.status) == ("llm", tool.span_id, "ok")
        assert llm.llm is not None and (llm.llm.role, llm.llm.input_tokens) == ("agent", 100)
        assert {(span_id, status) for _, span_id, status in sub.span_updates} == {
            (s.span_id, status) for s in (root, prepare, tool, llm) for status in ("running", "ok")
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
            # Two parallel sentinel requests; the tracked copy of the first carries its live phases.
            parallel = [
                LlmRequestState(
                    request_id=request_id,
                    source="sentinel",
                    turn_id=turn.turn_id,
                    span_id=exec_span.span_id,
                    started_at=_now(),
                )
                for request_id in ("r1", "r2")
            ]
            active.llm_requests_in_flight = {state.request_id: state for state in parallel}
            active.llm_request_state = parallel[0].model_copy(update={"first_thinking_at": _now()})
            live = turn_timeline(engine.session_mgr, sid, turn.turn_id, active)
            assert live is not None
            assert [(s.kind, s.status) for s in live.spans] == [
                ("turn", "running"),
                ("turn.prepare", "ok"),
                ("exec", "running"),
                ("llm", "running"),
                ("llm", "running"),
            ]
            bars = {s.span_id: s for s in live.spans if s.kind == "llm"}
            assert {s.parent_id for s in bars.values()} == {exec_span.span_id}
            assert bars["r1"].llm is not None and bars["r1"].llm.first_thinking_at is not None
            active.llm_requests_in_flight.clear()
            active.llm_request_state = None
            await engine.submit_cancel(sid)

        flushed = turn_timeline(engine.session_mgr, sid, turn.turn_id, active)
        assert flushed is not None and [s.status for s in flushed.spans] == ["interrupted", "ok", "interrupted"]

    with _patch_sentinel():
        asyncio.run(_run())


@pytest.mark.asyncio
async def test_tool_calls_get_tool_spans_and_a_deferred_call_ends_ok() -> None:
    trace, root, _ = _trace()

    def _call_tools(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        if len(messages) == 1:
            return ModelResponse(parts=[ToolCallPart("lookup", {}), ToolCallPart("guarded", {})])
        return ModelResponse(parts=[TextPart("done")])

    agent = Agent(
        FunctionModel(_call_tools), output_type=[str, DeferredToolRequests], capabilities=[ToolSpanCapability()]
    )

    @agent.tool_plain
    def lookup() -> str:
        return "found"

    @agent.tool_plain
    def guarded() -> str:
        raise ApprovalRequired

    with attach(trace, root.span_id):
        await agent.run("go")

    tools = {s.name: s for s in trace.spans.values() if s.kind == "tool"}
    assert {name: (s.parent_id, s.status) for name, s in tools.items()} == {
        "lookup": (root.span_id, "ok"),
        "guarded": (root.span_id, "ok"),
    }
    assert tools["guarded"].attrs == {"deferred": True}
    assert tools["lookup"].attrs == {}


@pytest.mark.asyncio
async def test_sentinel_evaluation_parents_its_requests_and_skill_file_reads(tmp_path: Path, db_factory) -> None:
    engine = _make_engine(tmp_path, session_factory=db_factory)
    sid = engine.session_mgr.create_session(user="thies").session_id
    with _patch_sentinel():
        active = engine.get_or_activate(sid)
    (tmp_path / "skills" / "demo").mkdir(parents=True)
    (tmp_path / "skills" / "demo" / "SKILL.md").write_text("demo")

    def _judge(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        if len(messages) == 1:
            return ModelResponse(parts=[ToolCallPart("read_skill_file", {"skill_name": "demo", "path": "SKILL.md"})])
        return ModelResponse(parts=[ToolCallPart(SENTINEL_VERDICT_TOOL, {"decision": "allow", "explanation": "fine"})])

    sentinel = Sentinel(
        model="test:model",
        user="thies",
        knowledge_dir=tmp_path,
        skills_dir=tmp_path / "skills",
        llm_slots=None,
        timeout=timedelta(seconds=5),
        model_factory=lambda _name, *, user: FunctionModel(_judge),
    )
    trace, root, _ = _trace()
    with engine.llm_request_recording(active), attach(trace, root.span_id):
        await sentinel.evaluate_tool_call(SessionSecurity(sid), "exec", {"command": "echo hi"})

    (evaluation,) = [s for s in trace.spans.values() if s.kind == "sentinel"]
    assert (evaluation.name, evaluation.parent_id, evaluation.status) == ("tool_call", root.span_id, "ok")
    assert evaluation.attrs == {"subject": "exec(\"command='echo hi'\")", "verdict": "allow"}
    (read,) = [s for s in trace.spans.values() if s.kind == "tool"]
    assert (read.name, read.parent_id) == ("read_skill_file", evaluation.span_id)
    requests = [r for r in active.llm_request_log.records if r.source == "sentinel"]
    assert [r.span_id for r in requests] == [evaluation.span_id, evaluation.span_id]


def test_approval_wait_is_a_wait_span(tmp_path: Path, db_factory) -> None:
    async def _run() -> None:
        engine, sid, _ = _engine(tmp_path, db_factory)

        async def _asking_turn(_input: str, _deps: Any, history: list[Any], **kwargs: Any) -> Any:
            await kwargs["collect_approvals"]({"call-1"})
            return history, "ok", "", None

        with patch("carapace.session.engine.run_agent_turn", new=_asking_turn):
            await engine.submit_message(sid, "go")
            active = engine.get_active(sid)
            assert active is not None and active.agent_task is not None
            await active.tool_approval_queue.put(ApprovalResponse(tool_call_id="call-1", approved=True))
            await active.agent_task

        (turn,) = session_turns(engine.session_mgr, sid, active)
        timeline = turn_timeline(engine.session_mgr, sid, turn.turn_id, active)
        assert timeline is not None
        (wait,) = [s for s in timeline.spans if s.kind == "wait"]
        assert (wait.name, wait.status, wait.attrs) == ("approval", "ok", {"reason": "approval", "calls": 1})

    with _patch_sentinel():
        asyncio.run(_run())


@pytest.mark.asyncio
async def test_credential_fetches_are_credential_spans() -> None:
    vault = AsyncMock()
    vault.fetch.return_value = "secret"
    registry = SessionCredentialRegistry(session_id="s", resolve_registry=AsyncMock(return_value=vault))
    trace, root, _ = _trace()
    with attach(trace, root.span_id):
        assert await registry.fetch("file/api-key") == "secret"
        with pytest.raises(KeyError):
            vault.fetch_metadata.side_effect = KeyError("file/missing")
            await registry.fetch_metadata("file/missing")

    fetched = [(s.name, s.status, s.attrs) for s in trace.spans.values() if s.kind == "credential"]
    assert fetched == [("file/api-key", "ok", {"fetch": "password"}), ("file/missing", "error", {"fetch": "metadata"})]


@pytest.mark.asyncio
async def test_requests_leave_the_in_flight_set_however_they_end(tmp_path: Path, db_factory) -> None:
    engine, sid, _ = _engine(tmp_path, db_factory)
    with _patch_sentinel():
        active = engine.get_or_activate(sid)

    def _fail(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        raise RuntimeError("boom")

    capabilities = [LlmRequestLogCapability(source="agent", model_id="test:m")]
    with engine.llm_request_recording(active):
        await Agent(FunctionModel(_reply), capabilities=capabilities).run("ok")
        with pytest.raises(RuntimeError):
            await Agent(FunctionModel(_fail), capabilities=capabilities).run("fail")
    assert active.llm_requests_in_flight == {}
