from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai.models import Model
from pydantic_ai.usage import RunUsage

from carapace.agent.loop import run_agent_turn
from carapace.credentials import CredentialRegistry
from carapace.git.store import GitStore
from carapace.models import Config, Deps, SessionState, TaskDone, TaskFailed
from carapace.sandbox.manager import SandboxManager
from carapace.security.context import AgentResponseEntry, SessionSecurity
from carapace.security.sentinel import Sentinel
from carapace.usage import UsageTracker


class _FakeResult:
    def __init__(self, output: Any) -> None:
        self.output = output

    def usage(self) -> RunUsage:
        return RunUsage(input_tokens=3, output_tokens=5)

    def all_messages(self) -> list[Any]:
        return []


def _make_deps(tmp_path: Path, *, unattended: bool) -> Deps:
    session_id = "session-1"
    return Deps(
        config=Config(),
        data_dir=tmp_path,
        knowledge_dir=tmp_path,
        session_state=SessionState.now(session_id=session_id, unattended=unattended),
        sandbox=MagicMock(spec=SandboxManager),
        security=SessionSecurity(session_id, unattended=unattended),
        sentinel=MagicMock(spec=Sentinel),
        git_store=MagicMock(spec=GitStore),
        agent_model=MagicMock(spec=Model),
        agent_model_id="anthropic:claude-sonnet-4-6",
        usage_tracker=UsageTracker(),
        credential_registry=CredentialRegistry(),
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("output", "expected_text", "expected_status"),
    [
        (TaskDone(result="completed"), "completed", "success"),
        (TaskFailed(problem="blocked by missing credential"), "blocked by missing credential", "warning"),
    ],
)
async def test_run_agent_turn_decodes_unattended_structured_outputs(
    tmp_path: Path,
    output: TaskDone | TaskFailed,
    expected_text: str,
    expected_status: str,
) -> None:
    deps = _make_deps(tmp_path, unattended=True)
    fake_agent = MagicMock()
    fake_agent.run = AsyncMock(return_value=_FakeResult(output))

    async def _send_approval_request(_req: Any) -> None:
        raise AssertionError("approval loop should not run")

    async def _collect_approvals(_pending: set[str]) -> dict[str, bool]:
        raise AssertionError("approval loop should not run")

    with patch("carapace.agent.loop.create_agent", return_value=fake_agent):
        messages, output_text, thinking, final_status = await run_agent_turn(
            "finish the task",
            deps,
            [],
            _send_approval_request,
            _collect_approvals,
        )

    assert messages == []
    assert output_text == expected_text
    assert thinking == ""
    assert final_status == expected_status
    assert isinstance(deps.security.action_log[-1], AgentResponseEntry)
