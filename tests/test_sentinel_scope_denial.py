"""A push that bundles or broadens beyond the user's request is denied, with what would be acceptable."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo

from carapace.builder.skill_builds import SkillBuilds
from carapace.builder.skill_updates import no_fetch_credentials
from carapace.security import evaluate_push_with
from carapace.security.context import (
    SENTINEL_VERDICT_TOOL,
    GitPushEntry,
    SentinelVerdict,
    SessionSecurity,
)
from carapace.security.sentinel import Sentinel

from .streaming_model import ReplayStreamModel

_SPLIT = "The commit also rewrites skills/web/SKILL.md. Push the recipes fix on its own."


@pytest.mark.anyio
async def test_a_push_denied_for_its_scope_tells_the_agent_what_would_be_acceptable() -> None:
    session = SessionSecurity("s")
    sentinel = MagicMock(spec=Sentinel)
    sentinel.evaluate_push = AsyncMock(return_value=SentinelVerdict(decision="deny", explanation=_SPLIT))

    evaluation = await evaluate_push_with(
        session,
        sentinel,
        "refs/heads/main",
        True,
        "abc fix",
        "diff",
        shared_artifacts=set(),
        flake_input_changes=[],
    )

    assert evaluation.allowed is False
    assert evaluation.rejection == f"Sentinel denied this operation. {_SPLIT}"
    assert session.action_log[-1] == GitPushEntry(ref="refs/heads/main", decision="denied", explanation=_SPLIT)


@pytest.mark.asyncio
async def test_a_revise_verdict_is_no_longer_accepted(tmp_path: Path) -> None:
    requests: list[list[ModelMessage]] = []
    decisions = ["revise", "deny"]

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
        skill_builds=SkillBuilds(None, no_fetch_credentials),
        llm_slots=None,
        model_factory=lambda _name, *, user: ReplayStreamModel(respond),
    )

    verdict = await sentinel.evaluate_push(
        SessionSecurity("s"),
        "refs/heads/main",
        True,
        "abc fix",
        "diff",
        shared_artifacts=set(),
        flake_input_changes=[],
    )

    assert verdict.decision == "deny"
    retry = requests[1][-1].parts[0]
    assert isinstance(retry, ToolReturnPart)
    assert retry.outcome == "retried"
    assert "literal_error" in retry.model_response_str()
