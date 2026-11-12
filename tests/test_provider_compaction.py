"""Provider-side compaction: which models use it, provider switches, and how it shows up."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from pydantic_ai.messages import (
    CompactionPart,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)
from pydantic_ai.models.anthropic import AnthropicCompaction
from pydantic_ai.models.openai import OpenAICompaction
from pydantic_ai.usage import RequestUsage, RunUsage

from carapace.agent.history_compaction import ProviderCompactionMarkerCapability
from carapace.llm import ANTHROPIC_MIN_COMPACTION_TOKENS, provider_compaction
from carapace.models.config import AvailableModelEntry
from carapace.server.history import HistoryMessage
from carapace.session.compaction import has_foreign_compaction, is_fold_message, strip_compaction_parts
from carapace.usage import split_provider_compaction_usage
from tests.session_helpers import _make_engine, _patch_sentinel
from tests.test_compaction_engine import _AgentAndSummarizer, _local_compaction_config, _seed, _turn


def _compacted(provider: str, summary: str | None = "SUMMARY") -> ModelResponse:
    return ModelResponse(
        parts=[CompactionPart(content=summary, provider_name=provider), TextPart("answer")],
        usage=RequestUsage(input_tokens=1000),
    )


def test_anthropic_compacts_server_side_at_the_threshold_clamped_to_its_minimum() -> None:
    entry = AvailableModelEntry(provider="anthropic", name="claude", max_input_tokens=60_000)

    provider = provider_compaction(entry, instructions="FOLD")

    assert provider is not None and provider.provider_name == "anthropic"
    assert isinstance(provider.capability, AnthropicCompaction)
    assert provider.capability.token_threshold == ANTHROPIC_MIN_COMPACTION_TOKENS
    assert provider.capability.instructions == "FOLD"


def test_openai_responses_compacts_server_side_without_instructions() -> None:
    entry = AvailableModelEntry(provider="openai-responses", name="gpt", compaction_threshold_tokens=90_000)

    provider = provider_compaction(entry, instructions="FOLD")

    assert provider is not None and provider.provider_name == "openai"
    assert isinstance(provider.capability, OpenAICompaction)
    assert not provider.capability.stateless and provider.capability.token_threshold == 90_000


@pytest.mark.parametrize(
    "entry",
    [
        AvailableModelEntry(provider="openai-responses", name="gpt", base_url="http://llama.local/v1"),
        # The Codex backend answers `/responses/compact` with 404 (verified 2026-11-12).
        AvailableModelEntry(provider="openai-codex", name="gpt-5.5"),
        AvailableModelEntry(provider="openai-chat", name="gpt"),
        AvailableModelEntry(provider="openrouter", name="any/model"),
    ],
)
def test_other_models_compact_locally(entry: AvailableModelEntry) -> None:
    assert provider_compaction(entry, instructions="FOLD") is None


def test_stripping_keeps_the_originals_and_only_the_kept_providers_parts() -> None:
    history: list[ModelMessage] = [
        ModelRequest(parts=[UserPromptPart("q")]),
        _compacted("openai"),
        ModelResponse(parts=[CompactionPart(content=None, provider_name="openai")]),
    ]

    assert has_foreign_compaction(history, keep_provider="anthropic")
    assert not has_foreign_compaction(history, keep_provider="openai")
    stripped = strip_compaction_parts(history, keep_provider="anthropic")
    assert len(stripped) == 2 and stripped[1].parts == [TextPart("answer")]
    assert strip_compaction_parts(history, keep_provider="openai") == history


def test_a_turn_on_another_provider_strips_foreign_compaction_and_runs_the_local_ladder(
    tmp_path: Path, db_factory
) -> None:
    async def _run() -> None:
        with _patch_sentinel():
            engine = _make_engine(tmp_path, session_factory=db_factory, config=_local_compaction_config(tmp_path))
        sid = engine.session_mgr.create_session(user="thies").session_id
        active = engine.get_or_activate(sid)
        _seed(engine, sid, 2)
        history = engine.session_mgr.load_history(sid)
        history[1] = _compacted("anthropic")

        prepared = await engine.history_for_agent_model(active, history)

        assert not has_foreign_compaction(prepared, keep_provider=None)
        assert engine.session_mgr.load_history(sid) == prepared
        # The old measurement came from the compacted context: it must not trigger anything later.
        assert active.state.compacted_through == history[1].timestamp
        # Nothing foreign left: the next turn leaves the history alone.
        assert await engine.history_for_agent_model(active, prepared) is prepared

    asyncio.run(_run())


def test_a_turn_on_the_same_provider_keeps_its_compaction(tmp_path: Path, db_factory) -> None:
    async def _run() -> None:
        with _patch_sentinel():
            engine = _make_engine(tmp_path, session_factory=db_factory)  # agent model: Anthropic
        sid = engine.session_mgr.create_session(user="thies").session_id
        active = engine.get_or_activate(sid)
        history = [*_turn(0), ModelRequest(parts=[UserPromptPart("q")]), _compacted("anthropic")]

        assert engine.agent_provider_compaction(active) is not None
        assert await engine.history_for_agent_model(active, history) is history

    asyncio.run(_run())


def test_manual_compact_drops_provider_compaction_after_folding(tmp_path: Path, db_factory) -> None:
    async def _run() -> None:
        models = _AgentAndSummarizer()
        with _patch_sentinel():
            engine = _make_engine(tmp_path, session_factory=db_factory)
        engine._model_factory = models.factory
        sid = engine.session_mgr.create_session(user="thies").session_id
        active = engine.get_or_activate(sid)
        _seed(engine, sid, 10)
        history = engine.session_mgr.load_history(sid)
        history[-1] = _compacted("anthropic")  # inside the turns the fold keeps
        engine.session_mgr.save_history(sid, history)

        report = await engine.run_compaction(active, mode="fold", keep_turns=3)

        compacted = engine.session_mgr.load_history(sid)
        assert report.turns_folded == 7 and is_fold_message(compacted[0])
        assert not has_foreign_compaction(compacted, keep_provider=None)
        assert compacted[-1].parts == [TextPart("answer")]

    asyncio.run(_run())


def test_reports_count_only_what_is_sent_after_a_provider_compaction(tmp_path: Path, db_factory) -> None:
    async def _run() -> None:
        with _patch_sentinel():
            engine = _make_engine(tmp_path, session_factory=db_factory)
        sid = engine.session_mgr.create_session(user="thies").session_id
        active = engine.get_or_activate(sid)
        _seed(engine, sid, 10, tool_output="line\n" * 3000)
        full = await engine.run_compaction(active, mode="tools", verbatim_tool_turns=99)
        history = engine.session_mgr.load_history(sid)
        engine.session_mgr.save_history(sid, [*history, ModelRequest(parts=[UserPromptPart("q")]), _compacted("x")])

        after_provider = await engine.run_compaction(active, mode="tools", verbatim_tool_turns=99)

        assert after_provider.before_tokens < full.before_tokens / 10

    asyncio.run(_run())


def test_a_provider_compaction_is_marked_in_the_events() -> None:
    events: list[dict] = []
    marker = ProviderCompactionMarkerCapability(events.extend)

    async def _run() -> None:
        await marker.after_model_request(None, request_context=None, response=_compacted("anthropic"))  # type: ignore[arg-type]
        await marker.after_model_request(None, request_context=None, response=ModelResponse(parts=[TextPart("x")]))  # type: ignore[arg-type]

    asyncio.run(_run())
    assert events == [{"role": "compaction", "provider": "anthropic", "summary": "SUMMARY"}]
    assert HistoryMessage.model_validate(events[0]).summary == "SUMMARY"


def test_provider_compaction_tokens_count_under_compaction() -> None:
    usage = RunUsage(
        requests=1,
        input_tokens=1000,
        cache_read_tokens=300,
        cache_write_tokens=100,
        output_tokens=200,
        details={
            "compaction_iterations": 1,
            "compaction_input_tokens": 400,
            "compaction_cache_read_input_tokens": 100,
            "compaction_cache_creation_input_tokens": 50,
            "compaction_output_tokens": 80,
            "thinking_tokens": 7,
        },
    )

    own, compaction = split_provider_compaction_usage(usage)

    assert compaction == RunUsage(input_tokens=550, cache_read_tokens=100, cache_write_tokens=50, output_tokens=80)
    assert (own.input_tokens, own.cache_read_tokens, own.cache_write_tokens, own.output_tokens) == (450, 200, 50, 120)
    assert own.requests == 1 and own.details == {"thinking_tokens": 7}
    assert split_provider_compaction_usage(RunUsage(input_tokens=5)) == (RunUsage(input_tokens=5), None)
