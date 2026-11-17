"""The agent's tool calls reach clients while the model is still writing them."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from pydantic_ai.messages import (
    ModelMessage,
    PartDeltaEvent,
    PartEndEvent,
    PartStartEvent,
    ToolCallPart,
    ToolCallPartDelta,
    ToolReturnPart,
)
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, DeltaToolCalls, FunctionModel

from carapace.agent.tool_stream import DELTA_INTERVAL_S, ToolCallStreamer
from carapace.ws_models import ToolCallDelta, ToolCallEnd, ToolCallStart, ToolCallStream
from tests.session_helpers import _FakeSubscriber, _make_engine, _patch_sentinel


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _streamer(clock: _Clock | None = None) -> tuple[ToolCallStreamer, list[ToolCallStream]]:
    sent: list[ToolCallStream] = []

    async def _send(msg: ToolCallStream) -> None:
        sent.append(msg)

    return ToolCallStreamer(_send, skip_tools=frozenset({"task_done"}), clock=clock or _Clock()), sent


def _delta(index: int, text: str | dict[str, object]) -> PartDeltaEvent:
    return PartDeltaEvent(index=index, delta=ToolCallPartDelta(args_delta=text))


@pytest.mark.asyncio
async def test_args_deltas_are_coalesced_per_interval_and_flushed_at_the_end() -> None:
    clock = _Clock()
    streamer, sent = _streamer(clock)
    part = ToolCallPart("exec", '{"comm', tool_call_id="a")
    # Three chunks stay inside one interval, the fourth crosses it.
    step = DELTA_INTERVAL_S * 0.3

    await streamer.handle(PartStartEvent(index=0, part=part))
    for text in ('and": "', "ec", "ho"):
        clock.now += step
        await streamer.handle(_delta(0, text))
    clock.now += step
    await streamer.handle(_delta(0, ' hi"}'))
    await streamer.handle(PartEndEvent(index=0, part=part))

    assert sent == [
        ToolCallStart(tool_call_id="a", tool="exec"),
        ToolCallDelta(tool_call_id="a", args_delta='{"comm'),
        ToolCallDelta(tool_call_id="a", args_delta='and": "echo hi"}'),
        ToolCallEnd(tool_call_id="a", aborted=False),
    ]


@pytest.mark.asyncio
async def test_parallel_calls_stream_under_their_own_ids_and_open_ones_end_aborted() -> None:
    streamer, sent = _streamer()
    first, second = ToolCallPart("read", "", tool_call_id="a"), ToolCallPart("exec", "", tool_call_id="b")

    await streamer.handle(PartStartEvent(index=1, part=first))
    await streamer.handle(PartStartEvent(index=2, part=second))
    await streamer.handle(_delta(2, "{}"))
    await streamer.handle(_delta(1, "{}"))
    await streamer.handle(PartEndEvent(index=1, part=first))
    await streamer.abort_open_calls()

    assert sent == [
        ToolCallStart(tool_call_id="a", tool="read"),
        ToolCallStart(tool_call_id="b", tool="exec"),
        ToolCallDelta(tool_call_id="b", args_delta="{}"),
        ToolCallDelta(tool_call_id="a", args_delta="{}"),
        ToolCallEnd(tool_call_id="a", aborted=False),
        ToolCallEnd(tool_call_id="b", aborted=True),
    ]


@pytest.mark.asyncio
async def test_dict_args_go_out_whole_when_the_call_ends() -> None:
    streamer, sent = _streamer()
    part = ToolCallPart("exec", {"command": "ls"}, tool_call_id="a")

    await streamer.handle(PartStartEvent(index=0, part=part))
    await streamer.handle(_delta(0, {"timeout": 5}))
    await streamer.handle(PartEndEvent(index=0, part=ToolCallPart("exec", {"command": "ls", "timeout": 5}, "a")))

    assert sent == [
        ToolCallStart(tool_call_id="a", tool="exec"),
        ToolCallDelta(tool_call_id="a", args_delta='{"command": "ls", "timeout": 5}'),
        ToolCallEnd(tool_call_id="a", aborted=False),
    ]


@pytest.mark.asyncio
async def test_output_tools_are_not_streamed() -> None:
    streamer, sent = _streamer()
    part = ToolCallPart("task_done", '{"result": "ok"}', tool_call_id="a")

    await streamer.handle(PartStartEvent(index=0, part=part))
    await streamer.handle(_delta(0, "x"))
    await streamer.handle(PartEndEvent(index=0, part=part))
    await streamer.abort_open_calls()

    assert sent == []


async def _write_then_answer(messages: list[ModelMessage], _info: AgentInfo) -> AsyncIterator[DeltaToolCalls | str]:
    if any(isinstance(part, ToolReturnPart) for message in messages for part in message.parts):
        yield "done"
        return
    yield {0: DeltaToolCall(name="write", json_args='{"path": "a",', tool_call_id="call_a")}
    yield {0: DeltaToolCall(json_args=' "content": "b"}')}


async def _fail_mid_call(_messages: list[ModelMessage], _info: AgentInfo) -> AsyncIterator[DeltaToolCalls]:
    yield {0: DeltaToolCall(name="exec", json_args='{"command": "ec', tool_call_id="call_a")}
    raise RuntimeError("overloaded")


def _engine_with(tmp_path: Path, db_factory, model: FunctionModel) -> tuple[object, str, _FakeSubscriber]:
    engine = _make_engine(tmp_path, session_factory=db_factory)
    engine._model_factory = lambda _name, *, user: model
    sid = engine.session_mgr.create_session(user="thies").session_id
    sub = _FakeSubscriber()
    engine.subscribe(sid, sub)
    return engine, sid, sub


def test_a_streamed_call_carries_its_id_into_the_executed_call(tmp_path: Path, db_factory) -> None:
    async def _run() -> _FakeSubscriber:
        engine, sid, sub = _engine_with(tmp_path, db_factory, FunctionModel(stream_function=_write_then_answer))
        await engine.submit_message(sid, "write a")
        await engine.get_active(sid).agent_task
        await asyncio.sleep(0)
        return sub

    with _patch_sentinel():
        sub = asyncio.run(_run())

    assert sub.tool_call_stream == [
        ToolCallStart(tool_call_id="call_a", tool="write"),
        ToolCallDelta(tool_call_id="call_a", args_delta='{"path": "a",'),
        ToolCallDelta(tool_call_id="call_a", args_delta=' "content": "b"}'),
        ToolCallEnd(tool_call_id="call_a", aborted=False),
    ]
    assert sub.tool_calls == [("write", "call_a")]


def test_a_request_failing_mid_call_ends_the_call_aborted(tmp_path: Path, db_factory) -> None:
    async def _run() -> _FakeSubscriber:
        engine, sid, sub = _engine_with(tmp_path, db_factory, FunctionModel(stream_function=_fail_mid_call))
        await engine.submit_message(sid, "echo")
        await engine.get_active(sid).agent_task
        return sub

    with _patch_sentinel():
        sub = asyncio.run(_run())

    assert sub.tool_call_stream == [
        ToolCallStart(tool_call_id="call_a", tool="exec"),
        ToolCallDelta(tool_call_id="call_a", args_delta='{"command": "ec'),
        ToolCallEnd(tool_call_id="call_a", aborted=True),
    ]
    assert sub.tool_calls == []
    assert sub.errors
