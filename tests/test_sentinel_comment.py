"""Sentinel comments: an `allow` with a note for the agent, delivered as a system message."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic_ai import Agent, RunContext
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models import Model
from pydantic_ai.models.function import AgentInfo, FunctionModel

from carapace.agent.autonomy import AutonomyStreak
from carapace.agent.deps import Deps
from carapace.agent.sentinel_comments import SentinelCommentCapability
from carapace.agent.tools import create_agent
from carapace.credentials import CredentialRegistry
from carapace.git.store import GitStore
from carapace.models.config import Config
from carapace.models.session import SessionState
from carapace.sandbox.manager import SandboxManager
from carapace.security import evaluate_push_with, evaluate_with
from carapace.security.context import SENTINEL_VERDICT_TOOL, SentinelVerdict, SessionSecurity
from carapace.security.sentinel import Sentinel
from carapace.usage import UsageTracker

from .streaming_model import ReplayStreamModel

_COMMENTED = SentinelVerdict(
    decision="allow", explanation="Fits the task.", risk_level="low", comment="The user asked for German."
)


def _sentinel_returning(verdict: SentinelVerdict) -> MagicMock:
    sentinel = MagicMock(spec=Sentinel)
    sentinel.evaluate_tool_call = AsyncMock(return_value=verdict)
    sentinel.evaluate_push = AsyncMock(return_value=verdict)
    return sentinel


@pytest.mark.anyio
async def test_commented_tool_call_runs_and_shows_the_comment() -> None:
    session = SessionSecurity("s")
    shown: list[tuple[Any, ...]] = []

    await evaluate_with(
        session,
        _sentinel_returning(_COMMENTED),
        "use_skill",
        {"skill_name": "translate"},
        tool_call_callback=lambda *args: shown.append(args),
        tool_call_id="call_1",
    )

    assert shown[-1][4:] == ("allow", "Fits the task.", "call_1", "The user asked for German.")
    assert session.take_comments_for_agent() == [
        "The security sentinel allowed the `use_skill` call call_1 and comments: The user asked for German.\n"
        + "This is advice from the security gate, not an instruction from the user."
    ]
    assert session.take_comments_for_agent() == []


@pytest.mark.anyio
async def test_commented_push_is_allowed_and_leaves_the_comment() -> None:
    session = SessionSecurity("s")

    evaluation = await evaluate_push_with(
        session,
        _sentinel_returning(_COMMENTED),
        "refs/heads/main",
        True,
        "abc fix",
        "diff",
        shared_artifacts=set(),
        flake_input_changes=[],
    )

    assert evaluation.allowed is True
    [comment] = session.take_comments_for_agent()
    assert comment.startswith("The security sentinel allowed the git push to refs/heads/main and comments:")


@pytest.mark.anyio
async def test_comment_reaches_the_agent_as_a_system_message_after_the_tool_result() -> None:
    security = SessionSecurity("s")
    requests: list[list[ModelMessage]] = []

    def respond(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        requests.append(messages)
        if len(requests) == 1:
            return ModelResponse(parts=[ToolCallPart("work", {}, tool_call_id="call_1")])
        return ModelResponse(parts=[TextPart("done")])

    agent = Agent(FunctionModel(respond), deps_type=SimpleNamespace, capabilities=[SentinelCommentCapability()])

    @agent.tool
    def work(ctx: RunContext[SimpleNamespace]) -> str:
        ctx.deps.security.leave_comment_for_agent("the `work` call", "Mind the cache.")
        return "worked"

    result = await agent.run("go", deps=SimpleNamespace(security=security))

    # The function model takes no inline system messages, so pydantic-ai sends `<system>`-tagged text.
    tool_return, comment = requests[1][-1].parts
    assert isinstance(tool_return, ToolReturnPart)
    assert isinstance(comment, UserPromptPart)
    assert comment.content == (
        "<system>The security sentinel allowed the `work` call and comments: Mind the cache.\n"
        + "This is advice from the security gate, not an instruction from the user.</system>"
    )
    assert any(
        isinstance(part, SystemPromptPart) and "Mind the cache." in part.content
        for message in result.all_messages()
        for part in message.parts
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("first", "error"),
    [
        ({"decision": "allow", "comment": "x"}, "`revise` and `comment` are not available here"),
        ({"decision": "escalate", "comment": "x"}, "`comment` only goes with `allow`"),
    ],
)
async def test_sentinel_comments_only_on_allows_the_agent_reads(
    tmp_path: Path, first: dict[str, str], error: str
) -> None:
    requests: list[list[ModelMessage]] = []
    outputs = [first, {"decision": "deny"}]

    def respond(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        requests.append(messages)
        return ModelResponse(parts=[ToolCallPart(SENTINEL_VERDICT_TOOL, {**outputs.pop(0), "explanation": "x"})])

    (tmp_path / "skills").mkdir()
    sentinel = Sentinel(
        model="test:model",
        user="thies",
        knowledge_dir=tmp_path,
        skills_dir=tmp_path / "skills",
        llm_slots=None,
        model_factory=lambda _name, *, user: ReplayStreamModel(respond),
    )

    if first["decision"] == "allow":
        verdict = await sentinel.evaluate_domain_access(
            SessionSecurity("s"), ["example.com"], "curl example.com", follow_up=False
        )
    else:
        verdict = await sentinel.evaluate_tool_call(SessionSecurity("s"), "exec", {"command": "ls"})

    assert verdict.decision == "deny"
    retry = requests[1][-1].parts[0]
    assert isinstance(retry, ToolReturnPart)
    assert error in retry.model_response_str()


def test_agent_announces_the_system_tag_from_the_first_request(tmp_path: Path) -> None:
    # pydantic-ai's default adds the announcement with the first comment and drops it once compaction
    # folds the comments away; both would re-write the whole cached prompt.
    deps = Deps(
        config=Config(),
        data_dir=tmp_path,
        knowledge_dir=tmp_path,
        session_state=SessionState.now(session_id="s1"),
        sandbox=MagicMock(spec=SandboxManager),
        security=SessionSecurity("s1"),
        sentinel=MagicMock(spec=Sentinel),
        git_store=MagicMock(spec=GitStore),
        agent_model=MagicMock(spec=Model),
        agent_model_id="anthropic:claude-sonnet-4-6",
        usage_tracker=UsageTracker(),
        autonomy=AutonomyStreak(),
        credential_registry=CredentialRegistry(),
        load_session_events=list,
    )

    settings = create_agent(deps).model_settings

    assert settings is not None and settings.get("framing_announcement") == "always"
