"""The `allow_with_comment` verdict: the operation runs, and the agent gets the sentinel's advice."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart, ToolReturn, ToolReturnPart
from pydantic_ai.models.function import AgentInfo

from carapace.agent.sentinel_comments import with_sentinel_comment
from carapace.security import evaluate_push_with, evaluate_with
from carapace.security.context import (
    SENTINEL_VERDICT_TOOL,
    GitPushEntry,
    SentinelVerdict,
    SessionSecurity,
    ToolCallEntry,
)
from carapace.security.sentinel import Sentinel

from .streaming_model import ReplayStreamModel

_COMMENT = SentinelVerdict(decision="allow_with_comment", explanation="The user asked for German.", risk_level="low")


def _sentinel_returning(verdict: SentinelVerdict) -> MagicMock:
    sentinel = MagicMock(spec=Sentinel)
    sentinel.evaluate_tool_call = AsyncMock(return_value=verdict)
    sentinel.evaluate_push = AsyncMock(return_value=verdict)
    return sentinel


@pytest.mark.anyio
async def test_commented_tool_call_runs_and_returns_the_comment() -> None:
    session = SessionSecurity("s")

    comment = await evaluate_with(
        session, _sentinel_returning(_COMMENT), "exec", {"command": "echo hi"}, tool_call_id="call_1"
    )

    assert comment == "The user asked for German."
    assert session.action_log[-1] == ToolCallEntry(
        tool="exec", args={"command": "echo hi"}, decision="allowed", explanation="The user asked for German."
    )


@pytest.mark.anyio
async def test_plain_allow_has_no_comment() -> None:
    allow = SentinelVerdict(decision="allow", explanation="Fits the task.", risk_level="low")

    comment = await evaluate_with(
        SessionSecurity("s"), _sentinel_returning(allow), "exec", {"command": "echo hi"}, tool_call_id="call_1"
    )

    assert comment is None


@pytest.mark.anyio
async def test_commented_push_is_allowed_and_prints_the_comment() -> None:
    session = SessionSecurity("s")

    evaluation = await evaluate_push_with(
        session, _sentinel_returning(_COMMENT), "refs/heads/main", True, "abc fix", "diff", shared_artifacts=set()
    )

    assert evaluation.allowed is True
    assert evaluation.message == "[Sentinel allowed this operation with a comment: The user asked for German.]"
    assert session.action_log[-1] == GitPushEntry(
        ref="refs/heads/main", decision="allowed", explanation="The user asked for German."
    )


def test_comment_is_appended_to_text_and_image_results() -> None:
    assert with_sentinel_comment("out", "note") == "out\n\nnote"
    image = with_sentinel_comment(ToolReturn(return_value="Read image a.png", content=["x"]), "note")
    assert image == ToolReturn(return_value="Read image a.png\n\nnote", content=["x"])


@pytest.mark.asyncio
async def test_sentinel_cannot_comment_where_the_agent_never_reads_it(tmp_path: Path) -> None:
    requests: list[list[ModelMessage]] = []
    decisions = ["allow_with_comment", "allow"]

    def respond(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        requests.append(messages)
        return ModelResponse(
            parts=[ToolCallPart(SENTINEL_VERDICT_TOOL, {"decision": decisions.pop(0), "explanation": "x"})]
        )

    (tmp_path / "skills").mkdir()
    sentinel = Sentinel(
        model="test:model",
        user="thies",
        knowledge_dir=tmp_path,
        skills_dir=tmp_path / "skills",
        llm_slots=None,
        model_factory=lambda _name, *, user: ReplayStreamModel(respond),
    )

    verdict = await sentinel.evaluate_domain_access(SessionSecurity("s"), "example.com", "curl example.com")

    assert verdict.decision == "allow"
    retry = requests[1][-1].parts[0]
    assert isinstance(retry, ToolReturnPart)
    assert "`allow_with_comment` is not available here" in retry.model_response_str()
