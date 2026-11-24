"""Every exec starts by killing the processes earlier calls left behind in the sandbox."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic_ai import RunContext
from pydantic_ai.models import Model
from pydantic_ai.usage import RunUsage

from carapace.agent.autonomy import AutonomyStreak
from carapace.agent.deps import Deps
from carapace.agent.tools import create_agent
from carapace.builder.skill_builds import SkillBuilds
from carapace.credentials import CredentialRegistry
from carapace.git.store import GitStore
from carapace.knowledge import KnowledgeRepoHandle
from carapace.models.config import Config
from carapace.models.session import SessionState
from carapace.sandbox.exec_flow import KILL_LEFTOVER_PROCESSES_COMMAND
from carapace.sandbox.manager import SandboxManager
from carapace.sandbox.runtime import ExecResult
from carapace.security.context import SessionSecurity
from carapace.session.manager import SessionManager, SessionMeta
from carapace.skills import SkillRegistry
from carapace.usage import UsageTracker
from tests.runtime_mocks import make_runtime_mock


class _ProcessTable:
    """Stands in for the sandbox: a command ending in ``&`` leaves its process running."""

    def __init__(self) -> None:
        self.running: list[str] = []
        self.running_when_started: dict[str, list[str]] = {}

    async def exec(self, _container_id: str, command: str | list[str], *_args: object, **_kwargs: object) -> ExecResult:
        if command == KILL_LEFTOVER_PROCESSES_COMMAND:
            killed, self.running = len(self.running), []
            return ExecResult(stdout=f"{killed}\n", exit_code=0, output=f"{killed}\n")
        assert isinstance(command, str)
        self.running_when_started[command] = list(self.running)
        if command.endswith("&"):
            self.running.append(command)
        return ExecResult(stdout="", exit_code=0, output="")


def _deps(tmp_path: Path, db_factory, processes: _ProcessTable) -> Deps:
    SessionManager(db_factory, tmp_path).save_meta("s1", SessionMeta(user="thies"))
    runtime = make_runtime_mock()
    runtime.logs = AsyncMock(return_value="carapace sandbox ready")
    runtime.exec = AsyncMock(side_effect=processes.exec)
    handle = KnowledgeRepoHandle(
        owner="thies",
        knowledge_dir=tmp_path,
        git_store=GitStore(tmp_path),
        skill_registry=SkillRegistry(tmp_path / "skills"),
    )
    sandbox = SandboxManager(
        runtime=runtime,
        data_dir=tmp_path,
        knowledge_repo_for_session=lambda _session_id: handle,
        session_factory=db_factory,
    )
    return Deps(
        skill_builds=SkillBuilds(None),
        config=Config.model_validate({}),
        data_dir=tmp_path,
        knowledge_dir=tmp_path,
        session_state=SessionState.now(session_id="s1", unattended=False),
        sandbox=sandbox,
        security=SessionSecurity("s1", unattended=False),
        git_store=MagicMock(spec=GitStore),
        agent_model=MagicMock(spec=Model),
        agent_model_id="anthropic:claude-sonnet-4-6",
        usage_tracker=UsageTracker(),
        autonomy=AutonomyStreak(),
        credential_registry=CredentialRegistry(),
        load_session_events=list,
    )


@pytest.mark.asyncio
async def test_a_background_process_from_one_exec_is_gone_when_the_next_starts(tmp_path: Path, db_factory) -> None:
    processes = _ProcessTable()
    deps = _deps(tmp_path, db_factory, processes)
    exec_tool = create_agent(deps)._function_toolset.tools["exec"]
    ctx = RunContext(deps=deps, model=MagicMock(spec=Model), usage=RunUsage(), tool_call_approved=True)

    first = await exec_tool.function(ctx, command="nohup ./serve.sh &")
    second = await exec_tool.function(ctx, command="curl localhost:8000")

    assert processes.running_when_started["curl localhost:8000"] == []
    assert "leftover" not in first
    assert second.endswith("Killed 1 leftover process(es) from earlier commands.")
