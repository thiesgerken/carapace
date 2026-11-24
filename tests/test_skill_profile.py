"""The sandbox's skill profile: what it should hold, and how the sync gets it there despite the process killer."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from carapace.builder.profile import SKILLS_PROFILE_MARKER, ProfilePlan, profile_plan, sync_script
from carapace.builder.skill_builds import SkillBuild, SkillCommand, SkillNeeds
from carapace.git import GitStore
from carapace.knowledge import KnowledgeRepoHandle
from carapace.sandbox.exec_flow import KILL_LEFTOVER_PROCESSES_COMMAND, SandboxExecCoordinator, SandboxExecState
from carapace.sandbox.manager import SandboxManager
from carapace.sandbox.runtime import ExecResult
from carapace.sandbox.session_lifecycle import SessionContainer
from carapace.sandbox.skill_profile import SkillProfileSync
from carapace.session.manager import SessionManager, SessionMeta
from carapace.skills import SkillRegistry
from tests.runtime_mocks import make_runtime_mock

_NEEDS = SkillNeeds(domains=[], credentials={}, tunnels=[])


def _build(skill: str, *commands: str, state: str = "succeeded") -> SkillBuild:
    return SkillBuild(
        skill=skill,
        tree=skill * 40,
        state=state,  # type: ignore[arg-type]
        store_paths=[f"/nix/store/{skill}-skill", f"/nix/store/{skill}-skill-man"] if state == "succeeded" else [],
        commands={command: SkillCommand(description="", needs=_NEEDS) for command in commands},
        detail="",
    )


def test_the_plan_holds_every_built_skill_and_nothing_that_failed() -> None:
    plan = profile_plan([_build("b", "notes"), _build("a", "weather"), _build("c", "mail", state="failed")])

    assert plan.store_paths == (
        "/nix/store/a-skill",
        "/nix/store/a-skill-man",
        "/nix/store/b-skill",
        "/nix/store/b-skill-man",
    )
    assert plan.excluded == {}


def test_skills_sharing_a_command_name_both_stay_out_and_say_why() -> None:
    plan = profile_plan([_build("a", "sync", "a-only"), _build("b", "sync"), _build("c", "notes")])

    assert plan.store_paths == ("/nix/store/c-skill", "/nix/store/c-skill-man")
    assert plan.excluded == {
        "a": "its command 'sync' is also a command of b",
        "b": "its command 'sync' is also a command of a",
    }


def test_the_sync_sets_the_profile_exactly_or_empties_it() -> None:
    plan = ProfilePlan(store_paths=("/nix/store/a-skill",), excluded={})

    assert "nix-env -p /nix/var/nix/profiles/carapace/skills -i -r /nix/store/a-skill\n" in sync_script(plan)
    assert f"printf %s {plan.digest} > {SKILLS_PROFILE_MARKER}" in sync_script(plan)
    assert "nix-env -p /nix/var/nix/profiles/carapace/skills -e '.*'" in sync_script(
        ProfilePlan(store_paths=(), excluded={})
    )


class SandboxStub:
    """A sandbox's profile and marker, with a sync that the next process killer can interrupt."""

    def __init__(self, plan: ProfilePlan) -> None:
        self.plan = plan
        self.marker = ""
        self.profile: tuple[str, ...] = ()
        self.syncs = 0
        self.interrupt_next = False

    async def exec(self, _container_id: str, command: Any, *_args: object, **_kwargs: object) -> ExecResult:
        if command == KILL_LEFTOVER_PROCESSES_COMMAND:
            return ExecResult(stdout=f"0\n{self.marker}", exit_code=0, output="")
        if command[:2] == ["/bin/bash", "-c"] and "nix-env" in command[2]:
            self.syncs += 1
            if self.interrupt_next:
                # The next exec's killer ended it; profile and marker stay as they were.
                self.interrupt_next = False
                return ExecResult(stdout="", exit_code=137, output="Killed")
            self.profile, self.marker = self.plan.store_paths, self.plan.digest
            return ExecResult(stdout="", exit_code=0, output="")
        return ExecResult(stdout="", exit_code=0, output="")


def _coordinator(stub: SandboxStub) -> tuple[SandboxExecCoordinator, SkillProfileSync]:
    runtime = make_runtime_mock()
    runtime.exec.side_effect = stub.exec
    sync = SkillProfileSync(runtime)

    async def plan_for(_session_id: str) -> ProfilePlan:
        return stub.plan

    sync.set_plan_callback(plan_for)
    state = SandboxExecState(
        sessions={},
        allowed_domains={},
        exec_temp_domains={},
        exec_context_skill_domains={},
        session_current_command={},
        domain_approval_cbs={},
        domain_notify_cbs={},
        exec_locks={},
        proxy_bypass_sessions=set(),
        session_current_contexts={},
        exec_notified_domains={},
        exec_notified_credentials={},
        running_execs={},
    )
    return SandboxExecCoordinator(runtime=runtime, state=state, profile_sync=sync), sync


_SC = SessionContainer(container_id="container-1", session_id="s1", created_at=0, last_used=0)


async def _idle(sync: SkillProfileSync) -> None:
    while sync.is_syncing("s1"):
        await asyncio.sleep(0)


@pytest.mark.anyio
async def test_a_sync_interrupted_by_an_exec_converges_on_restart() -> None:
    stub = SandboxStub(ProfilePlan(store_paths=("/nix/store/a-skill",), excluded={}))
    stub.interrupt_next = True
    coordinator, sync = _coordinator(stub)

    sync.start("s1", "container-1", marker=None)
    await _idle(sync)
    assert (stub.profile, stub.marker) == ((), "")

    await coordinator.kill_leftover_processes(_SC)
    await _idle(sync)

    assert (stub.profile, stub.marker, stub.syncs) == (("/nix/store/a-skill",), stub.plan.digest, 2)


@pytest.mark.anyio
async def test_an_up_to_date_profile_is_left_alone_and_a_new_build_is_synced() -> None:
    stub = SandboxStub(ProfilePlan(store_paths=("/nix/store/a-skill",), excluded={}))
    coordinator, sync = _coordinator(stub)
    sync.start("s1", "container-1", marker=None)
    await _idle(sync)

    await coordinator.kill_leftover_processes(_SC)
    await _idle(sync)
    assert stub.syncs == 1

    stub.plan = ProfilePlan(store_paths=("/nix/store/a-skill", "/nix/store/b-skill"), excluded={})
    await coordinator.kill_leftover_processes(_SC)
    await _idle(sync)

    assert (stub.profile, stub.syncs) == (("/nix/store/a-skill", "/nix/store/b-skill"), 2)


@pytest.mark.anyio
async def test_command_not_found_during_a_sync_gets_a_hint() -> None:
    stub = SandboxStub(ProfilePlan(store_paths=("/nix/store/a-skill",), excluded={}))
    _, sync = _coordinator(stub)
    missing = ExecResult(stdout="", exit_code=127, output="bash: weather: command not found")

    assert sync.with_hint("s1", missing) == missing
    blocker = asyncio.Event()
    sync._tasks["s1"] = asyncio.create_task(blocker.wait())  # type: ignore[assignment]

    assert "Skill commands are still being installed" in sync.with_hint("s1", missing).output
    ok = ExecResult(stdout="hi", exit_code=0, output="hi")
    assert sync.with_hint("s1", ok) == ok
    blocker.set()


@pytest.mark.anyio
async def test_a_fresh_sandbox_syncs_without_anyone_asking(tmp_path: Path, db_factory: Any) -> None:
    SessionManager(db_factory, tmp_path).save_meta("s1", SessionMeta(user="thies"))
    stub = SandboxStub(ProfilePlan(store_paths=("/nix/store/a-skill",), excluded={}))
    runtime = make_runtime_mock()
    runtime.logs = AsyncMock(return_value="carapace sandbox ready")
    runtime.exec = AsyncMock(side_effect=stub.exec)
    manager = SandboxManager(
        runtime=runtime,
        data_dir=tmp_path,
        knowledge_repo_for_session=lambda _session_id: KnowledgeRepoHandle(
            owner="thies",
            knowledge_dir=tmp_path,
            git_store=GitStore(tmp_path),
            skill_registry=SkillRegistry(tmp_path / "skills"),
        ),
        session_factory=db_factory,
    )
    plan_ready = asyncio.Event()

    async def plan_for(_session_id: str) -> ProfilePlan:
        await plan_ready.wait()
        return stub.plan

    manager.set_skill_profile_plan_callback(plan_for)

    await manager.ensure_session("s1")
    # The session is up before the plan is even known: nothing waits for builds or the sync.
    assert stub.syncs == 0

    plan_ready.set()
    while manager._profile_sync.is_syncing("s1"):
        await asyncio.sleep(0)
    assert stub.profile == ("/nix/store/a-skill",)
