"""The `revise` verdict: no threat, but the agent should change its approach."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, RetryPromptPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from carapace.security import evaluate_push_with, evaluate_with
from carapace.security.context import (
    SENTINEL_VERDICT_TOOL,
    ChangesRequestedError,
    GitPushEntry,
    SentinelVerdict,
    SessionSecurity,
    ToolCallEntry,
)
from carapace.security.sentinel import Sentinel

_REVISE = SentinelVerdict(decision="revise", explanation="Split the commit from the cleanup.", risk_level="low")


def _sentinel_returning(verdict: SentinelVerdict) -> MagicMock:
    sentinel = MagicMock(spec=Sentinel)
    sentinel.evaluate_tool_call = AsyncMock(return_value=verdict)
    sentinel.evaluate_push = AsyncMock(return_value=verdict)
    return sentinel


@pytest.mark.anyio
async def test_revised_tool_call_tells_the_agent_what_to_change() -> None:
    session = SessionSecurity("s")
    shown: list[tuple[Any, ...]] = []

    with pytest.raises(ChangesRequestedError) as raised:
        await evaluate_with(
            session,
            _sentinel_returning(_REVISE),
            "exec",
            {"command": "git push && rm -rf build"},
            tool_call_callback=lambda *args: shown.append(args),
        )

    assert str(raised.value) == "Sentinel requests changes (no threat detected): Split the commit from the cleanup."
    assert session.action_log[-1] == ToolCallEntry(
        tool="exec",
        args={"command": "git push && rm -rf build"},
        decision="changes_requested",
        explanation="Split the commit from the cleanup.",
    )
    _tool, _args, _detail, source, verdict, explanation = shown[-1]
    assert (source, verdict, explanation) == ("sentinel", "revise", "Split the commit from the cleanup.")


@pytest.mark.anyio
async def test_revised_push_is_rejected_with_the_change_request() -> None:
    session = SessionSecurity("s")

    evaluation = await evaluate_push_with(
        session, _sentinel_returning(_REVISE), "refs/heads/main", True, "abc fix", "diff", shared_artifacts=set()
    )

    assert evaluation.allowed is False
    assert evaluation.rejection == "Sentinel requests changes (no threat detected): Split the commit from the cleanup."
    assert session.action_log[-1] == GitPushEntry(
        ref="refs/heads/main", decision="changes_requested", explanation="Split the commit from the cleanup."
    )


def _sentinel(tmp_path: Path, decisions: list[str], *, unattended: bool = False) -> tuple[Sentinel, list[list]]:
    requests: list[list[ModelMessage]] = []

    def respond(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        requests.append(messages)
        decision = decisions.pop(0)
        return ModelResponse(parts=[ToolCallPart(SENTINEL_VERDICT_TOOL, {"decision": decision, "explanation": "x"})])

    (tmp_path / "skills").mkdir()
    sentinel = Sentinel(
        model="test:model",
        user="thies",
        knowledge_dir=tmp_path,
        skills_dir=tmp_path / "skills",
        llm_slots=None,
        unattended=unattended,
        model_factory=lambda _name, *, user: FunctionModel(respond),
    )
    return sentinel, requests


@pytest.mark.asyncio
async def test_sentinel_cannot_revise_requests_whose_explanation_never_reaches_the_agent(tmp_path: Path) -> None:
    sentinel, requests = _sentinel(tmp_path, ["revise", "deny"])

    verdict = await sentinel.evaluate_domain_access(SessionSecurity("s"), "example.com", "curl example.com")

    assert verdict.decision == "deny"
    retry = requests[1][-1].parts[0]
    assert isinstance(retry, RetryPromptPart)
    assert "`revise` is not available here" in retry.model_response()


@pytest.mark.asyncio
async def test_unattended_sentinel_can_revise_tool_calls(tmp_path: Path) -> None:
    sentinel, requests = _sentinel(tmp_path, ["revise"], unattended=True)

    verdict = await sentinel.evaluate_tool_call(SessionSecurity("s", unattended=True), "exec", {"command": "ls"})

    assert verdict.decision == "revise"
    assert len(requests) == 1
