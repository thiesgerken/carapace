"""Timing spans of one agent turn (see docs/debug-view.md, "Timeline").

A turn's spans live in memory on a ``TurnTrace`` while the turn runs and are flushed to the
database in one batch when it ends, so measuring adds no I/O to the measured path. The span a
new span nests under travels in a contextvar, like OpenTelemetry's current span.
"""

from __future__ import annotations

import asyncio
import secrets
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field
from pydantic_ai import ApprovalRequired, CallDeferred
from pydantic_ai.capabilities.abstract import AbstractCapability, ValidatedToolArgs, WrapToolExecuteHandler
from pydantic_ai.messages import ToolCallPart
from pydantic_ai.tools import AgentDepsT, RunContext, ToolDefinition

SpanStatus = Literal["running", "ok", "error", "interrupted"]
SpanAttr = str | int | float | bool


class Span(BaseModel):
    span_id: str
    parent_id: str | None
    kind: str
    name: str
    started_at: datetime
    ended_at: datetime | None = None
    status: SpanStatus = "running"
    attrs: dict[str, SpanAttr] = Field(default_factory=dict)


class SpanNotice(BaseModel):
    """A span of the running turn started or ended, as the session's subscribers hear it."""

    turn_id: str
    span_id: str
    kind: str
    name: str
    status: SpanStatus
    # Server clock: a client that joins mid-span counts its duration from here, not from when it heard of it.
    started_at: datetime
    # The call whose tool span this span is or nests under: the chat shows it on that call's card.
    tool_call_id: str | None = None


# Spans keep small attrs only (full arguments and outputs stay in the history), and some come
# straight from the sandbox, like the proxy's domains.
SPAN_TEXT_MAX = 200


def _new_span(kind: str, name: str, parent_id: str | None, attrs: dict[str, SpanAttr]) -> Span:
    return Span(
        span_id=secrets.token_hex(8),
        parent_id=parent_id,
        kind=kind,
        name=name[:SPAN_TEXT_MAX],
        started_at=datetime.now(tz=UTC),
        attrs={key: value[:SPAN_TEXT_MAX] if isinstance(value, str) else value for key, value in attrs.items()},
    )


class TurnTrace:
    """The spans of one running turn; *on_change* hears every span start and end."""

    def __init__(self, turn_id: str, on_change: Callable[[SpanNotice], None]) -> None:
        self.turn_id = turn_id
        self.spans: dict[str, Span] = {}
        self.closed = False
        self._on_change = on_change

    def start(self, kind: str, name: str, *, parent_id: str | None, attrs: dict[str, SpanAttr]) -> Span:
        if self.closed:
            raise RuntimeError(f"turn {self.turn_id} is closed, no span can start in it")
        span = _new_span(kind, name, parent_id, attrs)
        self.spans[span.span_id] = span
        self._on_change(self._notice(span))
        return span

    def end(self, span: Span, status: SpanStatus) -> None:
        # A span the turn's close already interrupted keeps that status.
        if span.status != "running":
            return
        span.status = status
        span.ended_at = datetime.now(tz=UTC)
        self._on_change(self._notice(span))

    def _notice(self, span: Span) -> SpanNotice:
        return SpanNotice(
            turn_id=self.turn_id,
            span_id=span.span_id,
            kind=span.kind,
            name=span.name,
            status=span.status,
            started_at=span.started_at,
            tool_call_id=self.tool_call_id(span.span_id),
        )

    def running_notices(self) -> Iterator[SpanNotice]:
        """Start notices of the spans still open, oldest first, for a subscriber that joins mid-turn.

        Lazy, so a span that ends while the caller sends the earlier notices is skipped instead of being
        announced as running after its end notice went out.
        """
        for span in list(self.spans.values()):
            if span.status == "running":
                yield self._notice(span)

    def tool_call_id(self, span_id: str | None) -> str | None:
        """The id of the outermost tool call *span_id* is or nests under; ``None`` outside a tool call.

        Outermost: the sentinel's own tool calls (reading skill files) run inside the agent call they
        review, which is the call the user sees.
        """
        found = None
        while span_id is not None:
            span = self.spans[span_id]
            if span.kind == "tool":
                found = str(span.attrs["tool_call_id"])
            span_id = span.parent_id
        return found

    def sandbox_call_parent(self) -> str:
        """The span a call from inside the sandbox nests under: the newest running exec or file span, else the root."""
        spans = list(self.spans.values())
        # ponytail: a call can't tell which of several parallel exec/file spans made it; the newest wins.
        running = (s for s in reversed(spans) if s.status == "running" and s.kind in ("exec", "file"))
        return next(running, next(s for s in spans if s.parent_id is None)).span_id

    def close(self) -> list[Span]:
        """End the spans still open as interrupted and return all spans for the flush."""
        for span in self.spans.values():
            self.end(span, "interrupted")
        self.closed = True
        return list(self.spans.values())


_current: ContextVar[tuple[TurnTrace, str] | None] = ContextVar("current_span", default=None)


@contextmanager
def attach(trace: TurnTrace, parent_id: str) -> Iterator[None]:
    """Make *parent_id* in *trace* the parent of spans started in this block.

    For code that runs in another task than the turn (the proxy) and so does not inherit the turn's context.
    """
    token = _current.set((trace, parent_id))
    try:
        yield
    finally:
        _current.reset(token)


@contextmanager
def attach_sandbox_call(trace: TurnTrace | None) -> Iterator[None]:
    """Nest the spans of a call from inside the sandbox (proxy, sandbox API) in its session's running turn.

    *trace* is the session's running turn, ``None`` outside one: then the block records no spans.
    """
    if trace is None or trace.closed:
        yield
        return
    with attach(trace, trace.sandbox_call_parent()):
        yield


@contextmanager
def span(kind: str, name: str, /, **attrs: SpanAttr) -> Iterator[Span]:
    """Time the block as a span under the current one; its status follows how the block exits.

    A deferred tool call (approval required) is control flow, not a failure: it ends ``ok`` with
    ``deferred: true``.

    Outside a running turn the yielded span is recorded nowhere, so callers never need to check.
    Event-loop thread only: ``asyncio.to_thread`` copies the contextvar into its worker, where a span
    would mutate the trace off the loop and fail to broadcast. Wrap the ``await asyncio.to_thread(...)``,
    never the function running inside it.
    """
    current = _current.get()
    if current is None or current[0].closed:
        yield _new_span(kind, name, None, attrs)
        return
    trace, parent_id = current
    started = trace.start(kind, name, parent_id=parent_id, attrs=attrs)
    token = _current.set((trace, started.span_id))
    try:
        yield started
    except asyncio.CancelledError:
        trace.end(started, "interrupted")
        raise
    except (ApprovalRequired, CallDeferred):
        started.attrs["deferred"] = True
        trace.end(started, "ok")
        raise
    except BaseException as exc:
        started.attrs["error"] = type(exc).__name__
        trace.end(started, "error")
        raise
    else:
        trace.end(started, "ok")
    finally:
        _current.reset(token)


def current_span_ref() -> tuple[str, str] | None:
    """``(turn_id, span_id)`` of the current span, or ``None`` outside a running turn."""
    current = _current.get()
    if current is None or current[0].closed:
        return None
    return current[0].turn_id, current[1]


@dataclass
class ToolSpanCapability(AbstractCapability[AgentDepsT]):
    """A ``tool`` span around every function tool call of an agent; output tools are the answer, not a step."""

    async def wrap_tool_execute(
        self,
        ctx: RunContext[AgentDepsT],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: ValidatedToolArgs,
        handler: WrapToolExecuteHandler,
    ) -> Any:
        if tool_def.kind != "function":
            return await handler(args)
        with span("tool", call.tool_name, tool_call_id=call.tool_call_id):
            return await handler(args)
