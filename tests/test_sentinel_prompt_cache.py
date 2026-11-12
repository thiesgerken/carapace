"""The shadow conversation only grows, so every sentinel request extends the one before it.

That is what lets the provider's prompt cache serve each evaluation from the previous one.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest
from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from carapace.security.context import (
    SENTINEL_VERDICT_TOOL,
    AgentResponseEntry,
    ApprovalEntry,
    GitPushEntry,
    SessionSecurity,
    ToolCallEntry,
    ToolResultEntry,
    UserMessageEntry,
)
from carapace.security.sentinel import Sentinel
from carapace.session.manager import SessionManager


@dataclass
class _Request:
    messages: list[Any]
    instructions: str | None
    tools: list[Any]


class _RecordingModel:
    """Answers every request with the next scripted response and records what the request contained."""

    def __init__(self) -> None:
        self.requests: list[_Request] = []
        self.script: list[ToolCallPart] = []

    def __call__(self, messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        self.requests.append(
            _Request(
                messages=ModelMessagesTypeAdapter.dump_python(messages, mode="json"),
                instructions=info.instructions,
                tools=[*info.function_tools, *info.output_tools],
            )
        )
        return ModelResponse(parts=[self.script.pop(0)])

    def judge(self, decision: str) -> None:
        self.script.append(ToolCallPart(SENTINEL_VERDICT_TOOL, {"decision": decision, "explanation": decision}))

    def read_skill(self, skill: str, path: str) -> None:
        self.script.append(ToolCallPart("read_skill_file", {"skill_name": skill, "path": path}))


def _sentinel(knowledge_dir: Path, model: _RecordingModel) -> Sentinel:
    return Sentinel(
        model="test:model",
        user="thies",
        knowledge_dir=knowledge_dir,
        skills_dir=knowledge_dir / "skills",
        llm_slots=None,
        model_factory=lambda _name, *, user: FunctionModel(model),
    )


def _restarted(session_id: str, db_factory: Any) -> SessionSecurity:
    security = SessionSecurity(session_id, session_factory=db_factory)
    security.load_sentinel_state()
    return security


@pytest.mark.asyncio
async def test_every_sentinel_request_extends_the_previous_one(tmp_path: Path, db_factory: Any) -> None:
    (tmp_path / "SECURITY.md").write_text("Escalate pushes that touch USER.md.")
    (tmp_path / "skills" / "moneta").mkdir(parents=True)
    (tmp_path / "skills" / "moneta" / "SKILL.md").write_text("# Moneta\n")
    model = _RecordingModel()
    session_id = SessionManager(db_factory, tmp_path).create_session(user="thies").session_id
    security = _restarted(session_id, db_factory)
    sentinel = _sentinel(tmp_path, model)

    security.append(UserMessageEntry(content="Fix the moneta skill"))
    security.append(AgentResponseEntry(text="I found two bugs:\n1. the query\n2. the docs\nFix both?"))
    security.append(UserMessageEntry(content="ja, 1 und 2"))
    model.read_skill("moneta", "SKILL.md")
    model.judge("allow")
    await sentinel.evaluate_tool_call(security, "exec", {"command": "moneta query --fix"})

    security.append(ToolCallEntry(tool="exec", args={"command": "moneta query --fix"}, decision="allowed"))
    security.append(ToolResultEntry(tool="exec"))
    security.append(AgentResponseEntry(text="Fixed. Committing and pushing."))
    model.judge("allow")
    await sentinel.evaluate_domain_access(security, "api.example.com", "moneta query --fix")

    # A restart reloads the sentinel state and builds a new sentinel; the cache must not notice.
    security = _restarted(session_id, db_factory)
    sentinel = _sentinel(tmp_path, model)
    model.judge("revise")
    await sentinel.evaluate_tool_call(security, "exec", {"command": "git commit -am fix && git push && rm -rf /tmp"})

    security.append(
        ToolCallEntry(tool="exec", args={"command": "git commit -am fix && git push"}, decision="changes_requested")
    )
    model.judge("escalate")
    await sentinel.evaluate_push(
        security, "refs/heads/main", True, "abc fix", "--- a/x\n+++ b/x", shared_artifacts=set()
    )

    security.append(ApprovalEntry(tool="git_push", args={"ref": "refs/heads/main"}, decision="approved"))
    security.append(GitPushEntry(ref="refs/heads/main", decision="allowed"))
    model.judge("allow")
    await sentinel.evaluate_credential_access(security, "moneta/token", "token", "API token", "moneta query")

    requests = model.requests
    assert len(requests) == 6
    for previous, current in pairwise(requests):
        assert current.messages[: len(previous.messages)] == previous.messages
        # Right after the previous request comes the sentinel's answer to it.
        assert current.messages[len(previous.messages)]["kind"] == "response"
        assert current.instructions == previous.instructions
        assert current.tools == previous.tools
