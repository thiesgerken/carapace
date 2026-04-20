from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pydantic_ai import ModelMessage
from pydantic_ai.messages import ModelRequest, ModelResponse, SystemPromptPart, TextPart, UserPromptPart

from carapace.usage import (
    InputShapeRatios,
    LlmRequestRecord,
    gauge_breakdown_pct_dict,
    input_shape_ratios_from_messages,
    usage_last_request_row,
)


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
