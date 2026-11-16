"""Read model of the turn timeline: the turn list and one turn's spans (see docs/debug-view.md, "Timeline").

Spans of finished turns come from the database, those of the running turn from its in-memory trace.
LLM requests are not stored as spans: their bars are joined in from the LLM request log and the
request in flight, which carry the turn and the span they started in.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from ..spans import Span, SpanStatus
from ..usage import LlmRequestRecord, LlmRequestState, LlmSource, RequestCost
from .manager import SessionManager
from .types import ActiveSession


class TurnSummary(BaseModel):
    turn_id: str
    started_at: datetime
    ended_at: datetime | None
    prompt_preview: str
    status: SpanStatus


class LlmPhases(BaseModel):
    role: LlmSource
    request_id: str
    model_name: str | None
    first_token_at: datetime | None
    first_thinking_at: datetime | None
    last_thinking_at: datetime | None
    first_text_at: datetime | None
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int | None
    cache_write_tokens: int | None
    cost: RequestCost | None


class TimelineSpan(Span):
    llm: LlmPhases | None = None


class TurnTimeline(BaseModel):
    turn: TurnSummary
    spans: list[TimelineSpan]


def _turn_summary(turn_id: str, root: Span) -> TurnSummary:
    return TurnSummary(
        turn_id=turn_id,
        started_at=root.started_at,
        ended_at=root.ended_at,
        prompt_preview=str(root.attrs["prompt"]),
        status=root.status,
    )


def _root(spans: list[Span]) -> Span:
    return next(span for span in spans if span.parent_id is None)


def _running_turn_spans(active: ActiveSession | None, turn_id: str | None = None) -> tuple[str, list[Span]] | None:
    """The running turn's id and a snapshot of its spans; with *turn_id*, only if it is that turn."""
    trace = active.turn_trace if active is not None else None
    if trace is None or (turn_id is not None and trace.turn_id != turn_id):
        return None
    return trace.turn_id, [span.model_copy(deep=True) for span in trace.spans.values()]


def session_turns(session_mgr: SessionManager, session_id: str, active: ActiveSession | None) -> list[TurnSummary]:
    """Every turn with a timeline, oldest first."""
    roots = session_mgr.load_turn_roots(session_id)
    if (running := _running_turn_spans(active)) is not None:
        turn_id, spans = running
        roots[turn_id] = _root(spans)
    return [_turn_summary(turn_id, root) for turn_id, root in roots.items()]


def _llm_span(
    request: LlmRequestRecord | LlmRequestState, *, status: SpanStatus, ended_at: datetime | None
) -> TimelineSpan:
    if request.request_id is None or request.started_at is None:
        raise ValueError(f"LLM request of turn {request.turn_id} lacks its id or start time")
    record = request if isinstance(request, LlmRequestRecord) else None
    return TimelineSpan(
        # Request ids are random hex like span ids, so they double as the bar's span id.
        span_id=request.request_id,
        parent_id=request.span_id,
        kind="llm",
        name=request.source,
        started_at=request.started_at,
        ended_at=ended_at,
        status=status,
        llm=LlmPhases(
            role=request.source,
            request_id=request.request_id,
            model_name=request.model_name,
            first_token_at=None,
            first_thinking_at=request.first_thinking_at,
            last_thinking_at=request.last_thinking_at,
            first_text_at=request.first_text_at,
            input_tokens=record.input_tokens if record else 0,
            output_tokens=record.output_tokens if record else 0,
            cache_read_tokens=record.cache_read_tokens if record else None,
            cache_write_tokens=record.cache_write_tokens if record else None,
            cost=record.cost if record else None,
        ),
    )


def _llm_spans(turn_id: str, records: list[LlmRequestRecord], in_flight: LlmRequestState | None) -> list[TimelineSpan]:
    spans = [
        _llm_span(
            record,
            status="ok" if record.outcome == "completed" else "interrupted",
            ended_at=record.ts,
        )
        for record in records
        if record.turn_id == turn_id
    ]
    if in_flight is not None and in_flight.turn_id == turn_id:
        spans.append(_llm_span(in_flight, status="running", ended_at=None))
    return spans


def turn_timeline(
    session_mgr: SessionManager, session_id: str, turn_id: str, active: ActiveSession | None
) -> TurnTimeline | None:
    """The spans of *turn_id* with its LLM requests joined in; ``None`` if the turn has no timeline."""
    running = _running_turn_spans(active, turn_id)
    spans = running[1] if running is not None else session_mgr.load_turn_spans(session_id, turn_id)
    if not spans:
        return None
    # An active session's log is current in memory: the request sink appends before it saves.
    records = (active.llm_request_log if active is not None else session_mgr.load_llm_request_log(session_id)).records
    in_flight = active.llm_request_state if active is not None else None
    timeline = [TimelineSpan.model_validate(span.model_dump()) for span in spans]
    timeline += _llm_spans(turn_id, records, in_flight)
    return TurnTimeline(
        turn=_turn_summary(turn_id, _root(spans)),
        spans=sorted(timeline, key=lambda span: span.started_at),
    )
