from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pydantic_ai import ModelMessage
from pydantic_ai.messages import (
    BinaryContent,
    FilePart,
    ModelRequest,
    ModelResponse,
    RetryFeedbackPart,
    RetryInfo,
    SystemPromptPart,
    TextPart,
    UserPromptPart,
)

from carapace.usage import (
    InputShapeRatios,
    LlmRequestLog,
    LlmRequestRecord,
    aggregate_turn_generation,
    count_message_tokens,
    gauge_breakdown_pct_dict,
    input_shape_ratios_from_messages,
    last_record_for_source,
    usage_last_request_row,
)


def test_aggregate_turn_generation_excludes_tool_time() -> None:
    base = datetime(2026, 6, 22, 12, 0, 0, tzinfo=UTC)

    def _rec(start_s: int, ttft_ms: int, decode_ms: int, out: int, inp: int) -> LlmRequestRecord:
        started = base + timedelta(seconds=start_s)
        first_text = started + timedelta(milliseconds=ttft_ms)
        return LlmRequestRecord(
            ts=started,
            source="agent",
            input_tokens=inp,
            output_tokens=out,
            started_at=started,
            first_text_at=first_text,
            completed_at=first_text + timedelta(milliseconds=decode_ms),
        )

    # Two agent requests with a long tool gap between them (request 2 starts 100s later).
    records = [
        _rec(start_s=0, ttft_ms=200, decode_ms=1000, out=100, inp=5000),
        _rec(start_s=100, ttft_ms=400, decode_ms=3000, out=300, inp=8000),
    ]

    stats = aggregate_turn_generation(records)

    assert stats["input_tokens"] == 13000  # provider input billed across rounds
    assert stats["output_tokens"] == 400  # provider output summed
    assert stats["ttft_ms"] == 200  # the turn's first request
    assert stats["generation_ms"] == 4000  # decode only (1000 + 3000), tool gap excluded


def test_aggregate_turn_generation_ignores_non_agent_and_interrupted() -> None:
    base = datetime(2026, 6, 22, 12, 0, 0, tzinfo=UTC)
    records = [
        LlmRequestRecord(ts=base, source="sentinel", output_tokens=999),
        LlmRequestRecord(ts=base, source="agent", outcome="interrupted", output_tokens=50),
    ]
    stats = aggregate_turn_generation(records)
    assert stats["output_tokens"] == 0
    assert stats["generation_ms"] is None


def test_input_shape_ratios_single_user_only() -> None:
    messages: list[ModelMessage] = [
        ModelRequest(parts=[UserPromptPart("hello world")]),
    ]
    r = input_shape_ratios_from_messages(messages, model_name="gpt-4o")
    assert r is not None
    assert abs(r.user - 1.0) < 1e-6


def test_input_shape_ratios_splits_system_and_user() -> None:
    messages: list[ModelMessage] = [
        ModelRequest(parts=[SystemPromptPart("sys"), UserPromptPart("hi")]),
    ]
    r = input_shape_ratios_from_messages(messages, model_name="gpt-4o")
    assert r is not None
    assert r.system > 0 and r.user > 0
    assert abs(r.system + r.user - 1.0) < 0.02


def test_input_shape_ratios_counts_retry_feedback_as_user_input() -> None:
    feedback = RetryFeedbackPart("Answer with a verdict.", retry=RetryInfo(cause="model_retry"))
    r = input_shape_ratios_from_messages([ModelRequest(parts=[feedback])], model_name="gpt-4o")
    assert r is not None
    assert abs(r.user - 1.0) < 1e-6


def test_input_shape_ratios_counts_first_model_request_instructions_only() -> None:
    """Agent ``instructions=`` is on ``ModelRequest.instructions``; only first request counts."""
    big = "S" * 200
    small_user = "U" * 200
    small_out = "A" * 200
    one_turn = input_shape_ratios_from_messages(
        [ModelRequest(instructions=big, parts=[UserPromptPart(small_user)])],
        model_name="gpt-4o",
    )
    two_turn = input_shape_ratios_from_messages(
        [
            ModelRequest(instructions=big, parts=[UserPromptPart(small_user)]),
            ModelResponse(parts=[TextPart(small_out)]),
            ModelRequest(instructions=big, parts=[UserPromptPart(small_user)]),
        ],
        model_name="gpt-4o",
    )
    assert one_turn is not None and two_turn is not None
    assert one_turn.system > 0
    # Later requests repeat the same blob; shape uses the first only.
    assert two_turn.system < one_turn.system


def test_input_shape_ratios_includes_assistant_response() -> None:
    messages = [
        ModelRequest(parts=[UserPromptPart("q")]),
        ModelResponse(parts=[TextPart("answer")]),
        ModelRequest(parts=[UserPromptPart("q2")]),
    ]
    r = input_shape_ratios_from_messages(messages, model_name="gpt-4o")
    assert r is not None
    assert r.assistant > 0
    total = r.system + r.user + r.assistant + r.tool_calls + r.tool_returns + r.other
    assert abs(total - 1.0) < 1e-5


def test_image_counts_as_flat_estimate_under_other() -> None:
    """An image's base64 is not tokenized: ~100 KB counts as one flat media estimate, booked as other."""
    image = BinaryContent(data=bytes(range(256)) * 400, media_type="image/png")
    messages: list[ModelMessage] = [
        ModelRequest(parts=[UserPromptPart(["Image file: chart.png (102400 bytes)", image])]),
    ]
    assert 1_600 <= count_message_tokens(messages, model_name="gpt-4o") < 1_700
    r = input_shape_ratios_from_messages(messages, model_name="gpt-4o")
    assert r is not None
    assert r.other > 0.95
    assert r.user > 0


def test_model_generated_image_counts_as_flat_estimate() -> None:
    image = BinaryContent(data=bytes(range(256)) * 400, media_type="image/png")
    messages: list[ModelMessage] = [ModelResponse(parts=[FilePart(image)])]
    assert count_message_tokens(messages, model_name="gpt-4o") == 1_600


def test_input_shape_ratios_empty_returns_none() -> None:
    messages: list = [
        ModelRequest(parts=[]),
    ]
    r = input_shape_ratios_from_messages(messages, model_name=None)
    assert r is None


def test_usage_last_request_row_tiktoken_pct_independent_of_api_output() -> None:
    rec = LlmRequestRecord(
        ts=datetime.now(tz=UTC),
        source="agent",
        input_tokens=100,
        output_tokens=50,
        input_shape=InputShapeRatios(
            system=0.5,
            user=0.5,
            assistant=0,
            tool_calls=0,
            tool_returns=0,
            other=0,
        ),
    )
    row = usage_last_request_row(rec)
    assert row is not None
    assert row["context_size"] == 150
    bp = row["breakdown_pct"]
    assert bp["system"] == 50.0 and bp["user"] == 50.0
    assert bp["assistant"] == 0.0
    total_pct = sum(v for v in bp.values() if isinstance(v, float))
    assert abs(total_pct - 100.0) < 1e-6


def test_usage_last_request_row_includes_timing_and_reasoning_tokens() -> None:
    started_at = datetime.now(tz=UTC)
    rec = LlmRequestRecord(
        ts=started_at,
        source="agent",
        input_tokens=100,
        output_tokens=50,
        started_at=started_at,
        first_thinking_at=started_at + timedelta(seconds=1),
        last_thinking_at=started_at + timedelta(seconds=2),
        first_text_at=started_at + timedelta(seconds=3),
        completed_at=started_at + timedelta(seconds=4),
        reasoning_tokens=64,
        input_shape=InputShapeRatios(
            system=0.5,
            user=0.5,
            assistant=0,
            tool_calls=0,
            tool_returns=0,
            other=0,
        ),
    )
    row = usage_last_request_row(rec)
    assert row is not None
    assert row["reasoning_tokens"] == 64
    assert row["ttft_ms"] == 3000


def test_usage_last_request_row_calculates_durations() -> None:
    started_at = datetime.now(tz=UTC)
    rec = LlmRequestRecord(
        ts=started_at,
        source="agent",
        input_tokens=100,
        output_tokens=50,
        started_at=started_at,
        first_thinking_at=started_at + timedelta(seconds=1),
        first_text_at=started_at + timedelta(seconds=3),
        completed_at=started_at + timedelta(seconds=5),
        input_shape=InputShapeRatios(
            system=0.5,
            user=0.5,
            assistant=0,
            tool_calls=0,
            tool_returns=0,
            other=0,
        ),
    )
    row = usage_last_request_row(rec)
    assert row is not None
    assert row["ttft_ms"] == 3000
    assert row["reasoning_duration_ms"] == 2000
    assert row["total_duration_ms"] == 5000


def test_last_record_for_source_skips_interrupted_records_by_default() -> None:
    started_at = datetime.now(tz=UTC)
    completed = LlmRequestRecord(
        ts=started_at + timedelta(seconds=1),
        request_id="req-complete",
        source="agent",
        outcome="completed",
        input_tokens=100,
        output_tokens=50,
        started_at=started_at,
        completed_at=started_at + timedelta(seconds=1),
    )
    interrupted = LlmRequestRecord(
        ts=started_at + timedelta(seconds=2),
        request_id="req-interrupted",
        source="agent",
        outcome="interrupted",
        started_at=started_at + timedelta(seconds=2),
    )
    log = LlmRequestLog(records=[completed, interrupted])

    assert last_record_for_source(log, "agent") == completed
    assert last_record_for_source(log, "agent", include_interrupted=True) == interrupted


def test_usage_last_request_row_falls_back_to_completion_for_tool_only_request() -> None:
    started_at = datetime.now(tz=UTC)
    rec = LlmRequestRecord(
        ts=started_at,
        source="agent",
        input_tokens=100,
        output_tokens=0,
        started_at=started_at,
        first_thinking_at=started_at + timedelta(seconds=1),
        completed_at=started_at + timedelta(seconds=4),
        input_shape=InputShapeRatios(
            system=0.5,
            user=0.5,
            assistant=0,
            tool_calls=0,
            tool_returns=0,
            other=0,
        ),
    )

    row = usage_last_request_row(rec)
    assert row is not None
    assert row["ttft_ms"] is None
    assert row["reasoning_duration_ms"] == 3000
    assert row["total_duration_ms"] == 4000


def test_gauge_breakdown_pct_dict_none_without_shape() -> None:
    rec = LlmRequestRecord(
        ts=datetime.now(tz=UTC),
        source="agent",
        input_tokens=10,
        output_tokens=5,
        input_shape=None,
    )
    assert gauge_breakdown_pct_dict(rec) is None


def test_gauge_breakdown_pct_dict_matches_row() -> None:
    rec = LlmRequestRecord(
        ts=datetime.now(tz=UTC),
        source="agent",
        input_tokens=100,
        output_tokens=0,
        input_shape=InputShapeRatios(
            system=0.8,
            user=0.2,
            assistant=0,
            tool_calls=0,
            tool_returns=0,
            other=0,
        ),
    )
    d = gauge_breakdown_pct_dict(rec)
    assert d is not None
    assert d["system"] == 80.0 and d["user"] == 20.0
