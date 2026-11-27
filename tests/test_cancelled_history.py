from __future__ import annotations

from pydantic_ai.messages import ModelRequest, ModelResponse, ToolCallPart, ToolReturnPart, UserPromptPart

from carapace.session.turns import _complete_cancelled_model_history


def test_open_tool_calls_get_a_failed_return() -> None:
    history = [
        ModelRequest(parts=[UserPromptPart(content="go")]),
        ModelResponse(
            parts=[ToolCallPart(tool_name="exec", tool_call_id="a"), ToolCallPart(tool_name="read", tool_call_id="b")]
        ),
        ModelRequest(parts=[ToolReturnPart(tool_name="exec", content="ok", tool_call_id="a")]),
    ]

    completed = _complete_cancelled_model_history(history, "interrupted")

    assert completed[:3] == history
    [closing] = completed[3:]
    assert isinstance(closing, ModelRequest)
    [part] = closing.parts
    assert isinstance(part, ToolReturnPart)
    assert (part.tool_name, part.tool_call_id, part.content, part.outcome) == ("read", "b", "interrupted", "failed")


def test_history_without_open_calls_is_unchanged() -> None:
    history = [ModelRequest(parts=[UserPromptPart(content="hi")])]
    assert _complete_cancelled_model_history(history, "interrupted") == history
