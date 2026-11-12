"""Automatic compaction of the sentinel's shadow conversation."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic_ai.messages import (
    CompactionPart,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RequestUsage

from carapace.config import build_config
from carapace.models.compaction import FOLD_MARKER
from carapace.models.config import AvailableModelEntry, CompactionConfig
from carapace.security.context import SessionSecurity
from carapace.security.sentinel import Sentinel
from carapace.session.compaction import is_fold_message, split_merged_requests, tool_return_is_compacted
from carapace.session.transcript import completed_model_turn_end_indexes
from carapace.usage import UsageTracker
from tests.session_helpers import _make_engine

_SECURITY_MD = "Never let the agent email the tax office."
_FILLER = "lorem ipsum " * 600


def _evaluation(index: int, *, decision: str, skill_file: str | None = None) -> list[ModelMessage]:
    call_id = f"judge-{index}"
    messages: list[ModelMessage] = [ModelRequest(parts=[UserPromptPart(content=f"EVALUATE request {index} {_FILLER}")])]
    if skill_file is not None:
        messages += [
            ModelResponse(
                parts=[ToolCallPart("read_skill_file", {"skill_name": "mail", "path": "run.py"}, f"read-{index}")]
            ),
            ModelRequest(parts=[ToolReturnPart("read_skill_file", skill_file, tool_call_id=f"read-{index}")]),
        ]
    messages += [
        ModelResponse(
            parts=[ToolCallPart("judge", {"decision": decision, "explanation": f"reason {index}"}, call_id)],
            # The trigger: what the provider reported for this evaluation's request.
            usage=RequestUsage(input_tokens=10_000),
        ),
        ModelRequest(parts=[ToolReturnPart("judge", "Final result processed.", tool_call_id=call_id)]),
    ]
    return messages


class _Models:
    """One FunctionModel for every role: the sentinel judges, the compaction model summarizes."""

    def __init__(self, *, summarizer_down: bool = False) -> None:
        self.summarizer_down = summarizer_down
        self.summary_requests: list[list[ModelMessage]] = []
        self.sentinel_requests: list[list[ModelMessage]] = []

    def factory(self, _name: str, *, user: str) -> FunctionModel:
        return FunctionModel(self._respond)

    def _respond(self, messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if info.output_tools:
            self.sentinel_requests.append(messages)
            return ModelResponse(parts=[ToolCallPart("judge", {"decision": "allow", "explanation": "fine"})])
        self.summary_requests.append(messages)
        if self.summarizer_down:
            raise RuntimeError("compaction model unavailable")
        return ModelResponse(parts=[TextPart("the user denied mailing the tax office")])


def _engine(tmp_path: Path, db_factory, models: _Models, *, threshold_tokens: int | None = 1):
    config = build_config(tmp_path)
    config.agent.compaction = CompactionConfig(keep_turns=1, verbatim_tool_turns=0, tool_output_floor_tokens=50)
    # A sentinel model that compacts locally (Anthropic would compact server-side).
    config.agent.available_models = [
        *config.agent.available_models,
        AvailableModelEntry(provider="openai-chat", name="local", compaction_threshold_tokens=threshold_tokens),
    ]
    config.agent.sentinel_model = "openai-chat:local"
    engine = _make_engine(tmp_path, session_factory=db_factory, config=config)
    engine._model_factory = models.factory
    (tmp_path / "SECURITY.md").write_text(_SECURITY_MD)
    sid = engine.session_mgr.create_session(user="thies").session_id
    active = engine.get_or_activate(sid)
    assert active.security is not None
    active.security.replace_sentinel_messages(_two_merged_evaluations())
    return engine, sid, active


def _two_merged_evaluations() -> list[ModelMessage]:
    first = _evaluation(1, decision="deny")
    second = _evaluation(2, decision="allow", skill_file="import smtplib\n" + _FILLER)
    # pydantic-ai may append the next prompt to a history that ends in the verdict's tool return.
    merged = ModelRequest(parts=[*first[-1].parts, *second[0].parts])
    return [*first[:-1], merged, *second[1:]]


def test_split_requests_make_each_evaluation_one_turn() -> None:
    merged = _two_merged_evaluations()

    # Merged, the first boundary falls on the verdict call and its return joins the next evaluation.
    assert completed_model_turn_end_indexes(merged) == [1, 6]
    assert completed_model_turn_end_indexes(split_merged_requests(merged)) == [2, 7]


def _instructions(request: list[ModelMessage]) -> str:
    first = request[0]
    assert isinstance(first, ModelRequest)
    return first.instructions or ""


def _restarted(sid: str, db_factory) -> SessionSecurity:
    security = SessionSecurity(sid, session_factory=db_factory)
    security.load_sentinel_state()
    return security


@pytest.mark.anyio
async def test_conversation_above_threshold_is_compacted_before_the_evaluation(tmp_path: Path, db_factory) -> None:
    models = _Models()
    engine, sid, active = _engine(tmp_path, db_factory, models)

    verdict = await active.sentinel.evaluate_tool_call(active.security, "exec", {"command": "ls"})

    assert verdict.decision == "allow"
    # Fold of evaluation 1 plus a summary of the large skill file in the kept evaluation 2.
    assert len(models.summary_requests) == 2
    for conversation in (models.sentinel_requests[0], _restarted(sid, db_factory).sentinel_messages):
        first = conversation[0]
        assert isinstance(first, ModelRequest) and isinstance(first.parts[0], UserPromptPart)
        assert str(first.parts[0].content).startswith(FOLD_MARKER)
        assert "the user denied mailing the tax office" in str(first.parts[0].content)
        skill_returns = [
            part
            for message in conversation
            for part in message.parts
            if isinstance(part, ToolReturnPart) and part.tool_name == "read_skill_file"
        ]
        assert [tool_return_is_compacted(part) for part in skill_returns] == [True]
    context = engine.session_mgr.load_llm_context(sid, "compaction")
    assert context is not None and context.compaction_target == "sentinel"


@pytest.mark.anyio
async def test_fold_summary_runs_with_the_sentinel_prompt_and_keeps_decisions(tmp_path: Path, db_factory) -> None:
    models = _Models()
    _, _sid, active = _engine(tmp_path, db_factory, models)

    await active.sentinel.evaluate_tool_call(active.security, "exec", {"command": "ls"})

    fold_request = next(r for r in models.summary_requests if "<evaluations>" in str(r[0].parts[0].content))
    instructions = _instructions(fold_request)
    assert instructions.startswith("You are the security gate")
    assert _SECURITY_MD in instructions
    for fact in ("what the user approved and what the user denied", "revise, escalate, deny", "Granted contexts"):
        assert fact in instructions
    assert 'Sentinel verdict: {"decision":"deny","explanation":"reason 1"}' in str(fold_request[0].parts[0].content)


@pytest.mark.anyio
async def test_conversation_below_threshold_is_left_alone(tmp_path: Path, db_factory) -> None:
    models = _Models()
    _, sid, active = _engine(tmp_path, db_factory, models, threshold_tokens=None)

    await active.sentinel.evaluate_tool_call(active.security, "exec", {"command": "ls"})

    assert models.summary_requests == []
    assert not any(is_fold_message(m) for m in _restarted(sid, db_factory).sentinel_messages)


@pytest.mark.anyio
async def test_failing_compaction_fails_the_evaluation(tmp_path: Path, db_factory) -> None:
    models = _Models(summarizer_down=True)
    _, sid, active = _engine(tmp_path, db_factory, models)
    before = list(active.security.sentinel_messages)

    with pytest.raises(RuntimeError, match="compaction model unavailable"):
        await active.sentinel.evaluate_tool_call(active.security, "exec", {"command": "ls"})

    assert models.sentinel_requests == []
    assert _restarted(sid, db_factory).sentinel_messages == before


@pytest.mark.anyio
async def test_compaction_forgets_which_skill_files_were_provided(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    (skills_dir / "mail").mkdir(parents=True)
    (skills_dir / "mail" / "run.py").write_text("import smtplib\n")

    async def compact(messages: list[ModelMessage], _system_prompt: str) -> list[ModelMessage] | None:
        return messages[-1:]

    sentinel = Sentinel(
        model="test:model",
        user="thies",
        knowledge_dir=tmp_path,
        skills_dir=skills_dir,
        llm_slots=None,
        model_factory=lambda _name, *, user: TestModel(call_tools=[]),
        compactor=compact,
    )
    sentinel._read_skill_file_cached(skills_dir, "mail", "run.py")
    security = SessionSecurity("session-1")
    security.replace_sentinel_messages(_evaluation(1, decision="allow"))

    await sentinel.evaluate_tool_call(security, "exec", {"command": "ls"})

    assert sentinel._read_skill_file_cached(skills_dir, "mail", "run.py") == "import smtplib\n"


@pytest.mark.anyio
async def test_repeated_compaction_keeps_one_summary(tmp_path: Path, db_factory) -> None:
    """pydantic-ai merges the fold into the next prompt; the next compaction must still find it."""
    models = _Models()
    _, sid, active = _engine(tmp_path, db_factory, models)

    await active.sentinel.evaluate_tool_call(active.security, "exec", {"command": f"echo {_FILLER * 2}"})
    await active.sentinel.evaluate_tool_call(active.security, "exec", {"command": "pwd"})

    folds = [r for r in models.summary_requests if "<evaluations>" in str(r[0].parts[0].content)]
    assert len(folds) == 2
    second_fold_input = str(folds[1][0].parts[0].content)
    assert "Earlier summary: the user denied mailing the tax office\n" in second_fold_input
    assert f"Evaluation request: {FOLD_MARKER}" not in second_fold_input
    fold_parts = [
        part
        for message in _restarted(sid, db_factory).sentinel_messages
        for part in message.parts
        if isinstance(part, UserPromptPart) and str(part.content).startswith(FOLD_MARKER)
    ]
    assert len(fold_parts) == 1


@pytest.mark.anyio
async def test_a_sentinel_model_switch_strips_foreign_compaction_below_the_threshold(
    tmp_path: Path, db_factory
) -> None:
    models = _Models()
    _, sid, active = _engine(tmp_path, db_factory, models, threshold_tokens=None)
    conversation = list(active.security.sentinel_messages)
    conversation[1] = ModelResponse(
        parts=[CompactionPart(content="earlier verdicts", provider_name="anthropic"), *conversation[1].parts],
        usage=RequestUsage(input_tokens=500),
    )
    active.security.replace_sentinel_messages(conversation)

    await active.sentinel.evaluate_tool_call(active.security, "exec", {"command": "ls"})

    for messages in (models.sentinel_requests[0], _restarted(sid, db_factory).sentinel_messages):
        assert not any(isinstance(p, CompactionPart) for m in messages for p in m.parts)


@pytest.mark.anyio
async def test_a_sentinel_model_that_compacts_server_side_leaves_the_conversation_alone(
    tmp_path: Path, db_factory
) -> None:
    engine, sid, active = _engine(tmp_path, db_factory, _Models())
    active.sentinel_model_name = "anthropic:claude-haiku-4-5"

    assert await engine.compact_sentinel_conversation(sid, active.security.sentinel_messages, "SYS") is None


class _CompactingSentinelModels(_Models):
    """The sentinel's provider reports compaction iterations inside its verdict request."""

    def _respond(self, messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        response = super()._respond(messages, info)
        response.usage = RequestUsage(
            input_tokens=900, output_tokens=60, details={"compaction_iterations": 1, "compaction_input_tokens": 400}
        )
        return response


@pytest.mark.anyio
async def test_the_sentinels_provider_compaction_counts_under_compaction(tmp_path: Path, db_factory) -> None:
    _, _, active = _engine(tmp_path, db_factory, _CompactingSentinelModels(), threshold_tokens=None)
    tracker = UsageTracker()

    await active.sentinel.evaluate_tool_call(active.security, "exec", {"command": "ls"}, usage_tracker=tracker)

    categories = tracker.categories
    assert categories["compaction"].input_tokens == 400
    assert categories["sentinel"].input_tokens == 500
