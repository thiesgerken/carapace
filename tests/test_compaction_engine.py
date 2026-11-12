"""Integration tests for /compact orchestration (engine + summarizer with TestModel)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from loguru import logger
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ThinkingPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.usage import RequestUsage

from carapace.config import build_config
from carapace.models.session import SessionState
from carapace.session.compaction import (
    fold_summary_text,
    is_fold_message,
    make_fold_message,
    split_lead_folds,
    tool_return_is_compacted,
)
from carapace.session.compaction_engine import CompactionError
from carapace.session.compaction_summarizer import summarize_tool_output
from carapace.session.transcript import completed_model_turn_end_indexes
from carapace.usage import count_message_tokens
from tests.session_helpers import _make_engine, _patch_sentinel
from tests.test_autonomy_limit import _read_calls, _streaming_model


def _turn(i: int, *, tool_output: str | None = None) -> list:
    msgs: list = [ModelRequest(parts=[UserPromptPart(content=f"question {i}")])]
    if tool_output is not None:
        cid = f"call-{i}"
        msgs.append(ModelResponse(parts=[ToolCallPart(tool_name="exec", args={"cmd": "ls"}, tool_call_id=cid)]))
        msgs.append(ModelRequest(parts=[ToolReturnPart(tool_name="exec", content=tool_output, tool_call_id=cid)]))
    msgs.append(ModelResponse(parts=[TextPart(content=f"answer {i}")]))
    return msgs


async def _compact(engine, active, *, keep_turns: int | None = None, verbatim_tool_turns: int | None = None):
    """`/compact` with the ladder's settings overridden for this test (the command no longer takes them)."""
    cfg = engine.config.agent.compaction
    if keep_turns is not None:
        cfg.keep_turns = keep_turns
    if verbatim_tool_turns is not None:
        cfg.verbatim_tool_turns = verbatim_tool_turns
    return await engine.run_compaction(active)


def _seed(engine, sid: str, n: int, *, tool_output: str | None = None) -> None:
    history: list = []
    events: list = []
    for i in range(n):
        history += _turn(i, tool_output=tool_output)
        events.append({"role": "user", "content": f"question {i}"})
        if tool_output is not None:
            events.append({"role": "tool_call", "tool": "exec", "tool_id": f"call-{i}"})
            events.append({"role": "tool_result", "tool": "exec", "tool_id": f"call-{i}", "result": tool_output})
        events.append({"role": "assistant", "content": f"answer {i}"})
    engine.session_mgr.save_history(sid, history)
    engine.session_mgr.save_events(sid, events)


def test_reset_warns_when_history_desynced_from_events(tmp_path: Path, db_factory) -> None:
    """A source whose model history lags its events must log a loud truncation warning, not silently cut."""

    async def _run() -> None:
        with _patch_sentinel():
            engine = _make_engine(tmp_path, session_factory=db_factory)
        sid = engine.session_mgr.create_session(user="thies").session_id
        engine.get_or_activate(sid)
        # 6 full event turns, but a model history with only the first turn (desynced source).
        _seed(engine, sid, 6)
        full = engine.session_mgr.load_history(sid)
        engine.session_mgr.save_history(sid, full[:2])  # turn 0 only (user-prompt + response)

        logs: list[str] = []
        sink_id = logger.add(lambda m: logs.append(m.record["message"]), level="WARNING")
        try:
            assert await engine.reset_to_turn(sid, 11) is True  # reset to turn 5
        finally:
            logger.remove(sink_id)

        assert any("out of sync with the event transcript" in m for m in logs)

    asyncio.run(_run())


def test_tool_result_annotation_matches_provider_id() -> None:
    """Events key tools by a carapace UUID; annotation must match the model's provider id instead."""
    from carapace.session.compaction import AppliedToolReturn
    from carapace.session.compaction_engine import _annotate_tool_result_events

    events = [
        # Real-world shape: tool_id is a UUID, model_tool_call_id is the provider call id.
        {"role": "tool_result", "tool": "exec", "tool_id": "uuid-aaa", "model_tool_call_id": "call_xyz__thought__z"},
        # Legacy event without model_tool_call_id falls back to tool_id.
        {"role": "tool_result", "tool": "exec", "tool_id": "call_legacy"},
    ]
    applied = {
        "call_xyz__thought__z": AppliedToolReturn(new_content="s", orig_tokens=100, summary_tokens=2),
        "call_legacy": AppliedToolReturn(new_content="s", orig_tokens=80, summary_tokens=1),
    }
    _annotate_tool_result_events(events, applied)
    assert events[0]["compaction"]["orig_tokens"] == 100
    assert events[1]["compaction"]["orig_tokens"] == 80


def test_compaction_model_precedence(tmp_path: Path, db_factory) -> None:
    """Resolution order: per-session override → platform compaction_model → title model."""
    with _patch_sentinel():
        engine = _make_engine(tmp_path, session_factory=db_factory)
    sid = engine.session_mgr.create_session(user="thies").session_id
    active = engine.get_or_activate(sid)

    agent_cfg = engine.config.agent
    # No override, no platform compaction model → fall back to the title model.
    agent_cfg.compaction_model = None
    active.compaction_model_name = None
    assert engine._compaction_model(active) == agent_cfg.title_model

    # Platform compaction model wins over the title model.
    agent_cfg.compaction_model = "openai:gpt-4o-mini"
    assert engine._compaction_model(active) == "openai:gpt-4o-mini"

    # A per-session override wins over everything.
    active.compaction_model_name = "anthropic:claude-haiku-4-5"
    assert engine._compaction_model(active) == "anthropic:claude-haiku-4-5"


def test_reset_into_folded_region_collapses_to_lead_fold(tmp_path: Path, db_factory) -> None:
    """Rewinding to a turn the fold swallowed keeps only the fold summary, consistent with events."""

    async def _run() -> None:
        with _patch_sentinel():
            engine = _make_engine(tmp_path, session_factory=db_factory)
        sid = engine.session_mgr.create_session(user="thies").session_id
        active = engine.get_or_activate(sid)
        _seed(engine, sid, 10)
        await _compact(engine, active, keep_turns=3)  # folds turns 0-6

        # Reset to turn 2 (assistant event index 5) — inside the folded region.
        assert await engine.reset_to_turn(sid, 5) is True

        history = engine.session_mgr.load_history(sid)
        lead, rest = split_lead_folds(history)
        # Tail turns = 0: only the fold summary survives, no dangling verbatim turns.
        assert len(lead) == 1 and is_fold_message(lead[0])
        assert completed_model_turn_end_indexes(rest) == []
        # The fold still has turns in the (truncated) events, so its tree node is retained.
        assert len(engine.session_mgr.load_compaction(sid).nodes) == 1

    asyncio.run(_run())


def test_compact_fold_collapses_old_turns(tmp_path: Path, db_factory) -> None:
    async def _run() -> None:
        with _patch_sentinel():
            engine = _make_engine(tmp_path, session_factory=db_factory)
        sid = engine.session_mgr.create_session(user="thies").session_id
        active = engine.get_or_activate(sid)
        _seed(engine, sid, 10)

        report = await _compact(engine, active, keep_turns=3)

        assert report.turns_folded == 7
        assert report.after_tokens < report.before_tokens
        history = engine.session_mgr.load_history(sid)
        lead, rest = split_lead_folds(history)
        assert len(lead) == 1 and is_fold_message(lead[0])
        assert len(completed_model_turn_end_indexes(rest)) == 3
        # tree persisted
        tree = engine.session_mgr.load_compaction(sid)
        assert len(tree.nodes) == 1
        # oldest events annotated with the fold node id
        events = list(engine.session_mgr.load_events(sid))
        assert any(e.get("compaction", {}).get("folded_into") == tree.nodes[0].id for e in events)

    asyncio.run(_run())


def test_rebuild_uses_provider_tool_call_id() -> None:
    """Uncompact must restore the model's provider call id on both the call and the return.

    Pairing events by the carapace UUID is correct, but the rebuilt parts have to carry
    ``model_tool_call_id`` (recorded only on the result event) so the next agent turn pairs
    the call to its return as the provider does. A legacy event without it falls back to the UUID.
    """
    from carapace.session.transcript import rebuild_model_history_from_events

    events = [
        {"role": "tool_call", "tool": "exec", "args": {"cmd": "ls"}, "tool_id": "uuid-aaa"},
        {"role": "tool_result", "tool": "exec", "result": "ok", "tool_id": "uuid-aaa", "model_tool_call_id": "call_x"},
        {"role": "tool_call", "tool": "exec", "args": {}, "tool_id": "uuid-legacy"},
        {"role": "tool_result", "tool": "exec", "result": "ok", "tool_id": "uuid-legacy"},
    ]
    msgs = rebuild_model_history_from_events(events)
    ids = [p.tool_call_id for m in msgs for p in m.parts if isinstance(p, (ToolCallPart, ToolReturnPart))]
    # Provider id on both call+return for the modern event; UUID fallback for the legacy one.
    assert ids == ["call_x", "call_x", "uuid-legacy", "uuid-legacy"]


def test_rebuild_restores_attachment_preamble() -> None:
    """User events store only the typed text; rebuild must re-augment from persisted attachments."""
    from carapace.session.transcript import rebuild_model_history_from_events

    events = [
        {
            "role": "user",
            "content": "summarize this",
            "attachments": [{"name": "report.pdf", "path": "/work/report.pdf"}],
        }
    ]
    [msg] = rebuild_model_history_from_events(events)
    text = msg.parts[0].content
    assert "report.pdf" in text and "/work/report.pdf" in text
    assert text.endswith("summarize this")


def test_uncompact_restores_history_from_events(tmp_path: Path, db_factory) -> None:
    """/uncompact rebuilds the full history from the transcript and clears all compaction state."""

    async def _run() -> None:
        with _patch_sentinel():
            engine = _make_engine(tmp_path, session_factory=db_factory)
        sid = engine.session_mgr.create_session(user="thies").session_id
        active = engine.get_or_activate(sid)
        _seed(engine, sid, 8, tool_output="x" * 4000)

        await _compact(engine, active, keep_turns=3)
        compacted = engine.session_mgr.load_history(sid)
        lead, _rest = split_lead_folds(compacted)
        assert lead and engine.session_mgr.load_compaction(sid).nodes  # actually compacted

        res = await engine.run_uncompaction(active)
        assert res["restored"] is True

        restored = engine.session_mgr.load_history(sid)
        # No fold messages left, tree cleared, every turn's tool output back to full length.
        assert split_lead_folds(restored)[0] == []
        assert engine.session_mgr.load_compaction(sid).nodes == []
        assert len(completed_model_turn_end_indexes(restored)) == 8
        assert not any(
            tool_return_is_compacted(p)
            for m in restored
            for p in getattr(m, "parts", [])
            if isinstance(p, ToolReturnPart)
        )
        assert all("compaction" not in e for e in engine.session_mgr.load_events(sid))

        # Idempotent: nothing left to undo.
        assert (await engine.run_uncompaction(active))["restored"] is False

    asyncio.run(_run())


def test_reset_after_fold_keeps_history_in_sync(tmp_path: Path, db_factory) -> None:
    """Reset past the verbatim tail must slice folded history by events, not raw model-turn count."""

    async def _run() -> None:
        with _patch_sentinel():
            engine = _make_engine(tmp_path, session_factory=db_factory)
        sid = engine.session_mgr.create_session(user="thies").session_id
        active = engine.get_or_activate(sid)
        _seed(engine, sid, 10)
        await _compact(engine, active, keep_turns=3)

        # Reset to turn 8 (assistant event index 17): drops turn 9, keeps the fold + turns 7,8.
        assert await engine.reset_to_turn(sid, 17) is True

        history = engine.session_mgr.load_history(sid)
        lead, rest = split_lead_folds(history)
        assert len(lead) == 1 and is_fold_message(lead[0])
        # Only the two surviving verbatim turns remain — not the stale turn 9.
        assert len(completed_model_turn_end_indexes(rest)) == 2
        # Tree still references the surviving fold; no dangling nodes.
        tree = engine.session_mgr.load_compaction(sid)
        assert len(tree.nodes) == 1

    asyncio.run(_run())


def test_fork_after_fold_carries_trimmed_tree(tmp_path: Path, db_factory) -> None:
    """A fork of a folded session inherits matching folds + a compaction tree (not a dangling one)."""

    async def _run() -> None:
        with _patch_sentinel():
            engine = _make_engine(tmp_path, session_factory=db_factory)
        sid = engine.session_mgr.create_session(user="thies").session_id
        active = engine.get_or_activate(sid)
        _seed(engine, sid, 10)
        await _compact(engine, active, keep_turns=3)

        forked = engine.fork_session(sid, event_index=17, channel_type="cli")
        history = engine.session_mgr.load_history(forked.session_id)
        lead, rest = split_lead_folds(history)
        assert len(lead) == 1 and is_fold_message(lead[0])
        assert len(completed_model_turn_end_indexes(rest)) == 2
        # The fork carries the fold's tree node so the fold UI renders.
        assert len(engine.session_mgr.load_compaction(forked.session_id).nodes) == 1

    asyncio.run(_run())


def test_compact_tools_summarizes_large_returns(tmp_path: Path, db_factory) -> None:
    async def _run() -> None:
        with _patch_sentinel():
            engine = _make_engine(tmp_path, session_factory=db_factory)
        engine._config.agent.compaction.verbatim_tool_turns = 1
        sid = engine.session_mgr.create_session(user="thies").session_id
        active = engine.get_or_activate(sid)
        _seed(engine, sid, 3, tool_output="line\n" * 3000)

        report = await _compact(engine, active)

        assert report.tool_returns_compacted >= 1
        history = engine.session_mgr.load_history(sid)
        compacted = [
            p
            for m in history
            if isinstance(m, ModelRequest)
            for p in m.parts
            if isinstance(p, ToolReturnPart) and tool_return_is_compacted(p)
        ]
        assert compacted
        # tool_result events annotated with the token savings
        events = list(engine.session_mgr.load_events(sid))
        assert any(e.get("compaction", {}).get("orig_tokens") for e in events)
        # idempotent: a second run compacts nothing new
        report2 = await _compact(engine, active)
        assert report2.tool_returns_compacted == 0

    asyncio.run(_run())


def test_compact_tools_keeps_verbatim_hot_zone(tmp_path: Path, db_factory) -> None:
    """The newest verbatim_tool_turns turns keep tool outputs verbatim; older ones get summarized."""

    async def _run() -> None:
        with _patch_sentinel():
            engine = _make_engine(tmp_path, session_factory=db_factory)
        engine._config.agent.compaction.verbatim_tool_turns = 2
        sid = engine.session_mgr.create_session(user="thies").session_id
        active = engine.get_or_activate(sid)
        _seed(engine, sid, 5, tool_output="line\n" * 3000)

        await _compact(engine, active)

        history = engine.session_mgr.load_history(sid)
        compacted_ids = {
            p.tool_call_id
            for m in history
            if isinstance(m, ModelRequest)
            for p in m.parts
            if isinstance(p, ToolReturnPart) and tool_return_is_compacted(p)
        }
        # 5 turns, hot zone of 2 → the newest two (call-3, call-4) stay verbatim.
        assert "call-4" not in compacted_ids
        assert "call-3" not in compacted_ids
        assert {"call-0", "call-1", "call-2"} <= compacted_ids

    asyncio.run(_run())


def test_compact_tools_verbatim_override(tmp_path: Path, db_factory) -> None:
    """`/compact tools N` overrides the configured hot zone for that run."""

    async def _run() -> None:
        with _patch_sentinel():
            engine = _make_engine(tmp_path, session_factory=db_factory)
        engine._config.agent.compaction.verbatim_tool_turns = 4  # config would shield everything
        sid = engine.session_mgr.create_session(user="thies").session_id
        active = engine.get_or_activate(sid)
        _seed(engine, sid, 5, tool_output="line\n" * 3000)

        # Override to 1: only the newest turn stays verbatim, so call-0..call-3 compact.
        await _compact(engine, active, verbatim_tool_turns=1)

        compacted_ids = {
            p.tool_call_id
            for m in engine.session_mgr.load_history(sid)
            if isinstance(m, ModelRequest)
            for p in m.parts
            if isinstance(p, ToolReturnPart) and tool_return_is_compacted(p)
        }
        assert "call-4" not in compacted_ids
        assert {"call-0", "call-1", "call-2", "call-3"} <= compacted_ids

    asyncio.run(_run())


def test_compact_focus_reaches_every_summary_request(tmp_path: Path, db_factory) -> None:
    prompts: list[str] = []

    async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        prompts.append(str(messages[-1].parts[-1].content))
        return ModelResponse(parts=[TextPart(content="short")])

    async def _run() -> None:
        with _patch_sentinel():
            engine = _make_engine(tmp_path, session_factory=db_factory)
        engine._model_factory = lambda _name, *, user: FunctionModel(respond)
        engine._config.agent.compaction.keep_turns = 3
        engine._config.agent.compaction.verbatim_tool_turns = 1
        sid = engine.session_mgr.create_session(user="thies").session_id
        engine.get_or_activate(sid)
        _seed(engine, sid, 6, tool_output="line\n" * 6000)

        res = await engine.handle_slash_command(sid, "/compact keep the migration details")

        assert res is not None and res["data"]["mode"] == "manual"
        assert res["data"]["turns_folded"] == 3 and res["data"]["tool_returns_compacted"] == 2
        assert len(prompts) == 3
        assert all(p.endswith("focus on: keep the migration details") for p in prompts)

    asyncio.run(_run())


def test_preview_matches_the_run_without_an_llm_call(tmp_path: Path, db_factory) -> None:
    async def no_llm(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        raise AssertionError("the preview must not call a model")

    async def _run() -> None:
        with _patch_sentinel():
            engine = _make_engine(tmp_path, session_factory=db_factory)
        engine._model_factory = lambda _name, *, user: FunctionModel(no_llm)
        engine._config.agent.compaction.keep_turns = 3
        engine._config.agent.compaction.verbatim_tool_turns = 1
        sid = engine.session_mgr.create_session(user="thies").session_id
        active = engine.get_or_activate(sid)
        _seed(engine, sid, 6, tool_output="line\n" * 6000)

        preview = engine.preview_compaction(active)

        assert preview.turns_folded == 3
        assert [o.tool_name for o in preview.tool_outputs] == ["exec", "exec"]
        assert preview.threshold_tokens == 120_000 and preview.context_window_tokens == 200_000
        assert 0 < preview.estimated_tokens_without_summaries < preview.context_tokens

    asyncio.run(_run())


def test_compact_all_ladder_end_to_end(tmp_path: Path, db_factory) -> None:
    """`/compact` (all): thinking dropped + old turns folded + big tool outputs summarized."""

    async def _run() -> None:
        with _patch_sentinel():
            engine = _make_engine(tmp_path, session_factory=db_factory)
        engine._config.agent.compaction.verbatim_tool_turns = 1
        sid = engine.session_mgr.create_session(user="thies").session_id
        active = engine.get_or_activate(sid)

        # 10 turns, each with a large tool output and a thinking part in the response.
        history: list = []
        events: list = []
        for i in range(10):
            cid = f"call-{i}"
            history.append(ModelRequest(parts=[UserPromptPart(content=f"q{i}")]))
            history.append(
                ModelResponse(
                    parts=[
                        ThinkingPart(content=f"reason {i}"),
                        ToolCallPart(tool_name="exec", args={}, tool_call_id=cid),
                    ]
                )
            )
            history.append(
                ModelRequest(parts=[ToolReturnPart(tool_name="exec", content="row\n" * 3000, tool_call_id=cid)])
            )
            history.append(ModelResponse(parts=[TextPart(content=f"a{i}")]))
            events.append({"role": "user", "content": f"q{i}"})
            events.append({"role": "tool_call", "tool": "exec", "tool_id": cid})
            events.append({"role": "tool_result", "tool": "exec", "tool_id": cid, "result": "row\n" * 3000})
            events.append({"role": "assistant", "content": f"a{i}"})
        engine.session_mgr.save_history(sid, history)
        engine.session_mgr.save_events(sid, events)

        report = await _compact(engine, active, keep_turns=3)

        assert report.thinking_dropped > 0
        assert report.turns_folded == 7
        assert report.tool_returns_compacted >= 1  # only kept-region returns
        assert report.after_tokens < report.before_tokens
        # compaction LLM usage is attributed to its own category, not the agent
        assert "compaction" in active.usage_tracker.categories
        # idempotent second run
        report2 = await _compact(engine, active, keep_turns=3)
        assert report2.turns_folded == 0
        assert report2.tool_returns_compacted == 0

    asyncio.run(_run())


def test_fold_after_tools_still_badges_turns(tmp_path: Path, db_factory) -> None:
    """`/compact tools` then `/compact fold`: folded turns must still get folded_into badges."""

    async def _run() -> None:
        with _patch_sentinel():
            engine = _make_engine(tmp_path, session_factory=db_factory)
        sid = engine.session_mgr.create_session(user="thies").session_id
        active = engine.get_or_activate(sid)
        _seed(engine, sid, 10, tool_output="line\n" * 3000)

        # Tool outputs first (keeping every turn) — annotates tool_result events with the token savings.
        await _compact(engine, active, keep_turns=10)
        # Then fold the old turns.
        report = await _compact(engine, active, keep_turns=3)

        assert report.turns_folded == 7
        tree = engine.session_mgr.load_compaction(sid)
        node_id = tree.nodes[0].id
        events = list(engine.session_mgr.load_events(sid))
        folded = [e for e in events if e.get("compaction", {}).get("folded_into") == node_id]
        # 7 folded turns, each with user + tool_call + tool_result + assistant events, get the badge.
        assert len(folded) >= 7
        # tool method annotations survived the merge where both apply.
        assert any(
            e.get("compaction", {}).get("orig_tokens") and e.get("compaction", {}).get("folded_into") for e in events
        )

    asyncio.run(_run())


def test_compact_noop_when_short(tmp_path: Path, db_factory) -> None:
    async def _run() -> None:
        with _patch_sentinel():
            engine = _make_engine(tmp_path, session_factory=db_factory)
        sid = engine.session_mgr.create_session(user="thies").session_id
        active = engine.get_or_activate(sid)
        _seed(engine, sid, 2)
        report = await _compact(engine, active, keep_turns=6)
        assert report.turns_folded == 0
        assert report.message == "Nothing to compact."

    asyncio.run(_run())


def test_summaries_lead_with_the_agents_shared_prompt_prefix(tmp_path: Path) -> None:
    seen: list[str | None] = []

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        seen.append(info.instructions)
        return ModelResponse(parts=[TextPart(content="short")])

    async def _run() -> str:
        return await summarize_tool_output(
            "exec",
            "long output",
            prompt_prefix="# AGENTS.md",
            model="anthropic:claude-haiku-4-5",
            config=build_config(tmp_path),
            user="thies",
            usage_tracker=None,
            before_llm_call=None,
            model_factory=lambda _name, *, user: FunctionModel(respond),
            model_settings=None,
            usage_limits=None,
        )

    assert asyncio.run(_run()) == "short"
    [instructions] = seen
    assert instructions is not None and instructions.startswith("# AGENTS.md\n\n---\n\n# Compaction")


def test_failed_compact_reports_the_error_and_keeps_the_history(tmp_path: Path, db_factory) -> None:
    def provider_down(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        raise RuntimeError("provider down")

    async def _run() -> None:
        with _patch_sentinel():
            engine = _make_engine(tmp_path, session_factory=db_factory)
        engine._model_factory = lambda _name, *, user: FunctionModel(provider_down)
        sid = engine.session_mgr.create_session(user="thies").session_id
        engine.get_or_activate(sid)
        engine._config.agent.compaction.keep_turns = 3
        _seed(engine, sid, 10)
        before = engine.session_mgr.load_history(sid)

        res = await engine.handle_slash_command(sid, "/compact")

        assert res is not None and "provider down" in res["data"]["error"]
        assert engine.session_mgr.load_history(sid) == before
        assert engine.session_mgr.load_compaction(sid).nodes == []

    asyncio.run(_run())


def test_fold_input_too_large_for_the_compaction_model_fails(tmp_path: Path, db_factory) -> None:
    async def _run() -> None:
        with _patch_sentinel():
            engine = _make_engine(tmp_path, session_factory=db_factory)
        for entry in engine._config.agent.available_models:
            entry.max_input_tokens = 100
        sid = engine.session_mgr.create_session(user="thies").session_id
        engine.get_or_activate(sid)
        engine._config.agent.compaction.keep_turns = 3
        _seed(engine, sid, 10)

        res = await engine.handle_slash_command(sid, "/compact")

        assert res is not None and "input too large" in res["data"]["error"]
        assert engine.session_mgr.load_compaction(sid).nodes == []

    asyncio.run(_run())


def test_first_tool_summary_warms_the_cache_before_the_rest_run_concurrently(tmp_path: Path, db_factory) -> None:
    calls: list[str] = []

    async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        calls.append("start")
        await asyncio.sleep(0.01)
        calls.append("end")
        return ModelResponse(parts=[TextPart(content="short")])

    async def _run() -> None:
        with _patch_sentinel():
            engine = _make_engine(tmp_path, session_factory=db_factory)
        engine._model_factory = lambda _name, *, user: FunctionModel(respond)
        engine._config.agent.compaction.verbatim_tool_turns = 1
        sid = engine.session_mgr.create_session(user="thies").session_id
        active = engine.get_or_activate(sid)
        _seed(engine, sid, 4, tool_output="line\n" * 6000)

        report = await _compact(engine, active)

        assert report.tool_returns_compacted == 3
        assert calls == ["start", "end", "start", "start", "end", "end"]

    asyncio.run(_run())


def test_a_failing_tool_summary_cancels_its_siblings(tmp_path: Path, db_factory) -> None:
    calls: list[str] = []

    async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        calls.append("start")
        if len(calls) == 2:
            raise RuntimeError("provider down")
        if len(calls) == 3:
            await asyncio.sleep(0.1)
            calls.append("sibling finished")
        return ModelResponse(parts=[TextPart(content="short")])

    async def _run() -> None:
        with _patch_sentinel():
            engine = _make_engine(tmp_path, session_factory=db_factory)
        engine._model_factory = lambda _name, *, user: FunctionModel(respond)
        engine._config.agent.compaction.verbatim_tool_turns = 1
        sid = engine.session_mgr.create_session(user="thies").session_id
        engine.get_or_activate(sid)
        _seed(engine, sid, 4, tool_output="line\n" * 6000)

        res = await engine.handle_slash_command(sid, "/compact")

        assert res is not None and "provider down" in res["data"]["error"]
        await asyncio.sleep(0.2)
        assert "sibling finished" not in calls

    asyncio.run(_run())


def test_memory_block_is_frozen_per_session_until_compaction(tmp_path: Path, db_factory) -> None:
    async def _run() -> None:
        builds: list[tuple[str, str]] = []

        def memory_block_for(user: str, state: SessionState) -> str:
            builds.append((user, state.session_id))
            return f"memory #{len(builds)}"

        with _patch_sentinel():
            engine = _make_engine(tmp_path, session_factory=db_factory, memory_block_for=memory_block_for)
        sid = engine.session_mgr.create_session(user="thies").session_id
        active = engine.get_or_activate(sid)
        _seed(engine, sid, 10)

        engine._ensure_memory_snapshot(active)
        engine._ensure_memory_snapshot(active)
        stored = engine.session_mgr.load_state(sid)
        assert stored is not None and stored.memory is not None and stored.memory.text == "memory #1"
        assert builds == [("thies", sid)]

        await _compact(engine, active, keep_turns=3)
        engine._ensure_memory_snapshot(active)

        assert active.state.memory is not None and active.state.memory.text == "memory #2"

    asyncio.run(_run())


class _AgentAndSummarizer:
    """The agent streams its answer; the compaction model is run without streaming and summarizes."""

    def __init__(self) -> None:
        self.summary_inputs: list[str] = []

    def factory(self, _name: str, *, user: str) -> FunctionModel:
        return FunctionModel(self._summarize, stream_function=self._answer)

    def _summarize(self, messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        self.summary_inputs.append(str(messages[-1].parts[-1].content))
        return ModelResponse(parts=[TextPart(f"summary {len(self.summary_inputs)}")])

    async def _answer(self, _messages: list[ModelMessage], _info: AgentInfo) -> AsyncIterator[str]:
        yield "answer 10"


async def _fold_then_real_turn(tmp_path: Path, db_factory, models: _AgentAndSummarizer):
    """A folded session that then runs a real turn, so pydantic-ai merges the fold with the next prompt."""
    with _patch_sentinel():
        engine = _make_engine(tmp_path, session_factory=db_factory)
    engine._model_factory = models.factory
    sid = engine.session_mgr.create_session(user="thies").session_id
    active = engine.get_or_activate(sid)
    _seed(engine, sid, 10)
    await _compact(engine, active, keep_turns=3)
    await engine.submit_message(sid, "question 10")
    async with asyncio.timeout(5):
        while active.agent_task is not None:
            await asyncio.sleep(0.01)
    return engine, sid, active


def test_repeated_compact_after_a_real_turn_rolls_the_fold_up(tmp_path: Path, db_factory) -> None:
    async def _run() -> None:
        models = _AgentAndSummarizer()
        engine, sid, active = await _fold_then_real_turn(tmp_path, db_factory, models)

        await _compact(engine, active, keep_turns=3)

        assert len(models.summary_inputs) == 2
        assert "Earlier summary: summary 1\n" in models.summary_inputs[1]
        lead, rest = split_lead_folds(engine.session_mgr.load_history(sid))
        assert [fold_summary_text(fold).split("\n\n")[-1] for fold in lead] == ["summary 2"]
        assert len(completed_model_turn_end_indexes(rest)) == 3

    asyncio.run(_run())


def test_reset_and_fork_after_a_real_turn_keep_the_fold(tmp_path: Path, db_factory) -> None:
    async def _run() -> None:
        engine, sid, _active = await _fold_then_real_turn(tmp_path, db_factory, _AgentAndSummarizer())
        events = list(engine.session_mgr.load_events(sid))
        last_answer = max(
            i for i, e in enumerate(events) if e.get("role") == "assistant" and e.get("content") == "answer 9"
        )

        forked = engine.fork_session(sid, event_index=last_answer, channel_type="cli")
        assert await engine.reset_to_turn(sid, last_answer) is True

        for session_id in (forked.session_id, sid):
            lead, rest = split_lead_folds(engine.session_mgr.load_history(session_id))
            assert [fold_summary_text(fold).split("\n\n")[-1] for fold in lead] == ["summary 1"]
            assert len(completed_model_turn_end_indexes(rest)) == 3

    asyncio.run(_run())


def _merged_task_done_history(turns: int) -> list[ModelMessage]:
    """Unattended turns ending in task_done, each return merged by pydantic-ai with the next task's prompt."""
    history: list[ModelMessage] = []
    for i in range(turns):
        prompt = UserPromptPart(f"task {i}")
        if history:
            history[-1] = ModelRequest(parts=[*history[-1].parts, prompt])
        else:
            history.append(ModelRequest(parts=[prompt]))
        history += [
            ModelResponse(parts=[ToolCallPart("task_done", {"result": f"done {i}"}, tool_call_id=f"done-{i}")]),
            ModelRequest(parts=[ToolReturnPart("task_done", "Final result processed.", tool_call_id=f"done-{i}")]),
        ]
    return history


def test_compact_cuts_merged_task_done_turns_at_the_output_tool_return(tmp_path: Path, db_factory) -> None:
    """An unattended turn ends in a task_done return, which the next run merges with the next prompt."""

    async def _run() -> None:
        models = _AgentAndSummarizer()
        with _patch_sentinel():
            engine = _make_engine(tmp_path, session_factory=db_factory)
        engine._model_factory = models.factory
        sid = engine.session_mgr.create_session(user="thies").session_id
        active = engine.get_or_activate(sid)
        engine.session_mgr.save_history(sid, _merged_task_done_history(3))
        engine.session_mgr.save_events(
            sid,
            [
                e
                for i in range(3)
                for e in ({"role": "user", "content": f"task {i}"}, {"role": "assistant", "content": f"done {i}"})
            ],
        )

        report = await _compact(engine, active, keep_turns=1)

        assert report.turns_folded == 2
        lead, rest = split_lead_folds(engine.session_mgr.load_history(sid))
        assert len(lead) == 1
        call_ids = {p.tool_call_id for m in rest for p in m.parts if isinstance(p, ToolCallPart)}
        return_ids = {p.tool_call_id for m in rest for p in m.parts if isinstance(p, ToolReturnPart)}
        assert call_ids == return_ids == {"done-2"}
        assert "done 1" not in str(rest) and "task 2" in str(rest)

    asyncio.run(_run())


def test_attended_fork_of_merged_unattended_turns_keeps_every_task(tmp_path: Path, db_factory) -> None:
    with _patch_sentinel():
        engine = _make_engine(tmp_path, session_factory=db_factory)
    sid = engine.session_mgr.create_session(user="thies", unattended=True).session_id
    engine.get_or_activate(sid)
    engine.session_mgr.save_history(sid, _merged_task_done_history(2))
    events = [
        {"role": role, "content": f"{text} {i}"}
        for i in range(2)
        for role, text in (("user", "task"), ("assistant", "done"))
    ]
    engine.session_mgr.save_events(sid, events)

    forked = engine.fork_session(sid, event_index=len(events) - 1, channel_type="cli", unattended=False)

    history = engine.session_mgr.load_history(forked.session_id)
    assert [type(p).__name__ + ":" + str(p.content) for m in history for p in m.parts] == [
        "UserPromptPart:task 0",
        "TextPart:done 0",
        "UserPromptPart:task 1",
        "TextPart:done 1",
    ]


def test_reset_into_an_earlier_fold_falls_back_to_its_summary(tmp_path: Path, db_factory) -> None:
    """Rolling folds: the history holds only the newest summary, so a rewind behind it restores the older one."""

    async def _run() -> None:
        models = _AgentAndSummarizer()
        with _patch_sentinel():
            engine = _make_engine(tmp_path, session_factory=db_factory)
        engine._model_factory = models.factory
        sid = engine.session_mgr.create_session(user="thies").session_id
        active = engine.get_or_activate(sid)
        _seed(engine, sid, 10)
        await _compact(engine, active, keep_turns=6)  # turns 0-3 → summary 1
        await _compact(engine, active, keep_turns=3)  # summary 1 + turns 4-6 → summary 2
        events = list(engine.session_mgr.load_events(sid))
        answer_2 = next(i for i, e in enumerate(events) if e.get("content") == "answer 2")

        assert await engine.reset_to_turn(sid, answer_2) is True

        lead, rest = split_lead_folds(engine.session_mgr.load_history(sid))
        assert [fold_summary_text(f) for f in lead] == ["summary 1"] and rest == []
        assert [n.summary for n in engine.session_mgr.load_compaction(sid).nodes] == ["summary 1"]

    asyncio.run(_run())


def _threshold_engine(tmp_path: Path, db_factory, *, threshold: int):
    config = build_config(tmp_path)
    config.agent.available_models = [
        entry.model_copy(update={"compaction_threshold_tokens": threshold})
        if entry.model_id == config.agent.model
        else entry
        for entry in config.agent.available_models
    ]
    with _patch_sentinel():
        engine = _make_engine(tmp_path, session_factory=db_factory, config=config)
    sid = engine.session_mgr.create_session(user="thies").session_id
    return engine, sid, engine.get_or_activate(sid)


def _running_turn(engine, sid: str, steps: int, *, reported: int) -> list[ModelMessage]:
    """Two completed turns, then a running turn of *steps* tool steps whose last request reported *reported*."""
    _seed(engine, sid, 2)
    messages = [*engine.session_mgr.load_history(sid), ModelRequest(parts=[UserPromptPart(content="do the job")])]
    events: list[dict] = [{"role": "user", "content": "do the job"}]
    for i in range(steps):
        cid = f"step-{i}"
        messages += [
            ModelResponse(
                parts=[ToolCallPart(tool_name="exec", args={"n": i}, tool_call_id=cid)],
                usage=RequestUsage(input_tokens=reported),
            ),
            ModelRequest(parts=[ToolReturnPart(tool_name="exec", content="x " * 300, tool_call_id=cid)]),
        ]
        events += [
            {"role": "tool_call", "tool": "exec", "tool_id": cid},
            {"role": "tool_result", "tool": "exec", "tool_id": cid, "result": "x " * 300},
        ]
    engine.session_mgr.append_events(sid, events)
    return messages


def test_compaction_during_a_run_folds_steps_of_the_running_turn(tmp_path: Path, db_factory) -> None:
    async def _run() -> None:
        engine, sid, active = _threshold_engine(tmp_path, db_factory, threshold=2000)
        messages = _running_turn(engine, sid, 12, reported=2500)
        engine._ensure_memory_snapshot(active)
        memory = active.state.memory

        compacted = await engine.compact_during_run(active, messages)

        assert compacted is not None and is_fold_message(compacted[0])
        assert active.state.memory == memory  # the run already missed the cache; no second miss next turn
        assert isinstance(compacted[1], ModelResponse)  # the cut lies inside the running turn
        kept_calls = {p.tool_call_id for m in compacted for p in m.parts if isinstance(p, ToolCallPart)}
        kept_returns = {p.tool_call_id for m in compacted for p in m.parts if isinstance(p, ToolReturnPart)}
        assert kept_calls == kept_returns and "step-11" in kept_calls and "step-0" not in kept_calls
        [node] = engine.session_mgr.load_compaction(sid).nodes
        folded = {
            e.get("tool_id") or e.get("content") for e in engine.session_mgr.load_events(sid) if e.get("compaction")
        }
        assert {"question 0", "answer 1", "do the job", "step-0"} <= folded
        assert not folded & kept_calls

        # The turn ends and is saved; rewinding to its end keeps the fold and the verbatim tail.
        final = ModelResponse(parts=[TextPart(content="job done")])
        engine.session_mgr.save_history(sid, [*compacted, final])
        engine.session_mgr.append_events(sid, [{"role": "assistant", "content": "job done"}])
        events = engine.session_mgr.load_events(sid)
        assert await engine.reset_to_turn(sid, len(events) - 1) is True
        assert engine.session_mgr.load_history(sid) == [*compacted, final]
        # Rewinding to a turn the fold swallowed whole drops the split turn's tail.
        answer_1 = next(i for i, e in enumerate(events) if e.get("content") == "answer 1")
        assert await engine.reset_to_turn(sid, answer_1) is True
        assert engine.session_mgr.load_history(sid) == compacted[:1]
        assert [n.id for n in engine.session_mgr.load_compaction(sid).nodes] == [node.id]

    asyncio.run(_run())


def test_compaction_during_a_run_waits_for_the_threshold(tmp_path: Path, db_factory) -> None:
    async def _run() -> None:
        engine, sid, active = _threshold_engine(tmp_path, db_factory, threshold=2000)

        assert await engine.compact_during_run(active, _running_turn(engine, sid, 12, reported=1999)) is None
        assert engine.session_mgr.load_compaction(sid).nodes == []

    asyncio.run(_run())


def test_compaction_during_a_run_ignores_a_measurement_from_before_an_earlier_compaction(
    tmp_path: Path, db_factory
) -> None:
    async def _run() -> None:
        engine, sid, active = _threshold_engine(tmp_path, db_factory, threshold=2000)
        messages = _running_turn(engine, sid, 12, reported=2500)
        measured = next(m for m in reversed(messages) if isinstance(m, ModelResponse))
        active.state.compacted_through = measured.timestamp

        assert await engine.compact_during_run(active, messages) is None

        # A response measured after that compaction triggers again.
        active.state.compacted_through = measured.timestamp - timedelta(seconds=1)
        assert await engine.compact_during_run(active, messages) is not None
        assert active.state.compacted_through == measured.timestamp

    asyncio.run(_run())


def test_compaction_during_a_run_counts_what_the_provider_sees_beyond_the_messages(tmp_path: Path, db_factory) -> None:
    """A history small by the local estimate still compacts when the provider measured it above the threshold."""

    async def _run() -> None:
        engine, sid, active = _threshold_engine(tmp_path, db_factory, threshold=100_000)
        messages = _running_turn(engine, sid, 12, reported=150_000)

        compacted = await engine.compact_during_run(active, messages)

        assert compacted is not None and is_fold_message(compacted[0])

    asyncio.run(_run())


def test_a_failed_turns_terminal_message_does_not_hide_the_measurement(tmp_path: Path, db_factory) -> None:
    async def _run() -> None:
        engine, sid, active = _threshold_engine(tmp_path, db_factory, threshold=2000)
        messages = _running_turn(engine, sid, 12, reported=2500)
        messages += [
            ModelResponse(parts=[TextPart("Compaction failed: provider down")]),
            ModelRequest(parts=[UserPromptPart(content="continue")]),
        ]

        assert await engine.compact_during_run(active, messages) is not None

    asyncio.run(_run())


def test_compaction_during_a_run_stops_once_dropping_thinking_reaches_the_target(tmp_path: Path, db_factory) -> None:
    history = [*_turn(0), *_turn(1), *_turn(2), ModelRequest(parts=[UserPromptPart(content="go")])]
    history[1] = ModelResponse(parts=[ThinkingPart(content="ponder " * 3000), TextPart(content="answer 0")])
    size = count_message_tokens(history)
    messages = [
        *history,
        ModelResponse(parts=[ToolCallPart("exec", {}, "c")], usage=RequestUsage(input_tokens=size)),
        ModelRequest(parts=[ToolReturnPart("exec", "ok", tool_call_id="c")]),
    ]

    async def _run() -> None:
        engine, sid, active = _threshold_engine(tmp_path, db_factory, threshold=size - 1)

        compacted = await engine.compact_during_run(active, messages)

        assert compacted is not None and not any(is_fold_message(m) for m in compacted)
        assert not any(isinstance(p, ThinkingPart) for m in compacted for p in m.parts)
        assert engine.session_mgr.load_compaction(sid).nodes == []

    asyncio.run(_run())


def test_compaction_during_a_run_fails_when_nothing_is_left_to_compact(tmp_path: Path, db_factory) -> None:
    async def _run() -> None:
        engine, _sid, active = _threshold_engine(tmp_path, db_factory, threshold=100)
        huge_step = [
            ModelResponse(
                parts=[ToolCallPart(tool_name="exec", args={}, tool_call_id="c")], usage=RequestUsage(input_tokens=500)
            ),
            ModelRequest(parts=[ToolReturnPart(tool_name="exec", content="x " * 300, tool_call_id="c")]),
        ]

        with pytest.raises(CompactionError, match="nothing is left to compact"):
            await engine.compact_during_run(active, huge_step)

    asyncio.run(_run())


def test_a_turn_continues_from_and_saves_the_history_compacted_during_it(tmp_path: Path, db_factory) -> None:
    requests: list[list[ModelMessage]] = []

    def respond(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        requests.append(messages)
        return _read_calls(f"c{len(requests)}") if len(requests) < 4 else ModelResponse(parts=[TextPart("done")])

    async def fold_after_three_steps(_active, messages: list[ModelMessage]) -> list[ModelMessage] | None:
        if len(requests) != 3:
            return None
        newest_step = max(i for i, m in enumerate(messages) if isinstance(m, ModelResponse))
        return [make_fold_message("SUMMARY"), *messages[newest_step:]]

    async def _run() -> None:
        with _patch_sentinel():
            engine = _make_engine(tmp_path, session_factory=db_factory)
        engine._model_factory = lambda _name, *, user: _streaming_model(respond)
        engine.sandbox_mgr.file_read = AsyncMock(return_value="content")
        engine.compact_during_run = fold_after_three_steps  # type: ignore[method-assign]
        sid = engine.session_mgr.create_session(user="thies").session_id
        active = engine.get_or_activate(sid)

        await engine.submit_message(sid, "go")
        async with asyncio.timeout(5):
            while active.agent_task is not None:
                await asyncio.sleep(0.01)

        assert is_fold_message(requests[3][0])
        history = engine.session_mgr.load_history(sid)
        assert fold_summary_text(history[0]) == "SUMMARY"
        assert sum(is_fold_message(m) for m in history) == 1
        assert isinstance(history[-1], ModelResponse) and history[-1].parts == [TextPart("done")]

    asyncio.run(_run())


def test_a_cut_inside_a_turn_a_step_fold_split_keeps_the_summary_and_the_unfolded_part(
    tmp_path: Path, db_factory
) -> None:
    async def _run() -> None:
        engine, sid, active = _threshold_engine(tmp_path, db_factory, threshold=2000)
        messages = _running_turn(engine, sid, 11, reported=2500)
        # The narration that comes with the newest step, which stays verbatim.
        engine.session_mgr.append_events(sid, [{"role": "assistant", "content": "almost there", "partial": True}])
        messages += [
            ModelResponse(
                parts=[TextPart("almost there"), ToolCallPart("exec", {"n": 11}, "step-11")],
                usage=RequestUsage(input_tokens=2500),
            ),
            ModelRequest(parts=[ToolReturnPart("exec", "x " * 300, tool_call_id="step-11")]),
        ]
        engine.session_mgr.append_events(
            sid,
            [
                {"role": "tool_call", "tool": "exec", "tool_id": "step-11"},
                {"role": "tool_result", "tool": "exec", "tool_id": "step-11", "result": "x " * 300},
            ],
        )
        compacted = await engine.compact_during_run(active, messages)
        assert compacted is not None
        [node] = engine.session_mgr.load_compaction(sid).nodes
        engine.session_mgr.save_history(sid, [*compacted, ModelResponse(parts=[TextPart("job done")])])
        engine.session_mgr.append_events(sid, [{"role": "assistant", "content": "job done"}])
        events = engine.session_mgr.load_events(sid)
        narration = next(i for i, e in enumerate(events) if e.get("content") == "almost there")
        prompt = next(i for i, e in enumerate(events) if e.get("content") == "do the job")
        assert not events[narration].get("compaction") and events[prompt]["compaction"]["folded_into"] == node.id

        forked = engine.fork_session(sid, event_index=narration, channel_type="cli")
        fold, *unfolded = engine.session_mgr.load_history(forked.session_id)
        assert fold_summary_text(fold) == node.summary
        assert [[p.content for p in m.parts] for m in unfolded] == [["almost there"]]
        assert [n.id for n in engine.session_mgr.load_compaction(forked.session_id).nodes] == [node.id]

        # A cut at the folded prompt leaves nothing of the turn verbatim.
        assert await engine.reset_to_turn(sid, prompt) is True
        [fold] = engine.session_mgr.load_history(sid)
        assert fold_summary_text(fold) == node.summary
        assert all(e["compaction"]["folded_into"] == node.id for e in engine.session_mgr.load_events(sid)[2:])

    asyncio.run(_run())
