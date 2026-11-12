"""Unit tests for the pure compaction strategies."""

from __future__ import annotations

from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    ThinkingPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from carapace.models.compaction import FOLD_MARKER
from carapace.session.compaction import (
    AppliedToolReturn,
    apply_fold,
    apply_thinking_drop,
    apply_tool_return_compaction,
    find_tool_return_candidates,
    fold_render_text,
    is_fold_message,
    plan_fold,
    split_lead_folds,
    tool_return_is_compacted,
    truncate_tool_output,
)
from carapace.session.transcript import completed_model_turn_end_indexes


def _turn(user: str, *, assistant: str = "ok", tool: tuple[str, str] | None = None) -> list:
    """One complete turn: user prompt, optional tool call+return, terminal assistant text."""
    msgs: list = [ModelRequest(parts=[UserPromptPart(content=user)])]
    if tool is not None:
        name, output = tool
        call_id = f"call-{user}"
        msgs.append(ModelResponse(parts=[ToolCallPart(tool_name=name, args={}, tool_call_id=call_id)]))
        msgs.append(ModelRequest(parts=[ToolReturnPart(tool_name=name, content=output, tool_call_id=call_id)]))
    msgs.append(ModelResponse(parts=[TextPart(content=assistant)]))
    return msgs


def _history(n: int, *, tool_output: str | None = None) -> list:
    out: list = []
    for i in range(n):
        out += _turn(f"q{i}", assistant=f"a{i}", tool=("exec", tool_output) if tool_output else None)
    return out


# ----------------------------------------------------------------------------- thinking-drop


def test_thinking_drop_removes_old_keeps_last_turn():
    msgs = [
        ModelRequest(parts=[UserPromptPart(content="q0")]),
        ModelResponse(parts=[ThinkingPart(content="reason-0"), TextPart(content="a0")]),
        ModelRequest(parts=[UserPromptPart(content="q1")]),
        ModelResponse(parts=[ThinkingPart(content="reason-1"), TextPart(content="a1")]),
    ]
    out, dropped = apply_thinking_drop(msgs)
    assert dropped == 1
    # old turn lost its thinking, text kept
    assert [type(p).__name__ for p in out[1].parts] == ["TextPart"]
    # newest turn keeps thinking
    assert any(isinstance(p, ThinkingPart) for p in out[3].parts)


def test_thinking_drop_drops_thinking_only_message():
    msgs = [
        ModelRequest(parts=[UserPromptPart(content="q0")]),
        ModelResponse(parts=[ThinkingPart(content="reason")]),
        ModelResponse(parts=[TextPart(content="a0")]),
        ModelRequest(parts=[UserPromptPart(content="q1")]),
        ModelResponse(parts=[TextPart(content="a1")]),
    ]
    out, dropped = apply_thinking_drop(msgs)
    assert dropped == 1
    assert all(not (isinstance(m, ModelResponse) and any(isinstance(p, ThinkingPart) for p in m.parts)) for m in out)


# ------------------------------------------------------------------------ tool-return compaction


def test_find_candidates_respects_floor_and_size_order():
    big = "x\n" * 4000
    small = "tiny"
    msgs = _turn("a", tool=("exec", big)) + _turn("b", tool=("exec", small))
    cands = find_tool_return_candidates(msgs, floor_tokens=100)
    assert len(cands) == 1
    assert cands[0].content == big


def test_apply_tool_return_compaction_stamps_and_skips_recompaction():
    big = "y\n" * 4000
    msgs = _turn("a", tool=("exec", big))
    cands = find_tool_return_candidates(msgs, floor_tokens=100)
    applied = {
        cands[0].tool_call_id: AppliedToolReturn(
            new_content="listed 5 pods", orig_tokens=cands[0].tokens, summary_tokens=4
        )
    }
    out = apply_tool_return_compaction(msgs, applied)
    part = next(p for m in out if isinstance(m, ModelRequest) for p in m.parts if isinstance(p, ToolReturnPart))
    assert tool_return_is_compacted(part)
    assert "listed 5 pods" in part.content
    assert "re-run the tool" in part.content
    # second pass finds nothing (already compacted)
    assert find_tool_return_candidates(out, floor_tokens=100) == []


def test_truncate_tool_output_elides_middle():
    text = "\n".join(str(i) for i in range(100))
    out = truncate_tool_output(text, head_lines=3, tail_lines=3)
    assert out.startswith("0\n1\n2")
    assert out.endswith("97\n98\n99")
    assert "elided" in out


def test_truncate_tool_output_caps_single_line_dumps():
    out = truncate_tool_output("x" * 10_000 + "END", max_chars=100)
    assert len(out) < 200
    assert out.startswith("x" * 50)
    assert out.endswith("END")
    assert "characters elided" in out


def test_fold_render_text_keeps_tool_args_and_cuts_large_returns():
    huge = "\n".join(f"line {i}" for i in range(1000))
    msgs = [
        ModelRequest(parts=[UserPromptPart(content="list the pods")]),
        ModelResponse(
            parts=[ToolCallPart(tool_name="exec", args={"command": "kubectl get pods -A"}, tool_call_id="c1")]
        ),
        ModelRequest(parts=[ToolReturnPart(tool_name="exec", content=huge, tool_call_id="c1")]),
        ModelResponse(parts=[TextPart(content="done")]),
    ]
    text = fold_render_text(msgs)
    assert "User: list the pods" in text
    assert 'Assistant called exec({"command":"kubectl get pods -A"})' in text
    assert "line 0" in text and "line 999" in text
    assert "line 500" not in text
    assert "Assistant: done" in text


# -------------------------------------------------------------------------------- message-fold


def test_plan_fold_none_when_few_turns():
    assert plan_fold(_history(3), keep_turns=6) is None


def test_plan_and_apply_fold_keeps_window_and_pairs_intact():
    msgs = _history(10, tool_output="z\n" * 50)
    plan = plan_fold(msgs, keep_turns=3)
    assert plan is not None and not plan.is_empty
    new = apply_fold(plan, "SUMMARY-OF-OLD")
    # leads with a single fold message
    assert is_fold_message(new[0])
    assert new[0].parts[0].content.startswith(FOLD_MARKER)
    assert "SUMMARY-OF-OLD" in new[0].parts[0].content
    # exactly the last 3 turns kept verbatim
    lead, rest = split_lead_folds(new)
    assert len(lead) == 1
    assert len(completed_model_turn_end_indexes(rest)) == 3
    # every tool call still has its return in the kept region
    calls = [p for m in rest if isinstance(m, ModelResponse) for p in m.parts if isinstance(p, ToolCallPart)]
    rets = [p for m in rest if isinstance(m, ModelRequest) for p in m.parts if isinstance(p, ToolReturnPart)]
    assert {p.tool_call_id for p in calls} == {p.tool_call_id for p in rets}


def test_second_fold_appends_block_and_does_not_refold():
    msgs = _history(12)
    first = apply_fold(plan_fold(msgs, keep_turns=3), "SUM1")
    # grow with more turns, fold again
    grown = first + _history(6)
    plan2 = plan_fold(grown, keep_turns=3)
    assert plan2 is not None
    # the existing fold block is preserved as lead, not re-folded
    assert len(plan2.lead_folds) == 1
    second = apply_fold(plan2, "SUM2")
    lead, _rest = split_lead_folds(second)
    assert len(lead) == 2  # appended, not merged
    assert "SUM1" in lead[0].parts[0].content
    assert "SUM2" in lead[1].parts[0].content
