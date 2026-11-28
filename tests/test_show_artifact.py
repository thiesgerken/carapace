from __future__ import annotations

import json
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
from carapace.builder.skill_builds import SkillBuilds
from carapace.builder.skill_updates import no_fetch_credentials
from carapace.credentials import CredentialRegistry
from carapace.git.store import GitStore
from carapace.models.config import Config
from carapace.models.session import SessionState
from carapace.sandbox.manager import SandboxManager
from carapace.security.context import SessionSecurity
from carapace.usage import UsageTracker


def _deps(tmp_path: Path) -> Deps:
    return Deps(
        skill_builds=SkillBuilds(None, no_fetch_credentials),
        config=Config(),
        data_dir=tmp_path / "data",
        knowledge_dir=tmp_path / "knowledge",
        session_state=SessionState.now(session_id="s1"),
        sandbox=MagicMock(spec=SandboxManager),
        security=SessionSecurity("s1"),
        git_store=MagicMock(spec=GitStore),
        agent_model=MagicMock(spec=Model),
        agent_model_id="anthropic:claude-sonnet-4-6",
        usage_tracker=UsageTracker(),
        autonomy=AutonomyStreak(),
        credential_registry=CredentialRegistry(),
        load_session_events=lambda: [],
    )


async def _call(deps: Deps, tool_name: str, arg: str) -> Any:
    tool = create_agent(deps)._function_toolset.tools[tool_name]
    ctx = RunContext(deps=deps, model=MagicMock(spec=Model), usage=RunUsage())
    return await tool.function(ctx, arg)


@pytest.mark.anyio
async def test_show_artifact_references_a_pushed_artifact(tmp_path: Path) -> None:
    deps = _deps(tmp_path)
    index = deps.knowledge_dir / "artifacts" / "report" / "index.html"
    index.parent.mkdir(parents=True)
    index.write_text("<head><title> Quarterly\n report </title></head>")

    assert json.loads(await _call(deps, "show_artifact", "report")) == {"slug": "report", "title": "Quarterly report"}
    assert not deps.sandbox.mock_calls


@pytest.mark.anyio
@pytest.mark.parametrize("slug", ["unpushed", "..", "a/b"])
async def test_show_artifact_requires_the_artifact_on_the_server(tmp_path: Path, slug: str) -> None:
    deps = _deps(tmp_path)
    (deps.knowledge_dir / "artifacts").mkdir(parents=True)

    result = await _call(deps, "show_artifact", slug)

    assert result.startswith(f"Error: the server has no artifact {slug!r}. Commit and push")


@pytest.mark.anyio
@pytest.mark.parametrize(
    "path",
    [
        "/workspace/artifacts/report/index.html",
        "artifacts/report/chart.svg",
        "/workspace/x/../artifacts/report/index.html",
    ],
)
async def test_send_file_points_artifacts_to_show_artifact(tmp_path: Path, path: str) -> None:
    deps = _deps(tmp_path)

    result = await _call(deps, "send_file", path)

    assert "show_artifact('report')" in result
    assert not deps.sandbox.mock_calls


@pytest.mark.anyio
async def test_send_file_still_sends_files_directly_under_artifacts(tmp_path: Path) -> None:
    deps = _deps(tmp_path)
    deps.sandbox.download_tmp_file.side_effect = RuntimeError("sandbox reached")

    result = await _call(deps, "send_file", "/workspace/artifacts/README.md")

    assert result == "Error: sandbox reached"
