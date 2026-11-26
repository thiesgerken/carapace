"""The sandbox's skill profile: what it should hold, and how the sync gets it there despite the process killer."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from carapace.builder.profile import SKILLS_PROFILE_MARKER, ProfilePlan, profile_plan, sync_script
from carapace.builder.skill_builds import SkillBuild, SkillCommand, SkillNeeds
from carapace.git import GitStore
from carapace.knowledge import KnowledgeRepoHandle
from carapace.sandbox.exec_flow import (
    KILL_LEFTOVER_PROCESSES_COMMAND,
    KILL_LEFTOVER_PROCESSES_SCRIPT,
    SandboxExecCoordinator,
    SandboxExecState,
)
from carapace.sandbox.manager import SandboxManager
from carapace.sandbox.runtime import ExecResult
from carapace.sandbox.session_lifecycle import SessionContainer
from carapace.sandbox.skill_profile import KILLER_MARKER, SYNC_PID_FILE, SkillProfileSync
from carapace.session.manager import SessionManager, SessionMeta
from carapace.skills import SkillRegistry
from tests.runtime_mocks import make_runtime_mock

_NEEDS = SkillNeeds(domains=[], credentials={}, tunnels=[])


def _path(name: str) -> str:
    return f"/nix/store/{'a' * 32}-{name}"


def _build(skill: str, *commands: str, state: str = "succeeded") -> SkillBuild:
    return SkillBuild(
        skill=skill,
        tree=skill * 40,
        state=state,  # type: ignore[arg-type]
        store_paths=[_path(f"{skill}-skill"), _path(f"{skill}-skill-man")] if state == "succeeded" else [],
        commands={command: SkillCommand(description="", needs=_NEEDS) for command in commands},
        detail="",
    )


def test_the_plan_holds_every_built_skill_and_nothing_that_failed() -> None:
    plan = profile_plan([_build("b", "notes"), _build("a", "weather"), _build("c", "mail", state="failed")])

    assert plan.store_paths == (_path("a-skill"), _path("a-skill-man"), _path("b-skill"), _path("b-skill-man"))
    assert plan.excluded == {}


def test_skills_sharing_a_command_name_both_stay_out_and_say_why() -> None:
    plan = profile_plan([_build("a", "sync", "a-only"), _build("b", "sync"), _build("c", "notes")])

    assert plan.store_paths == (_path("c-skill"), _path("c-skill-man"))
    assert plan.excluded == {
        "a": "its command 'sync' is also a command of b",
        "b": "its command 'sync' is also a command of a",
    }


def test_the_sync_sets_the_profile_exactly_or_empties_it() -> None:
    plan = ProfilePlan(store_paths=(_path("a-skill"),), excluded={})

    assert f"/bin/nix-env -p /nix/var/nix/profiles/carapace/skills -i -r {_path('a-skill')}\n" in sync_script(plan)
    assert f"printf %s {plan.digest} > {SKILLS_PROFILE_MARKER}" in sync_script(plan)
    assert "/bin/nix-env -p /nix/var/nix/profiles/carapace/skills -e '.*'" in sync_script(
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
        self.fail_with = ""
        # Set: `nix-env` runs until the test releases it.
        self.hold: asyncio.Event | None = None

    async def exec(self, _container_id: str, command: Any, *_args: object, **_kwargs: object) -> ExecResult:
        if command == KILL_LEFTOVER_PROCESSES_COMMAND:
            return ExecResult(stdout=f"0\n{self.marker}", exit_code=0, output="")
        if command == ["/bin/sh", "-c", KILLER_MARKER]:
            return ExecResult(stdout=self.marker, exit_code=0, output=self.marker)
        if command[:2] == ["/bin/bash", "-c"] and "nix-env" in command[2]:
            self.syncs += 1
            # What this run installs: the script carries the plan it was made from.
            plan = self.plan
            if self.hold is not None:
                await self.hold.wait()
            if self.fail_with:
                return ExecResult(stdout="", exit_code=1, output=self.fail_with)
            if self.interrupt_next:
                # The next exec's killer ended it; profile and marker stay as they were.
                self.interrupt_next = False
                return ExecResult(stdout="", exit_code=137, output="Killed")
            self.profile, self.marker = plan.store_paths, plan.digest
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
        exec_temp_domains={},
        session_current_command={},
        domain_approval_cbs={},
        domain_notify_cbs={},
        exec_locks={},
        exec_notified_domains={},
        exec_notified_credentials={},
        running_execs={},
    )
    return SandboxExecCoordinator(runtime=runtime, state=state, profile_sync=sync), sync


_SC = SessionContainer(container_id="container-1", session_id="s1", created_at=0, last_used=0)


async def _after_exec_killer(coordinator: SandboxExecCoordinator) -> None:
    """What every ordinary exec does first: kill leftovers, then resume the profile sync."""
    await coordinator.kill_leftover_processes(_SC)
    coordinator._resume_profile_sync(_SC)


@pytest.mark.anyio
async def test_a_sync_interrupted_by_an_exec_converges_on_restart() -> None:
    stub = SandboxStub(ProfilePlan(store_paths=(_path("a-skill"),), excluded={}))
    stub.interrupt_next = True
    coordinator, sync = _coordinator(stub)

    sync.start("s1", "container-1", marker=None)
    await _idle_tasks(sync)
    assert (stub.profile, stub.marker) == ((), "")

    await _after_exec_killer(coordinator)
    await _idle_tasks(sync)

    assert (stub.profile, stub.marker, stub.syncs) == ((_path("a-skill"),), stub.plan.digest, 2)


@pytest.mark.anyio
async def test_an_up_to_date_profile_is_left_alone_and_a_new_build_is_synced() -> None:
    stub = SandboxStub(ProfilePlan(store_paths=(_path("a-skill"),), excluded={}))
    coordinator, sync = _coordinator(stub)
    sync.start("s1", "container-1", marker=None)
    await _idle_tasks(sync)

    await _after_exec_killer(coordinator)
    await _idle_tasks(sync)
    assert stub.syncs == 1

    stub.plan = ProfilePlan(store_paths=(_path("a-skill"), _path("b-skill")), excluded={})
    await _after_exec_killer(coordinator)
    await _idle_tasks(sync)

    assert (stub.profile, stub.syncs) == ((_path("a-skill"), _path("b-skill")), 2)


@pytest.mark.anyio
async def test_command_not_found_during_a_sync_gets_a_hint() -> None:
    stub = SandboxStub(ProfilePlan(store_paths=(_path("a-skill"),), excluded={}))
    _, sync = _coordinator(stub)
    missing = ExecResult(stdout="", exit_code=127, output="bash: weather: command not found")

    assert sync.with_hint("s1", missing) == missing
    sync._installing.add("s1")

    assert "Skill commands are still being installed" in sync.with_hint("s1", missing).output
    ok = ExecResult(stdout="hi", exit_code=0, output="hi")
    assert sync.with_hint("s1", ok) == ok


@pytest.mark.anyio
async def test_a_fresh_sandbox_syncs_without_anyone_asking(tmp_path: Path, db_factory: Any) -> None:
    SessionManager(db_factory, tmp_path).save_meta("s1", SessionMeta(user="thies"))
    stub = SandboxStub(ProfilePlan(store_paths=(_path("a-skill"),), excluded={}))
    runtime = make_runtime_mock()
    runtime.logs = AsyncMock(return_value="carapace sandbox ready")
    runtime.exec = AsyncMock(side_effect=stub.exec)
    manager = SandboxManager(
        runtime=runtime,
        server_host="172.18.0.1",
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
    await _idle_tasks(manager._profile_sync)
    assert stub.profile == (_path("a-skill"),)


def test_a_removed_or_disabled_skill_drops_out_of_the_plan() -> None:
    # Disabled and removed skills are not among the builds SkillBuilds reports for the head (#599).
    before = profile_plan([_build("a", "weather"), _build("b", "notes")])
    after = profile_plan([_build("a", "weather")])

    assert set(before.store_paths) - set(after.store_paths) == {_path("b-skill"), _path("b-skill-man")}


def test_paths_that_are_not_store_paths_are_refused() -> None:
    build = SkillBuild(
        skill="a", tree="a" * 40, state="succeeded", store_paths=["--remove-all"], commands={}, detail=""
    )

    with pytest.raises(ValueError, match="not store paths"):
        profile_plan([build])


@pytest.mark.anyio
async def test_the_killer_cancels_a_sync_that_has_not_started_nix_env_yet() -> None:
    stub = SandboxStub(ProfilePlan(store_paths=(_path("a-skill"),), excluded={}))
    runtime = make_runtime_mock()
    runtime.exec.side_effect = stub.exec
    sync = SkillProfileSync(runtime)
    planning = asyncio.Event()

    async def slow_plan(_session_id: str) -> ProfilePlan:
        await planning.wait()
        return stub.plan

    sync.set_plan_callback(slow_plan)
    sync.start("s1", "container-1", marker=None)
    await asyncio.sleep(0)
    sync.stop("s1")
    planning.set()
    await asyncio.sleep(0.01)

    assert stub.syncs == 0


def test_the_killer_skips_the_sync_and_its_children_when_counting(tmp_path: Path) -> None:
    proc, pid_file, marker = tmp_path / "proc", tmp_path / "sync-pid", tmp_path / "wanted"
    for pid, stat in {
        "1": "1 (sleep) S 0 1",
        "100": "100 (bash) S 1 100",  # the sync's shell
        "101": "101 (nix-env) S 100 100",  # its child
        "200": "200 (sleep) S 1 200",  # a leftover of the agent's
        "300": "300 (defunct) Z 1 300",  # a zombie
    }.items():
        (proc / pid).mkdir(parents=True)
        (proc / pid / "stat").write_text(stat + " rest of the fields\n")
    marker.write_text("abc123")
    script = (
        KILL_LEFTOVER_PROCESSES_SCRIPT.replace(SYNC_PID_FILE, str(pid_file))
        .replace(SKILLS_PROFILE_MARKER, str(marker))
        .replace("/proc/[0-9]*", f"{proc}/[0-9]*")
        .replace("${proc#/proc/}", "${proc##*/}")
        # Only the counting: no PID namespace here, so neither the parent check nor kill(-1).
        .replace("[[ $PPID != 0 ]]", "false")
        .replace("kill -9 -1", "true")
    )

    assert _run(script) == "3\nabc123"
    pid_file.write_text("100\n")
    assert _run(script) == "1\nabc123"


def _run(script: str) -> str:
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=True).stdout.strip()


async def _idle_tasks(sync: SkillProfileSync) -> None:
    while any(not task.done() for task in sync._tasks.values()):
        await asyncio.sleep(0)


@pytest.mark.anyio
async def test_a_waited_sync_returns_once_the_profile_holds_the_plan() -> None:
    stub = SandboxStub(ProfilePlan(store_paths=(_path("a-skill"),), excluded={}))
    coordinator, _sync = _coordinator(stub)
    ensure_session = AsyncMock(return_value=_SC)

    assert await coordinator.sync_skill_profile("s1", ensure_session=ensure_session) is None
    assert (stub.profile, stub.syncs) == ((_path("a-skill"),), 1)

    # The marker matches the plan now: nothing runs again.
    assert await coordinator.sync_skill_profile("s1", ensure_session=ensure_session) is None
    assert stub.syncs == 1


@pytest.mark.anyio
async def test_a_waited_sync_lets_a_running_one_finish_and_then_syncs_a_newer_plan() -> None:
    stub = SandboxStub(ProfilePlan(store_paths=(_path("a-skill"),), excluded={}))
    coordinator, sync = _coordinator(stub)
    stub.hold = asyncio.Event()
    sync.start("s1", "container-1", marker=None)
    while not stub.syncs:
        await asyncio.sleep(0)
    stub.plan = ProfilePlan(store_paths=(_path("a-skill"), _path("b-skill")), excluded={})

    waited = asyncio.create_task(coordinator.sync_skill_profile("s1", ensure_session=AsyncMock(return_value=_SC)))
    await asyncio.sleep(0)
    assert (stub.syncs, waited.done()) == (1, False)
    stub.hold.set()

    assert await waited is None
    assert (stub.profile, stub.syncs) == ((_path("a-skill"), _path("b-skill")), 2)


@pytest.mark.anyio
async def test_a_waited_sync_reports_why_it_failed() -> None:
    stub = SandboxStub(ProfilePlan(store_paths=(_path("a-skill"),), excluded={}))
    stub.fail_with = "error: cannot substitute path"
    coordinator, _sync = _coordinator(stub)

    failure = await coordinator.sync_skill_profile("s1", ensure_session=AsyncMock(return_value=_SC))

    assert failure == "The skill profile sync failed: error: cannot substitute path"
