"""read_skill: the skill's text and files from its build, its commands with their declarations, and whether
they are on PATH."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic_ai import RunContext
from pydantic_ai.models import Model
from pydantic_ai.usage import RunUsage

from carapace.agent.autonomy import AutonomyStreak
from carapace.agent.deps import Deps
from carapace.agent.tools import create_agent
from carapace.builder.skill_builds import BuildState, SkillBuild, SkillBuilds, SkillCommand, SkillNeeds
from carapace.builder.skill_updates import SkillUpdate, UpdateCheck
from carapace.credentials import CredentialRegistry
from carapace.git.store import GitStore
from carapace.models.config import Config
from carapace.models.session import SessionState
from carapace.sandbox.manager import SandboxLimitError, SandboxManager
from carapace.sandbox.runtime import ExecResult
from carapace.security.context import SessionSecurity, ToolCallEntry
from carapace.usage import UsageTracker
from tests.skills_flake import write_skills_flake

_WEATHER = SkillCommand(
    description="Current weather.",
    needs=SkillNeeds(
        domains=["api.example.com"], credentials={"WEATHER_TOKEN": "demo/weather-token"}, tunnels=[], oauth=[]
    ),
)
_PLAIN = SkillCommand(description="Offline forecast.", needs=SkillNeeds(domains=[], credentials={}, tunnels=[]))
_TRACKER = SkillCommand(
    description="Issues in the example tracker.",
    needs=SkillNeeds(domains=["mcp.example.com"], credentials={}, tunnels=[], oauth=["demo/tracker-oauth"]),
    mcp=True,
)
_TOOLS = "search\tFind issues by text\ncreate\tOpen an issue\n"


_SKILL_DIR = f"/nix/store/{'b' * 32}-skill-demo-src"


def _build(
    skill: str, state: BuildState, frontmatter: str = "", files: tuple[str, ...] = (), **commands: SkillCommand
) -> SkillBuild:
    return SkillBuild(
        skill=skill,
        key=skill[0] * 64,
        state=state,
        store_paths=[f"/nix/store/{'a' * 32}-{skill}"] if state == "succeeded" else [],
        commands=dict(commands),
        detail="error: attribute 'packages' missing" if state == "failed" else "",
        skill_dir=_SKILL_DIR,
        skill_md=f"---\nname: {skill}\ndescription: demo\n{frontmatter}---\nUse it well.\n",
        skill_files=["SKILL.md", *files],
    )


def _deps(tmp_path: Path, builds: list[SkillBuild]) -> Deps:
    skill_builds = MagicMock(spec=SkillBuilds)

    async def wait_built(_repo_dir: Path, skill: str) -> tuple[SkillBuild | None, list[SkillBuild]]:
        return next((build for build in builds if build.skill == skill), None), builds

    skill_builds.wait_built = AsyncMock(side_effect=wait_built)
    sandbox = MagicMock(spec=SandboxManager)
    sandbox.sync_skill_profile = AsyncMock(return_value=None)
    sandbox.exec_command = AsyncMock(return_value=ExecResult(stdout=_TOOLS, exit_code=0, output=_TOOLS))
    return Deps(
        config=Config(),
        data_dir=tmp_path,
        knowledge_dir=tmp_path,
        session_state=SessionState.now(session_id="s1"),
        sandbox=sandbox,
        security=SessionSecurity("s1"),
        git_store=MagicMock(spec=GitStore),
        skill_builds=skill_builds,
        agent_model=MagicMock(spec=Model),
        agent_model_id=Config().agent.model,
        usage_tracker=UsageTracker(),
        autonomy=AutonomyStreak(),
        credential_registry=CredentialRegistry(),
        load_session_events=list,
    )


async def _read_skill(deps: Deps, name: str) -> str:
    ctx = RunContext(deps=deps, model=deps.agent_model, usage=RunUsage())
    return await create_agent(deps)._function_toolset.tools["read_skill"].function(ctx, name)


def _sync(deps: Deps) -> AsyncMock:
    return cast(AsyncMock, cast(Any, deps.sandbox).sync_skill_profile)


@pytest.mark.anyio
async def test_a_built_skill_lists_its_commands_and_waits_for_the_profile(tmp_path: Path) -> None:
    deps = _deps(tmp_path, [_build("weather", "succeeded", weather=_WEATHER, forecast=_PLAIN)])

    result = await _read_skill(deps, "weather")

    assert result.startswith("---\nname: weather")
    assert "Use it well." in result
    assert "- `forecast`: Offline forecast.\n" in result
    assert (
        "- `weather`: Current weather. Asks for: domain api.example.com, "
        "credential demo/weather-token as $WEATHER_TOKEN." in result
    )
    assert result.endswith("The commands are on PATH.")
    _sync(deps).assert_awaited_once_with("s1")
    cast(AsyncMock, cast(Any, deps.sandbox).exec_command).assert_not_awaited()


@pytest.mark.anyio
async def test_an_mcp_server_lists_its_tools_through_its_own_command(tmp_path: Path) -> None:
    deps = _deps(tmp_path, [_build("tracker", "succeeded", tracker=_TRACKER, forecast=_PLAIN)])
    calls: list[str] = []

    async def exec_command(_session_id: str, command: str, **_kwargs: object) -> ExecResult:
        # The profile is synced first: the server's command has to be on PATH.
        _sync(deps).assert_awaited_once()
        calls.append(command)
        return ExecResult(stdout=_TOOLS, exit_code=0, output=_TOOLS)

    cast(Any, deps.sandbox).exec_command = AsyncMock(side_effect=exec_command)

    result = await _read_skill(deps, "tracker")

    assert calls == ["tracker --list-tools"]
    assert "- `tracker`: Issues in the example tracker. An MCP server: `tracker <tool> --flag value`" in result
    assert result.endswith(
        "The commands are on PATH.\n\n# Tools of `tracker`\n\nsearch\tFind issues by text\ncreate\tOpen an issue"
    )


@pytest.mark.anyio
async def test_a_denied_listing_is_reported_and_the_rest_still_returns(tmp_path: Path) -> None:
    deps = _deps(tmp_path, [_build("tracker", "succeeded", tracker=_TRACKER)])
    denial = "error: Sentinel denied this operation. Not for this task.\n[exit code: 1]"
    cast(Any, deps.sandbox).exec_command = AsyncMock(
        return_value=ExecResult(stdout="", exit_code=1, output=denial, leftover_processes_killed=2)
    )

    result = await _read_skill(deps, "tracker")

    assert result.startswith("---\nname: tracker")
    assert "The commands are on PATH." in result
    assert result.endswith(
        "# Tools of `tracker`\n\nThe tools could not be listed; the server may still answer a call: "
        + denial
        + "\n\nListing them killed 2 leftover process(es) from earlier commands."
    )


@pytest.mark.anyio
async def test_reading_a_skill_is_logged_for_the_sentinel(tmp_path: Path) -> None:
    deps = _deps(tmp_path, [])

    await _read_skill(deps, "weather")

    [entry] = deps.security.action_log
    assert isinstance(entry, ToolCallEntry)
    assert (entry.tool, entry.args, entry.decision) == ("read_skill", {"skill_name": "weather"}, "auto_allowed")


@pytest.mark.anyio
async def test_a_skill_with_only_instructions_points_at_its_files_in_the_sandbox(tmp_path: Path) -> None:
    deps = _deps(tmp_path, [_build("notes", "succeeded", files=("references/syntax.md",))])

    result = await _read_skill(deps, "notes")

    assert result.endswith(
        "Use it well.\n\nThe skill has no commands.\n\n"
        f"# Files\n\nThe skill's files are read-only at {_SKILL_DIR}:\n- references/syntax.md"
    )
    # The profile brings the skill directory into the sandbox.
    _sync(deps).assert_awaited_once_with("s1")


@pytest.mark.anyio
async def test_a_build_without_skill_md_says_why(tmp_path: Path) -> None:
    no_text = SkillBuild(
        skill="weather",
        key="w" * 64,
        state="failed",
        store_paths=[],
        commands={},
        detail="error: syntax error, unexpected '}'",
        skill_dir=None,
        skill_md=None,
        skill_files=[],
    )
    deps = _deps(tmp_path, [no_text])

    result = await _read_skill(deps, "weather")

    assert result == "Error: weather has no SKILL.md to read: error: syntax error, unexpected '}'"


@pytest.mark.anyio
async def test_a_failed_build_shows_its_log_tail(tmp_path: Path) -> None:
    deps = _deps(tmp_path, [_build("weather", "failed")])

    result = await _read_skill(deps, "weather")

    assert "The skill's build failed" in result
    assert result.endswith("error: attribute 'packages' missing")
    _sync(deps).assert_not_awaited()


@pytest.mark.anyio
async def test_a_command_collision_keeps_the_commands_off_path_and_says_why(tmp_path: Path) -> None:
    deps = _deps(
        tmp_path,
        [_build("weather", "succeeded", weather=_WEATHER), _build("storms", "succeeded", weather=_PLAIN)],
    )

    result = await _read_skill(deps, "weather")

    assert "- `weather`: Current weather." in result
    assert result.endswith(
        "These commands are not on PATH: its command 'weather' is also a command of storms. "
        "Rename one of them in its flake."
    )
    _sync(deps).assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("sync", "reason"),
    [
        (AsyncMock(return_value="The skill profile sync failed: error: path is not valid"), "path is not valid"),
        (AsyncMock(side_effect=SandboxLimitError("You have 3/3 sandboxes.")), "You have 3/3 sandboxes."),
    ],
)
async def test_a_failed_profile_sync_is_reported(tmp_path: Path, sync: AsyncMock, reason: str) -> None:
    deps = _deps(tmp_path, [_build("weather", "succeeded", weather=_WEATHER)])
    cast(Any, deps.sandbox).sync_skill_profile = sync

    result = await _read_skill(deps, "weather")

    assert "The commands could not be put on PATH: " in result
    assert result.endswith(reason)


@pytest.mark.anyio
@pytest.mark.parametrize("name", ["../secrets", ".hidden", "a/b", ""])
async def test_a_name_that_is_no_skill_directory_is_refused(tmp_path: Path, name: str) -> None:
    deps = _deps(tmp_path, [])

    result = await _read_skill(deps, name)

    assert result == f"Error: {name!r} is not a skill name."
    assert deps.security.action_log == []


@pytest.mark.anyio
async def test_a_missing_skill_is_reported(tmp_path: Path) -> None:
    result = await _read_skill(_deps(tmp_path, []), "nowhere")

    assert result == (
        "Error: there is no skill 'nowhere'. read_skill sees only skills that skills/flake.nix lists in the pushed "
        "repo: add its input there, run `nix flake lock ./skills`, commit and push, and the builder builds it after "
        "the push."
    )


@pytest.mark.anyio
async def test_disabled_in_the_frontmatter_is_reported(tmp_path: Path) -> None:
    deps = _deps(tmp_path, [_build("parked", "succeeded", "metadata:\n  carapace:\n    disabled: true\n")])

    result = await _read_skill(deps, "parked")

    assert result.startswith("Error: the SKILL.md of parked is invalid: ")
    assert "disabled is gone" in result


@pytest.mark.anyio
@pytest.mark.parametrize(
    "moved",
    [
        "    network:\n      domains: [ideas.example]\n",
        "    mcp:\n      - name: ideas\n        url: https://ideas.example/mcp\n",
    ],
)
async def test_a_broken_skill_md_is_reported_with_its_text(tmp_path: Path, moved: str) -> None:
    deps = _deps(tmp_path, [_build("ideas", "succeeded", f"metadata:\n  carapace:\n{moved}")])

    result = await _read_skill(deps, "ideas")

    assert result.startswith("Error: the SKILL.md of ideas is invalid: ")
    assert "moved out of the frontmatter into the skill's flake" in result
    assert result.endswith("Use it well.\n")


@pytest.mark.anyio
async def test_the_agent_reads_where_a_skill_comes_from_and_whether_it_has_an_update(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    write_skills_flake(tmp_path / "skills", [], external=["weather"])
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    commit = ["git", "-C", str(tmp_path), "-c", "user.name=T", "-c", "user.email=t@example.com", "commit", "-qm", "x"]
    subprocess.run(commit, check=True)
    deps = _deps(tmp_path, [_build("weather", "succeeded", weather=_PLAIN)])
    update = SkillUpdate(state="available", available_rev="c" * 40, available_at=datetime(2026, 11, 20, tzinfo=UTC))
    check = UpdateCheck(skills_tree="t", checked_at=datetime(2026, 11, 21, tzinfo=UTC), skills={"weather": update})
    cast(Any, deps.skill_builds).updates = MagicMock(latest=MagicMock(return_value=check))

    result = await _read_skill(deps, "weather")

    assert (
        "Use it well.\n\nFrom github:someone/weather, locked at 2222222. An update is available: ccccccc (2026-11-20); "
        "`nix flake update weather --flake ./skills` takes it.\n\n# Commands\n- `weather`: Offline forecast." in result
    )
