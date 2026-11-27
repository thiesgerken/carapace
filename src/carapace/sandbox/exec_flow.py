from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager, nullcontext
from dataclasses import dataclass

from loguru import logger

from ..security.context import ApprovalSource, ApprovalVerdict, BoundaryEvaluation
from ..span_names import EXEC_LOCK_WAIT_SPAN
from ..spans import span
from .exec_scope import RunningExec
from .runtime import ContainerGoneError, ContainerRuntime, ExecResult
from .session_lifecycle import SessionContainer
from .skill_profile import KILLER_MARKER, KILLER_SYNC_PID, SkillProfileSync
from .tunnels import ExecEndedError, Tunnel, close_script, listen_addresses, open_script

type DomainApprovalCallback = Callable[[str, RunningExec], Awaitable[BoundaryEvaluation]]
type DomainNotifyCallback = Callable[[str, str, ApprovalSource | None, ApprovalVerdict | None, str | None], None]
type EnsureSessionCallback = Callable[[str], Awaitable[SessionContainer]]
type RecreateSessionCallback = Callable[[str], Awaitable[SessionContainer]]
type LogContainerTailCallback = Callable[[str, str], Awaitable[None]]
type ExecInContainerCallback = Callable[..., Awaitable[ExecResult]]

# Kills every process in the sandbox except PID 1 (the container's `sleep infinity`) and
# prints how many live ones it found. Only bash builtins, since a fork would count itself.
# kill(-1) signals everything but PID 1 and the caller in one kernel pass, so a forking
# process cannot slip through. Zombies are not counted: `sleep infinity` never reaps them.
# The killer must be the top process of its exec, or kill(-1) would take its wrapper down.
KILL_LEFTOVER_PROCESSES_SCRIPT = f"""\
if [[ $PPID != 0 ]]; then
    echo "process killer must not run below another process in the sandbox (parent $PPID)" >&2
    exit 1
fi
{KILLER_SYNC_PID}
leftover=0
for proc in /proc/[0-9]*; do
    pid=${{proc#/proc/}}
    [[ $pid == 1 || $pid == $$ ]] && continue
    read -r stat 2>/dev/null < "$proc/stat" || continue
    read -r state ppid _ <<< "${{stat##*) }}"
    [[ $state == Z ]] && continue
    # The skill profile sync dies like every other process, but it is no leftover of the agent's.
    [[ -n $sync && ($pid == "$sync" || $ppid == "$sync") ]] && continue
    leftover=$((leftover + 1))
done
# As root, kill(-1) only fails with ESRCH: everything counted has exited by itself meanwhile.
kill -9 -1 2>/dev/null || true
echo "$leftover"
{KILLER_MARKER}
"""
# A process that outlived its exec asks for nothing: what it was granted ended with that exec.
ORPHANED_REQUEST_REJECTION = "Denied: no exec is running, the request comes from a process an earlier exec left behind."
# The decision was made for an exec that is gone; granting it now would reach no one or the wrong exec.
EXEC_ENDED_REJECTION = "Denied: the exec that asked ended before the decision came back."

# Absolute path: the agent can write to directories on PATH.
KILL_LEFTOVER_PROCESSES_COMMAND = ["/bin/bash", "-c", KILL_LEFTOVER_PROCESSES_SCRIPT]


@dataclass
class SandboxExecState:
    sessions: dict[str, SessionContainer]
    exec_temp_domains: dict[str, set[str]]
    session_current_command: dict[str, str]
    domain_approval_cbs: dict[str, DomainApprovalCallback]
    domain_notify_cbs: dict[str, DomainNotifyCallback]
    exec_locks: dict[str, asyncio.Lock]
    exec_notified_domains: dict[str, set[str]]
    exec_notified_credentials: dict[str, set[str]]
    # One per running exec; what it was granted needs no further review until it ends.
    running_execs: dict[str, RunningExec]


class SandboxExecCoordinator:
    def __init__(self, *, runtime: ContainerRuntime, state: SandboxExecState, profile_sync: SkillProfileSync) -> None:
        self._runtime = runtime
        self._state = state
        self._profile_sync = profile_sync
        # What the last killer reported per session, until the sync it interrupted is started again.
        self._profile_markers: dict[str, str] = {}

    def get_exec_lock(self, session_id: str) -> asyncio.Lock:
        if session_id not in self._state.exec_locks:
            self._state.exec_locks[session_id] = asyncio.Lock()
        return self._state.exec_locks[session_id]

    @asynccontextmanager
    async def hold_exec_lock(self, session_id: str) -> AsyncGenerator[None]:
        """Hold the session's exec lock; waiting for it is a `wait` span, so a call queued behind another says so.

        An uncontended acquire records nothing: the timeline gets no zero-length span per call.
        """
        lock = self.get_exec_lock(session_id)
        with span("wait", EXEC_LOCK_WAIT_SPAN) if lock.locked() else nullcontext():
            await lock.acquire()
        try:
            yield
        finally:
            lock.release()

    async def exec_in_container(
        self,
        sc: SessionContainer,
        command: str,
        timeout: int = 30,
        *,
        workdir: str | None = None,
        stdin: bytes | None = None,
    ) -> ExecResult:
        """Run *command* in *sc* without acquiring the exec lock."""
        return await self._runtime.exec(
            sc.container_id,
            command,
            timeout=timeout,
            workdir=workdir,
            env=sc.session_env or None,
            stdin=stdin,
        )

    async def exec(
        self,
        session_id: str,
        command: str,
        timeout: int = 30,
        *,
        ensure_session: EnsureSessionCallback,
        recreate_session: RecreateSessionCallback,
        log_container_tail: LogContainerTailCallback,
        exec_in_container: ExecInContainerCallback,
        tool_call_id: str | None,
        workdir: str | None = None,
        stdin: bytes | None = None,
    ) -> ExecResult:
        """Run a command in the sandbox and return the raw ExecResult.

        Leftover processes are killed before the exec scope opens, so only processes started by this
        call can use what its boundary requests are granted.
        """

        async def run_in(container: SessionContainer) -> ExecResult:
            leftover_processes_killed = await self.kill_leftover_processes(container)
            self._resume_profile_sync(container)
            self._grant_exec_scope(session_id, command, tool_call_id=tool_call_id)
            result = await exec_in_container(container, command, timeout, workdir=workdir, stdin=stdin)
            result = self._profile_sync.with_hint(session_id, result)
            return result.model_copy(update={"leftover_processes_killed": leftover_processes_killed})

        async with self.hold_exec_lock(session_id):
            try:
                sc = await ensure_session(session_id)
                sc.last_used = time.time()
                logger.debug(f"Exec in session {session_id}: {command}")
                try:
                    return await run_in(sc)
                except ContainerGoneError:
                    logger.warning(f"Container gone for session {session_id}, recreating sandbox")
                    self._revoke_exec_scope(session_id)
                    await log_container_tail(sc.container_id, session_id)
                    return await run_in(await recreate_session(session_id))
            finally:
                running = self._state.running_execs.get(session_id)
                self._revoke_exec_scope(session_id)
                if running is not None:
                    await self._close_tunnels(running)

    async def open_tunnels(self, running: RunningExec, tunnels: list[Tunnel]) -> str | None:
        """Open *tunnels* for the running exec; why they could not be opened, or None.

        Runs while that exec holds the exec lock, so it goes to the container directly. Raises
        ``ExecEndedError`` when the exec ended before the tunnels could be opened.
        """
        async with running.tunnel_lock:
            if not self.is_running(running):
                raise ExecEndedError
            new = listen_addresses(running.tunnels, [tunnel for tunnel in tunnels if tunnel not in running.tunnels])
            if not new:
                return None
            sc = self._state.sessions[running.session_id]
            script = open_script(new, running.tunnels)
            # Recorded first: the close at the end of the exec also cleans up a half-opened tunnel.
            running.tunnels.update(new)
            result = await self._runtime.exec(
                sc.container_id, ["/bin/bash", "-c", script], timeout=30, env=sc.session_env or None
            )
            if result.exit_code != 0:
                # Closes the exec's other tunnels too: recorded as open, a failed one would let a retry
                # answer 200 with nothing listening. Starting over is the simple way to keep the record true.
                await self._run_close_script(sc)
                running.tunnels.clear()
                return f"The tunnels could not be opened: {result.output.strip()[-2000:]}"
            return None

    async def _close_tunnels(self, running: RunningExec) -> None:
        """Close what the exec opened; waits for an open that is still running."""
        async with running.tunnel_lock:
            sc = self._state.sessions.get(running.session_id)
            if not running.tunnels or sc is None:
                return
            try:
                await self._run_close_script(sc)
            except ContainerGoneError:
                return

    async def _run_close_script(self, sc: SessionContainer) -> None:
        result = await self._runtime.exec(sc.container_id, ["/bin/bash", "-c", close_script()], timeout=30)
        if result.exit_code != 0:
            # Left open, /etc/hosts would keep pointing the hosts at forwarders the next killer ends.
            raise RuntimeError(f"Failed to close the tunnels of session {sc.session_id}: {result.output}")

    async def sync_skill_profile(self, session_id: str, *, ensure_session: EnsureSessionCallback) -> str | None:
        """Bring the session's skill profile to its plan and wait for it: why it failed, or None.

        Under the exec lock, so no exec's killer ends the sync halfway.
        """
        async with self.hold_exec_lock(session_id):
            sc = await ensure_session(session_id)
            return await self._profile_sync.sync(sc)

    async def kill_leftover_processes(self, sc: SessionContainer) -> int:
        """Kill every process in *sc* except PID 1 and return how many the agent left behind.

        That includes a running skill profile sync. The caller starts it again with ``_resume_profile_sync``.
        """
        self._profile_sync.stop(sc.session_id)
        result = await self._runtime.exec(sc.container_id, KILL_LEFTOVER_PROCESSES_COMMAND, timeout=30)
        if result.exit_code != 0:
            raise RuntimeError(f"Failed to kill leftover processes in session {sc.session_id}: {result.output}")
        count, _, marker = result.stdout.partition("\n")
        self._profile_markers[sc.session_id] = marker.strip()
        killed = int(count)
        if killed:
            logger.info(f"Killed {killed} leftover process(es) in session {sc.session_id}")
        return killed

    def _resume_profile_sync(self, sc: SessionContainer) -> None:
        """Start the profile sync the killer interrupted."""
        marker = self._profile_markers.pop(sc.session_id, None)
        if marker is not None:
            self._profile_sync.start(sc, marker=marker)

    def _grant_exec_scope(self, session_id: str, command: str, *, tool_call_id: str | None) -> None:
        self._state.session_current_command[session_id] = command
        self._state.exec_temp_domains[session_id] = set()
        self._state.exec_notified_domains[session_id] = set()
        self._state.exec_notified_credentials[session_id] = set()
        self._state.running_execs[session_id] = RunningExec(
            session_id=session_id,
            command=command,
            domains=self._state.exec_temp_domains[session_id],
            credentials=set(),
            tool_call_id=tool_call_id,
        )

    def _revoke_exec_scope(self, session_id: str) -> None:
        self._state.session_current_command.pop(session_id, None)
        self._state.exec_temp_domains.pop(session_id, None)
        self._state.exec_notified_domains.pop(session_id, None)
        self._state.exec_notified_credentials.pop(session_id, None)
        self._state.running_execs.pop(session_id, None)

    def get_domain_info(self, session_id: str) -> list[dict[str, str]]:
        return [
            {"domain": domain, "scope": "this exec only"}
            for domain in sorted(self._state.exec_temp_domains.get(session_id, set()))
        ]

    def get_effective_domains(self, session_id: str) -> set[str]:
        return set(self._state.exec_temp_domains.get(session_id, set()))

    def mark_credential_notified(self, session_id: str, vault_path: str) -> bool:
        notified = self._state.exec_notified_credentials.get(session_id)
        if notified is None:
            return False
        if vault_path in notified:
            return True
        notified.add(vault_path)
        return False

    def running_exec(self, session_id: str) -> RunningExec | None:
        """The scope of the running exec, or None between execs."""
        return self._state.running_execs.get(session_id)

    def is_running(self, running: RunningExec) -> bool:
        # Every exec gets its own scope objects, so identity tells this exec apart from a later one. The
        # domain set is checked too: session teardown drops it without knowing about running execs.
        return (
            self._state.running_execs.get(running.session_id) is running
            and self._state.exec_temp_domains.get(running.session_id) is running.domains
        )

    def notify_domain_access(self, session_id: str, domain: str, allowed: bool, refusal: str | None = None) -> None:
        """Show a denial no reviewer made; *refusal* is the destination policy's reason, if that refused it."""
        if allowed or (cb := self._state.domain_notify_cbs.get(session_id)) is None:
            return
        if refusal is not None:
            cb(domain, f"[denied] {domain}", "policy", "deny", refusal)
        else:
            cb(domain, f"[denied] {domain}", "unknown", "deny", "no approval callback configured")

    def set_domain_approval_callback(self, session_id: str, cb: DomainApprovalCallback | None) -> None:
        if cb is None:
            self._state.domain_approval_cbs.pop(session_id, None)
        else:
            self._state.domain_approval_cbs[session_id] = cb

    def set_domain_notify_callback(self, session_id: str, cb: DomainNotifyCallback | None) -> None:
        if cb is None:
            self._state.domain_notify_cbs.pop(session_id, None)
        else:
            self._state.domain_notify_cbs[session_id] = cb

    async def request_domain_approval(self, session_id: str, domain: str) -> BoundaryEvaluation:
        cb = self._state.domain_approval_cbs.get(session_id)
        if cb is None:
            logger.warning(f"No domain approval callback for session {session_id}, denying {domain}")
            return BoundaryEvaluation(allowed=False, rejection="No approval path is set up for this session.")

        # No live exec: the request comes from a process an earlier exec left behind.
        # Deny without invoking the sentinel so orphaned traffic can't burn tokens.
        running = self.running_exec(session_id)
        if running is None:
            logger.info(f"Denying {domain} for session {session_id}: no active exec (orphaned request)")
            return BoundaryEvaluation(allowed=False, rejection=ORPHANED_REQUEST_REJECTION)

        evaluation = await cb(domain, running)
        if not self.is_running(running):
            logger.info(f"Denying {domain} for session {session_id}: its exec ended during the review")
            return BoundaryEvaluation(allowed=False, rejection=EXEC_ENDED_REJECTION)
        running.boundary_reviewed = True
        if evaluation.allowed:
            running.domains.add(domain)
            logger.info(f"Security approved {domain} for session {session_id}")
        else:
            logger.info(f"Security denied {domain} for session {session_id}")
        return evaluation

    def cleanup_tracking(self, session_id: str) -> None:
        self._state.domain_approval_cbs.pop(session_id, None)
        self._state.domain_notify_cbs.pop(session_id, None)
        self._state.exec_notified_domains.pop(session_id, None)
        self._state.exec_notified_credentials.pop(session_id, None)
        self._state.running_execs.pop(session_id, None)
