"""Keeps each sandbox's skill profile at what its owner's head resolves to, in the background.

The sync is an ordinary process in the sandbox, so the leftover-process killer before every exec kills it
like any other (no exemption a root agent could borrow). The killer reports the profile's marker, and the
sync starts again right after it: a killed `nix-env` keeps every path it substituted, so each run continues
where the last one stopped, and the profile only ever switches as a whole.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from loguru import logger

from ..builder.profile import SKILLS_PROFILE, SKILLS_PROFILE_MARKER, ProfilePlan, sync_script
from ..spans import span
from .runtime import ContainerGoneError, ContainerRuntime, ExecResult
from .session_lifecycle import SessionContainer

# The running sync's shell, so the killer can leave it out of the count it reports to the agent.
SYNC_PID_FILE = f"{SKILLS_PROFILE}.sync-pid"
# A cold sync of a large skill set takes minutes; one that runs longer is stuck.
_SYNC_TIMEOUT_SECONDS = 1800
# bash reports a SIGKILLed child as 128 + 9: the killer before an exec ended this sync.
_KILLED = 137

_HINT = (
    "[carapace] Skill commands are still being installed in this sandbox. "
    "If a skill command was not found, try again in a moment."
)

type ProfilePlanCallback = Callable[[str], Awaitable[ProfilePlan]]


class SkillProfileSync:
    def __init__(self, runtime: ContainerRuntime) -> None:
        self._runtime = runtime
        self._plan_for_session: ProfilePlanCallback | None = None
        self._tasks: dict[str, asyncio.Task[str | None]] = {}
        # Sessions whose `nix-env` runs right now: what the "still being installed" hint means.
        self._installing: set[str] = set()

    def set_plan_callback(self, plan_for_session: ProfilePlanCallback) -> None:
        self._plan_for_session = plan_for_session

    def start(self, sc: SessionContainer, *, marker: str | None) -> None:
        """Bring the profile to the session's plan in the background, unless *marker* says it is there.

        *marker* is what the sandbox last finished syncing to; None for a sandbox that just started, which
        always syncs (`nix-env` is a no-op when nothing changed).
        """
        self.stop(sc.session_id)
        task = asyncio.create_task(self._sync(sc, marker))
        task.add_done_callback(lambda done: _log_crash(done, sc.session_id))
        self._tasks[sc.session_id] = task

    async def sync(self, sc: SessionContainer) -> str | None:
        """Bring the profile to the session's plan and wait for it: why it failed, or None.

        The caller holds the session's exec lock, so no killer ends this sync halfway.
        """
        if (running := self._tasks.get(sc.session_id)) is not None:
            # Its plan may predate a build that just finished: let it end, then compare again.
            await asyncio.wait({running})
        marker = await self._runtime.exec(sc.container_id, ["/bin/sh", "-c", KILLER_MARKER], timeout=30)
        self.start(sc, marker=marker.stdout.strip())
        task = self._tasks[sc.session_id]
        await asyncio.wait({task})
        if task.cancelled():
            return "The skill profile sync was cancelled."
        return task.result()

    def stop(self, session_id: str) -> None:
        """Drop the session's sync task, so a sync still computing its plan cannot start `nix-env` later.

        The killer ends a `nix-env` that already runs; this keeps a pending one from starting after it.
        """
        if (task := self._tasks.pop(session_id, None)) is not None:
            task.cancel()

    def is_syncing(self, session_id: str) -> bool:
        return session_id in self._installing

    def with_hint(self, session_id: str, result: ExecResult) -> ExecResult:
        """Point a "command not found" during a running sync at the sync."""
        if not self.is_syncing(session_id):
            return result
        if result.exit_code != 127 and "command not found" not in result.output:
            return result
        return result.model_copy(update={"output": f"{result.output}\n{_HINT}"})

    async def _sync(self, sc: SessionContainer, marker: str | None) -> str | None:
        """Why the sync failed, or None when the profile holds the plan."""
        session_id = sc.session_id
        if self._plan_for_session is None:
            return None
        plan = await self._plan_for_session(session_id)
        if plan.digest == marker:
            return None
        script = f"echo $$ > {SYNC_PID_FILE}\n{sync_script(plan)}rm -f {SYNC_PID_FILE}\n"
        try:
            # Started from an exec or a sandbox start, so the span lands in that turn's timeline.
            with span("skill", "profile sync", paths=len(plan.store_paths)):
                self._installing.add(session_id)
                try:
                    # The session env carries NIX_CONFIG (the builder cache as substituter) and the proxy.
                    # A sandbox claimed from the warm pool has neither in its pod spec, only here.
                    result = await self._runtime.exec(
                        sc.container_id,
                        ["/bin/bash", "-c", script],
                        timeout=_SYNC_TIMEOUT_SECONDS,
                        env=sc.session_env or None,
                    )
                finally:
                    self._installing.discard(session_id)
        except ContainerGoneError:
            logger.debug(f"Sandbox of session {session_id} went away during its skill profile sync")
            return "The sandbox went away during the skill profile sync."
        if result.exit_code == _KILLED:
            logger.debug(f"Skill profile sync of session {session_id} was interrupted by an exec; it restarts")
            return "The skill profile sync was interrupted by an exec."
        if result.exit_code != 0:
            # The marker stays stale, so the next exec tries again.
            logger.warning(f"Skill profile sync of session {session_id} failed: {result.output[-2000:]}")
            return f"The skill profile sync failed: {result.output[-2000:]}"
        return None


def _log_crash(task: asyncio.Task[str | None], session_id: str) -> None:
    if not task.cancelled() and (exc := task.exception()) is not None:
        logger.opt(exception=exc).error(f"Skill profile sync of session {session_id} crashed")


# Leftover-process killer additions: skip the sync when counting, then report the marker.
KILLER_SYNC_PID = f"sync=$(cat {SYNC_PID_FILE} 2>/dev/null || true)"
KILLER_MARKER = f"cat {SKILLS_PROFILE_MARKER} 2>/dev/null || true"
