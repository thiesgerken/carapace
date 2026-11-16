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
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

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


def _new_span(kind: str, name: str, parent_id: str | None, attrs: dict[str, SpanAttr]) -> Span:
    return Span(
        span_id=secrets.token_hex(8),
        parent_id=parent_id,
        kind=kind,
        name=name,
        started_at=datetime.now(tz=UTC),
        attrs=attrs,
    )


class TurnTrace:
    """The spans of one running turn; *on_change* hears every span start and end."""

    def __init__(self, turn_id: str, on_change: Callable[[Span], None]) -> None:
        self.turn_id = turn_id
        self.spans: dict[str, Span] = {}
        self.closed = False
        self._on_change = on_change

    def start(self, kind: str, name: str, *, parent_id: str | None, attrs: dict[str, SpanAttr]) -> Span:
        if self.closed:
            raise RuntimeError(f"turn {self.turn_id} is closed, no span can start in it")
        span = _new_span(kind, name, parent_id, attrs)
        self.spans[span.span_id] = span
        self._on_change(span)
        return span

    def end(self, span: Span, status: SpanStatus) -> None:
        # A span the turn's close already interrupted keeps that status.
        if span.status != "running":
            return
        span.status = status
        span.ended_at = datetime.now(tz=UTC)
        self._on_change(span)

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
def span(kind: str, name: str, **attrs: SpanAttr) -> Iterator[Span]:
    """Time the block as a span under the current one; its status follows how the block exits.

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
    except BaseException:
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
