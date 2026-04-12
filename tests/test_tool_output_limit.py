"""Tests for configurable tool output truncation."""

from carapace.agent.tools import truncate_tool_output


def test_truncate_tool_output_unlimited_zero():
    text = "x" * 10
    assert truncate_tool_output(text, 0) == text


def test_truncate_tool_output_fits():
    text = "hello"
    assert truncate_tool_output(text, 100) == text


def test_truncate_tool_output_truncates():
    text = "abcdefghij"
    out = truncate_tool_output(text, 4)
    assert out.startswith("abcd")
    assert "10 characters total" in out
    assert "limit 4" in out
