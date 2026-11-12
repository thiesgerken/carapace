"""Server-side compaction on the Codex backend, through pydantic-ai's real `OpenAICodexModel` (#485)."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import httpx2
import pytest
from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import CompactionPart, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.openai_codex import OpenAICodexModel
from pydantic_ai.providers.openai_codex import OpenAICodexCredentials, OpenAICodexProvider
from pydantic_ai.usage import RequestUsage

from carapace.llm import ProviderCompactionRejectionCapability, provider_compaction
from carapace.models.config import AvailableModelEntry
from carapace.security.context import SessionSecurity
from carapace.security.sentinel import Sentinel
from carapace.session.compaction import is_fold_message
from tests.session_helpers import _make_engine, _patch_sentinel
from tests.test_compaction_engine import _AgentAndSummarizer, _seed

_ENTRY = AvailableModelEntry(provider="openai-codex", name="gpt-6.1-sol", compaction_threshold_tokens=90_000)


def _sse(*events: dict[str, Any]) -> bytes:
    return b"".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n".encode() for e in events)


def _response(output: list[dict[str, Any]], *, input_tokens: int) -> dict[str, Any]:
    return {
        "id": "resp_1",
        "object": "response",
        "created_at": 1,
        "model": "gpt-6.1-sol",
        "status": "completed",
        "output": output,
        "parallel_tool_calls": True,
        "tool_choice": "auto",
        "tools": [],
        "usage": {
            "input_tokens": input_tokens,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens": 5,
            "output_tokens_details": {"reasoning_tokens": 0},
            "total_tokens": input_tokens + 5,
        },
    }


def _turn_stream(text: str, *compactions: str, input_tokens: int) -> bytes:
    """A streamed response: the compaction items the backend emits (before and after the answer), then done."""
    message = {
        "type": "message",
        "id": "msg_1",
        "role": "assistant",
        "status": "completed",
        "content": [{"type": "output_text", "text": text, "annotations": []}],
    }
    items = [{"type": "compaction", "id": f"cmp_{c}", "encrypted_content": c} for c in compactions]
    # Probe D in #485: one compaction before the answer, a second one after it.
    output = [*items[:1], message, *items[1:]]
    events: list[dict[str, Any]] = [
        {"type": "response.created", "response": {**_response([], input_tokens=0), "status": "in_progress"}}
    ]
    for i, item in enumerate(output):
        if item["type"] == "message":
            # Text arrives as deltas; the finished item alone carries no new text for a stream.
            events += [
                {"type": "response.output_item.added", "output_index": i, "item": {**item, "content": []}},
                {
                    "type": "response.content_part.added",
                    "output_index": i,
                    "content_index": 0,
                    "item_id": item["id"],
                    "part": {"type": "output_text", "text": "", "annotations": []},
                },
                {
                    "type": "response.output_text.delta",
                    "output_index": i,
                    "content_index": 0,
                    "item_id": item["id"],
                    "delta": text,
                    "logprobs": [],
                },
            ]
        events.append({"type": "response.output_item.done", "output_index": i, "item": item})
    events.append({"type": "response.completed", "response": _response(output, input_tokens=input_tokens)})
    return _sse(*events)


async def test_codex_compacts_server_side_and_replays_the_newest_compaction() -> None:
    bodies: list[dict[str, Any]] = []
    streams = iter(
        [
            _turn_stream("first answer", "ENC-A", "ENC-B", input_tokens=95_000),
            _turn_stream("second answer", input_tokens=4_000),
        ]
    )

    def backend(request: httpx2.Request) -> httpx2.Response:
        bodies.append(json.loads(request.content))
        return httpx2.Response(200, content=next(streams), headers={"content-type": "text/event-stream"})

    provider = OpenAICodexProvider(
        credentials=OpenAICodexCredentials(access_token="token", refresh_token="refresh", account_id="acct"),
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(backend)),
    )
    compaction = provider_compaction(_ENTRY, instructions="unused")
    assert compaction is not None
    agent = Agent(OpenAICodexModel(_ENTRY.name, provider=provider), capabilities=[compaction.capability])

    first = await agent.run("long question")
    second = await agent.run("follow-up", message_history=first.all_messages())

    assert bodies[0]["context_management"] == [{"type": "compaction", "compact_threshold": 90_000}]
    assert bodies[0]["store"] is False
    parts = [p for m in first.all_messages() if isinstance(m, ModelResponse) for p in m.parts]
    compactions = [p for p in parts if isinstance(p, CompactionPart)]
    assert [p.provider_name for p in compactions] == ["openai-codex", "openai-codex"]
    # The newest compaction covers everything before it: only it and what follows go out again.
    replayed = bodies[1]["input"]
    assert replayed[0] == {"type": "compaction", "id": "cmp_ENC-B", "encrypted_content": "ENC-B"}
    assert "long question" not in json.dumps(replayed) and "follow-up" in json.dumps(replayed)
    assert second.output == "second answer"


# --- failures of the provider's compaction (Plan item 3 of #485) ---


def _measured(history: list[Any], input_tokens: int, *, compacted: bool, provider: str = "anthropic") -> list[Any]:
    """*history* whose last response, served by *provider*, reports *input_tokens*, with or without its compaction."""
    last = history[-1]
    parts = [CompactionPart(content=None, provider_name=provider), *last.parts] if compacted else last.parts
    measured = replace(last, parts=parts, usage=RequestUsage(input_tokens=input_tokens), provider_name=provider)
    return [*history[:-1], measured]


def _failed_compaction_events(engine: Any, sid: str) -> list[dict[str, Any]]:
    return [e for e in engine.session_mgr.load_events(sid) if e.get("role") == "compaction" and e.get("failed")]


def test_a_provider_that_skips_a_compaction_is_reported_and_compacted_locally(tmp_path: Path, db_factory) -> None:
    async def _run() -> None:
        models = _AgentAndSummarizer()
        with _patch_sentinel():
            engine = _make_engine(tmp_path, session_factory=db_factory)  # agent model: Anthropic, server-side
        engine._model_factory = models.factory
        engine._config.agent.compaction.keep_turns = 3
        sid = engine.session_mgr.create_session(user="thies").session_id
        active = engine.get_or_activate(sid)
        _seed(engine, sid, 10)
        history = _measured(engine.session_mgr.load_history(sid), 300_000, compacted=False)

        compacted = await engine.compact_after_provider_miss(active, history)

        assert compacted is not None and is_fold_message(compacted[0])
        [event] = _failed_compaction_events(engine, sid)
        assert (
            event["provider"] == "anthropic" and "did not compact a request of 300,000 input tokens" in event["failed"]
        )
        # Reported once: the measurement now predates the local compaction.
        assert await engine.compact_after_provider_miss(active, history) is None

    asyncio.run(_run())


@pytest.mark.parametrize(
    ("measured_tokens", "provider", "threshold"),
    [
        # Anthropic is asked to compact only from its 50k minimum on, whatever the model's threshold.
        (40_000, "anthropic", 30_000),
        # A measurement from before a switch to this model was never sent with its setting.
        (300_000, "openai", None),
    ],
)
def test_requests_the_provider_was_not_asked_to_compact_are_no_failure(
    tmp_path: Path, db_factory, measured_tokens: int, provider: str, threshold: int | None
) -> None:
    async def _run() -> None:
        with _patch_sentinel():
            engine = _make_engine(tmp_path, session_factory=db_factory)
        for entry in engine._config.agent.available_models:
            entry.compaction_threshold_tokens = threshold
        sid = engine.session_mgr.create_session(user="thies").session_id
        active = engine.get_or_activate(sid)
        _seed(engine, sid, 3)
        history = _measured(engine.session_mgr.load_history(sid), measured_tokens, compacted=False, provider=provider)

        assert await engine.compact_after_provider_miss(active, history) is None
        assert _failed_compaction_events(engine, sid) == []

    asyncio.run(_run())


def test_a_provider_that_compacted_is_left_alone(tmp_path: Path, db_factory) -> None:
    async def _run() -> None:
        with _patch_sentinel():
            engine = _make_engine(tmp_path, session_factory=db_factory)
        sid = engine.session_mgr.create_session(user="thies").session_id
        active = engine.get_or_activate(sid)
        _seed(engine, sid, 3)
        history = _measured(engine.session_mgr.load_history(sid), 300_000, compacted=True)

        assert await engine.compact_after_provider_miss(active, history) is None
        assert _failed_compaction_events(engine, sid) == []

    asyncio.run(_run())


def test_a_provider_rejecting_compaction_switches_the_model_to_local_compaction(tmp_path: Path, db_factory) -> None:
    with _patch_sentinel():
        engine = _make_engine(tmp_path, session_factory=db_factory)
    sid = engine.session_mgr.create_session(user="thies").session_id
    active = engine.get_or_activate(sid)
    model_id = engine.agent_model_id_for_gauge(active)

    engine.reject_provider_compaction(active, model_id, "Unknown parameter: 'context_management'")

    assert engine.agent_provider_compaction(active) is None
    [event] = _failed_compaction_events(engine, sid)
    assert "rejected compaction: Unknown parameter" in event["failed"] and event["rejected"] is True
    # A sentinel built before the first refusal hits it once more: that is reported too.
    engine.reject_provider_compaction(active, model_id, "again")
    assert len(_failed_compaction_events(engine, sid)) == 2


async def test_the_rejection_capability_reports_only_the_compaction_setting_and_reraises() -> None:
    rejected: list[str] = []
    capability = ProviderCompactionRejectionCapability(rejected.append)
    rejection = ModelHTTPError(400, "gpt", {"message": "Unknown parameter: 'context_management'"})
    other = ModelHTTPError(400, "gpt", {"message": "Invalid tool schema"})

    for error in (rejection, other):
        with pytest.raises(ModelHTTPError):
            await capability.on_model_request_error(MagicMock(), request_context=MagicMock(), error=error)

    assert len(rejected) == 1 and "context_management" in rejected[0]


def test_the_sentinel_compacts_locally_when_its_provider_skips_a_compaction(tmp_path: Path, db_factory) -> None:
    async def _run() -> None:
        models = _AgentAndSummarizer()
        with _patch_sentinel():
            engine = _make_engine(tmp_path, session_factory=db_factory)
        engine._model_factory = models.factory
        engine._config.agent.compaction.keep_turns = 3
        sid = engine.session_mgr.create_session(user="thies").session_id
        engine.get_or_activate(sid)
        _seed(engine, sid, 10)
        conversation = _measured(engine.session_mgr.load_history(sid), 300_000, compacted=False)

        compacted = await engine.compact_sentinel_conversation(sid, conversation, "SECURITY")

        assert compacted is not None and is_fold_message(compacted[0])
        [event] = _failed_compaction_events(engine, sid)
        assert event["failed"].startswith("sentinel model")
        # The same conversation with the provider's compaction in it needs nothing.
        assert (
            await engine.compact_sentinel_conversation(
                sid, _measured(conversation, 300_000, compacted=True), "SECURITY"
            )
            is None
        )

    asyncio.run(_run())


def test_a_codex_backend_that_ignores_context_management_is_caught(tmp_path: Path, db_factory) -> None:
    """The skip, end to end on the Codex path: a real `OpenAICodexModel` response over the threshold without a
    compaction item (the backend ignored the setting) makes carapace report it and compact locally."""

    def backend(request: httpx2.Request) -> httpx2.Response:
        stream = _turn_stream("answer", input_tokens=150_000)
        return httpx2.Response(200, content=stream, headers={"content-type": "text/event-stream"})

    async def _run() -> None:
        models = _AgentAndSummarizer()
        with _patch_sentinel():
            engine = _make_engine(tmp_path, session_factory=db_factory)
        engine._config.agent.available_models.append(_ENTRY)
        engine._config.agent.model = _ENTRY.model_id
        engine._model_factory = models.factory  # the compaction model
        engine._config.agent.compaction.keep_turns = 3
        sid = engine.session_mgr.create_session(user="thies").session_id
        active = engine.get_or_activate(sid)
        _seed(engine, sid, 10)
        compaction = engine.agent_provider_compaction(active)
        assert compaction is not None and compaction.provider_name == "openai-codex"
        provider = OpenAICodexProvider(
            credentials=OpenAICodexCredentials(access_token="token", refresh_token="refresh", account_id="acct"),
            http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(backend)),
        )
        agent = Agent(OpenAICodexModel(_ENTRY.name, provider=provider), capabilities=[compaction.capability])
        run = await agent.run("next question", message_history=engine.session_mgr.load_history(sid))

        compacted = await engine.compact_after_provider_miss(active, run.all_messages())

        assert compacted is not None and is_fold_message(compacted[0])
        [event] = _failed_compaction_events(engine, sid)
        assert event["provider"] == "openai-codex" and "150,000 input tokens" in event["failed"]
        assert "rejected" not in event

    asyncio.run(_run())


async def test_a_sentinel_whose_provider_rejects_compaction_evaluates_without_it_next_time(tmp_path: Path) -> None:
    rejected: set[str] = set()
    reports: list[str] = []
    settings_seen: list[bool] = []

    def judge(messages: list[Any], info: AgentInfo) -> ModelResponse:
        sends_setting = "openai_context_management" in (info.model_settings or {})
        settings_seen.append(sends_setting)
        if sends_setting:
            raise ModelHTTPError(400, _ENTRY.name, {"message": "Unknown parameter: 'context_management'"})
        verdict = {"decision": "allow", "explanation": "fine"}
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, verdict)])

    def on_rejected(model: str, reason: str) -> None:
        rejected.add(model)
        reports.append(reason)

    sentinel = Sentinel(
        model=_ENTRY.model_id,
        user="thies",
        knowledge_dir=tmp_path,
        skills_dir=tmp_path / "skills",
        llm_slots=None,
        model_factory=lambda _name, *, user: FunctionModel(judge),
        provider_compaction=lambda model: None if model in rejected else provider_compaction(_ENTRY, instructions=""),
        on_provider_compaction_rejected=on_rejected,
    )
    security = SessionSecurity("session-1")

    with pytest.raises(ModelHTTPError):
        await sentinel.evaluate_tool_call(security, "exec", {"command": "ls"})
    verdict = await sentinel.evaluate_tool_call(security, "exec", {"command": "pwd"})

    assert verdict.decision == "allow"
    assert settings_seen == [True, False] and len(reports) == 1
