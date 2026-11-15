"""Model-history helpers: where turns end, and how unattended output reads in an attended fork."""

from __future__ import annotations

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from carapace.security.context import SENTINEL_VERDICT_TOOL
from carapace.session.transcript import (
    completed_model_turn_end_indexes,
    is_terminal_history_message,
    normalize_unattended_output_history,
)


def _output_return(tool_name: str, *, retried: bool) -> ModelRequest:
    outcome = "retried" if retried else "success"
    return ModelRequest(parts=[ToolReturnPart(tool_name, "x", tool_call_id="call-1", outcome=outcome)])


def _task_done(result: str, call_id: str) -> ModelResponse:
    return ModelResponse(parts=[ToolCallPart("task_done", {"result": result}, tool_call_id=call_id)])


def test_an_output_tool_return_ends_the_turn() -> None:
    for tool_name in ("task_done", "task_failed", SENTINEL_VERDICT_TOOL):
        assert is_terminal_history_message(_output_return(tool_name, retried=False))


def test_a_retried_output_tool_return_does_not_end_the_turn() -> None:
    for tool_name in ("task_done", "task_failed", SENTINEL_VERDICT_TOOL):
        assert not is_terminal_history_message(_output_return(tool_name, retried=True))


def test_a_turn_stopped_on_a_retried_verdict_is_not_completed() -> None:
    messages: list[ModelMessage] = [
        ModelRequest(parts=[UserPromptPart("evaluate")]),
        ModelResponse(parts=[ToolCallPart(SENTINEL_VERDICT_TOOL, {"decision": "revise"}, tool_call_id="call-1")]),
        _output_return(SENTINEL_VERDICT_TOOL, retried=True),
    ]

    assert completed_model_turn_end_indexes(messages) == []


def test_finished_task_output_becomes_assistant_text() -> None:
    messages: list[ModelMessage] = [
        ModelRequest(parts=[UserPromptPart("do it")]),
        _task_done("Done.", "call-1"),
        ModelRequest(parts=[ToolReturnPart("task_done", "ok", tool_call_id="call-1")]),
    ]

    normalized = normalize_unattended_output_history(messages)

    assert normalized == [messages[0], ModelResponse(parts=[TextPart("Done.")], timestamp=messages[1].timestamp)]


def test_rejected_task_output_is_not_shown_as_an_answer() -> None:
    rejected = _task_done("Half done.", "call-1")
    retry = ModelRequest(
        parts=[ToolReturnPart("task_done", "Finish the cleanup first.", tool_call_id="call-1", outcome="retried")]
    )
    messages: list[ModelMessage] = [
        ModelRequest(parts=[UserPromptPart("do it")]),
        rejected,
        retry,
        _task_done("Done.", "call-2"),
        ModelRequest(parts=[ToolReturnPart("task_done", "ok", tool_call_id="call-2")]),
    ]

    normalized = normalize_unattended_output_history(messages)

    assert normalized[:3] == [messages[0], rejected, retry]
    assert normalized[3:] == [ModelResponse(parts=[TextPart("Done.")], timestamp=messages[3].timestamp)]
