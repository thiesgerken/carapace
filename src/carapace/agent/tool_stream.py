"""Shows the agent's tool calls to clients while the model is still writing them.

A long call (an exec with a big heredoc) can take the model a minute to write; without this the
chat shows nothing until the call is complete and gated.
"""

from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from pydantic_ai.messages import (
    AgentStreamEvent,
    PartDeltaEvent,
    PartEndEvent,
    PartStartEvent,
    ToolCallPart,
    ToolCallPartDelta,
)

from ..ws_models import ToolCallDelta, ToolCallEnd, ToolCallStart, ToolCallStream

# At most ~10 delta messages per second and call: a fast model writes hundreds of tiny chunks.
DELTA_INTERVAL_S = 0.1


@dataclass
class _OpenCall:
    tool_call_id: str
    pending: str = ""
    last_sent: float = float("-inf")


class ToolCallStreamer:
    """Turns one model response's stream events into tool call start/delta/end messages.

    One instance per response: the part indices it keys calls by restart at 0 for every response.
    """

    def __init__(
        self,
        send: Callable[[ToolCallStream], Awaitable[None]],
        *,
        skip_tools: frozenset[str],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._send = send
        self._skip_tools = skip_tools
        self._clock = clock
        self._open: dict[int, _OpenCall] = {}

    async def handle(self, event: AgentStreamEvent) -> None:
        match event:
            case PartStartEvent(index=index, part=ToolCallPart() as part) if part.tool_name not in self._skip_tools:
                call = self._open[index] = _OpenCall(part.tool_call_id)
                await self._send(ToolCallStart(tool_call_id=call.tool_call_id, tool=part.tool_name))
                if isinstance(part.args, str):
                    await self._append(call, part.args)
            case PartDeltaEvent(index=index, delta=ToolCallPartDelta(args_delta=str() as text)) if (
                call := self._open.get(index)
            ):
                await self._append(call, text)
            case PartEndEvent(index=index, part=ToolCallPart() as part) if call := self._open.pop(index, None):
                # Providers that hand over args as a dict never stream text; their args go out whole.
                if isinstance(part.args, dict):
                    call.pending = json.dumps(part.args)
                await self._flush(call)
                await self._send(ToolCallEnd(tool_call_id=call.tool_call_id, aborted=False))

    async def abort_open_calls(self) -> None:
        """End every call the model did not finish writing (the request was cancelled or failed)."""
        calls, self._open = list(self._open.values()), {}
        for call in calls:
            await self._send(ToolCallEnd(tool_call_id=call.tool_call_id, aborted=True))

    async def _append(self, call: _OpenCall, text: str) -> None:
        call.pending += text
        # ponytail: no timer, so text that arrives within the interval waits for the next chunk or
        # the part's end. Fine while the model is still streaming; add a timer if stalls show up.
        if self._clock() - call.last_sent >= DELTA_INTERVAL_S:
            await self._flush(call)

    async def _flush(self, call: _OpenCall) -> None:
        if not call.pending:
            return
        text, call.pending = call.pending, ""
        call.last_sent = self._clock()
        await self._send(ToolCallDelta(tool_call_id=call.tool_call_id, args_delta=text))
