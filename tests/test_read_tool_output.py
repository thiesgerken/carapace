from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic_ai import RunContext
from pydantic_ai.models import Model
from pydantic_ai.usage import RunUsage

from carapace.agent.autonomy import AutonomyStreak
from carapace.agent.deps import Deps
from carapace.agent.tools import create_agent
from carapace.credentials import CredentialRegistry
from carapace.git.store import GitStore
from carapace.models.config import Config
from carapace.models.session import SessionState
from carapace.sandbox.manager import SandboxManager
from carapace.security.context import SessionSecurity
from carapace.security.sentinel import Sentinel
from carapace.usage import UsageTracker

_EVENTS: list[dict[str, Any]] = [
    {"role": "tool_call", "tool": "exec", "tool_id": "uuid-1"},
    {"role": "tool_result", "tool": "exec", "result": "pod-a Running\npod-b Running", "model_tool_call_id": "call-1"},
    {"role": "tool_result", "tool": "read", "result": "other", "model_tool_call_id": "call-2"},
]


def _deps(tmp_path: Path) -> Deps:
    return Deps(
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
        load_session_events=lambda: _EVENTS,
    )


async def _call(deps: Deps, tool_call_id: str) -> Any:
    tool = create_agent(deps)._function_toolset.tools["read_tool_output"]
    ctx = RunContext(deps=deps, model=MagicMock(spec=Model), usage=RunUsage())
    return await tool.function(ctx, tool_call_id)


@pytest.mark.anyio
async def test_returns_the_original_output_without_asking_the_sentinel(tmp_path: Path) -> None:
    deps = _deps(tmp_path)

    assert await _call(deps, "call-1") == "pod-a Running\npod-b Running"
    assert not deps.sentinel.mock_calls


@pytest.mark.anyio
async def test_unknown_id_is_an_error(tmp_path: Path) -> None:
    assert await _call(_deps(tmp_path), "call-9") == "Error: no tool call 'call-9' in this session."
