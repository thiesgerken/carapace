from __future__ import annotations

import base64
import os
import secrets
import shlex
from asyncio.locks import Lock
from collections.abc import Awaitable, Callable
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path

from loguru import logger

from ..database.engine import SessionFactory
from ..knowledge import KnowledgeRepoHandle, KnowledgeRepoResolver
from ..models.git import GitActionResult, SandboxGitStatus
from ..security.context import ApprovalSource, ApprovalVerdict, BoundaryEvaluation
from ..spans import span
from . import file_ops
from .exec_flow import SandboxExecCoordinator, SandboxExecState
from .exec_scope import RunningExec
from .file_ops import SandboxFileOps
from .runtime import ContainerRuntime, ExecResult, SandboxStatus
from .session_lifecycle import (
    SandboxSessionLifecycle,
    SandboxSessionLifecycleState,
    SessionContainer,
)
from .skill_profile import ProfilePlanCallback, SkillProfileSync
from .state import (
    SessionSandboxSnapshot,
    clear_sandbox_snapshot,
    count_owned_sessions,
    load_sandbox_snapshot,
    save_sandbox_snapshot,
    session_owner,
)
from .tunnels import Tunnel

_READ_ERROR_TAIL_CHARS = 2000
FILE_READ_SCRIPT = file_ops.FILE_READ_SCRIPT
MAX_READ_OUTPUT_CHARS = file_ops.MAX_READ_OUTPUT_CHARS
SANDBOX_READ_BODY_SEPARATOR = file_ops.SANDBOX_READ_BODY_SEPARATOR
READ_TOOL_MAX_LINE_WINDOW = file_ops.READ_TOOL_MAX_LINE_WINDOW
READ_IMAGE_MAX_BYTES = file_ops.READ_IMAGE_MAX_BYTES


class UploadError(Exception):
    """Writing an uploaded file into the sandbox failed."""


class SandboxLimitError(RuntimeError):
    """Raised when starting a new sandbox would exceed its owner's sandbox limit."""


class UploadTooLargeError(UploadError):
    """Uploaded file exceeded the allowed size."""


class SandboxManager:
    def __init__(
        self,
        runtime: ContainerRuntime,
        data_dir: Path,
        knowledge_repo_for_session: KnowledgeRepoResolver,
        session_factory: SessionFactory,
        base_image: str = "carapace-sandbox:latest",
        *,
        server_host: str,
        network_name: str,
        idle_timeout_minutes: int = 15,
        proxy_port: int = 3128,
        sandbox_port: int = 8322,
        warm_pool_size: int = 0,
        max_sandboxes_per_user: int = 0,
        nix_config: Callable[[], Awaitable[str]] | None = None,
    ) -> None:
        self._runtime = runtime
        self._max_sandboxes_per_user = max_sandboxes_per_user
        self._data_dir = data_dir
        self._session_factory = session_factory
        self._knowledge_repo_for_session = knowledge_repo_for_session
        self._base_image = base_image
        self._network_name = network_name
        self._idle_timeout = idle_timeout_minutes * 60
        self._proxy_port = proxy_port
        self._sandbox_port = sandbox_port
        self._sessions: dict[str, SessionContainer] = {}
        self._token_to_session: dict[str, str] = {}
        self._session_tokens: dict[str, str] = {}
        self._exec_temp_domains: dict[str, set[str]] = {}  # session_id -> domains, cleared after each exec
        self._session_current_command: dict[str, str] = {}
        self._domain_approval_cbs: dict[str, Callable[[str, RunningExec], Awaitable[BoundaryEvaluation]]] = {}
        self._domain_notify_cbs: dict[
            str,
            Callable[[str, str, ApprovalSource | None, ApprovalVerdict | None, str | None], None],
        ] = {}
        self._exec_locks: dict[str, Lock] = {}
        # Never pruned: dropping a lock that a caller holds or is queued on would let
        # a newcomer start concurrently on a fresh one. One Lock per session is cheap.
        self._startup_locks: dict[str, Lock] = {}
        self._stashed_session_env: dict[str, dict[str, str]] = {}
        self._exec_notified_domains: dict[str, set[str]] = {}  # dedupe silent-allow domain UI notifications
        self._exec_notified_credentials: dict[str, set[str]] = {}  # dedupe credential UI notifications
        self._running_execs: dict[str, RunningExec] = {}
        self._session_lifecycle = SandboxSessionLifecycle(
            runtime=runtime,
            state=SandboxSessionLifecycleState(
                sessions=self._sessions,
                token_to_session=self._token_to_session,
                session_tokens=self._session_tokens,
                exec_temp_domains=self._exec_temp_domains,
                session_current_command=self._session_current_command,
                domain_approval_cbs=self._domain_approval_cbs,
                domain_notify_cbs=self._domain_notify_cbs,
                exec_locks=self._exec_locks,
                stashed_session_env=self._stashed_session_env,
                exec_notified_domains=self._exec_notified_domains,
                exec_notified_credentials=self._exec_notified_credentials,
            ),
            data_dir=data_dir,
            session_factory=session_factory,
            base_image=base_image,
            network_name=network_name,
            server_host=server_host,
            idle_timeout=self._idle_timeout,
            proxy_port=proxy_port,
            sandbox_port=sandbox_port,
            warm_pool_size=warm_pool_size,
            knowledge_repo_name_for_session=self._knowledge_repo_name_for_session,
            git_author_for_session=self._git_author_for_session,
            nix_config=nix_config,
        )
        self._profile_sync = SkillProfileSync(runtime)
        self._exec_coordinator = SandboxExecCoordinator(
            runtime=runtime,
            profile_sync=self._profile_sync,
            state=SandboxExecState(
                sessions=self._sessions,
                exec_temp_domains=self._exec_temp_domains,
                session_current_command=self._session_current_command,
                domain_approval_cbs=self._domain_approval_cbs,
                domain_notify_cbs=self._domain_notify_cbs,
                exec_locks=self._exec_locks,
                exec_notified_domains=self._exec_notified_domains,
                exec_notified_credentials=self._exec_notified_credentials,
                running_execs=self._running_execs,
            ),
        )
        self._sandbox_file_ops = SandboxFileOps(exec_in_session=self._exec)
        logger.info(
            f"SandboxManager initialized (image={base_image}, "
            + f"network={network_name}, proxy_port={proxy_port}, idle_timeout={idle_timeout_minutes}m)"
        )

    def set_skill_profile_plan_callback(self, cb: ProfilePlanCallback) -> None:
        """What a session's skill profile should hold: its owner's built skills (see builder/profile.py)."""
        self._profile_sync.set_plan_callback(cb)

    def _repo_for_session(self, session_id: str) -> KnowledgeRepoHandle:
        return self._knowledge_repo_for_session(session_id)

    def _knowledge_dir_for_session(self, session_id: str) -> Path:
        return self._repo_for_session(session_id).knowledge_dir

    def _knowledge_repo_name_for_session(self, session_id: str) -> str:
        return self._knowledge_dir_for_session(session_id).name

    def _git_author_for_session(self, session_id: str) -> str:
        return self._repo_for_session(session_id).git_store.author_template

    async def refresh_git_identities(self, owner: str) -> None:
        """Reapply the git identity in *owner*'s running sandboxes.

        Scoped to one owner so a broken sandbox of another user can't fail this
        owner's settings change.

        Deliberately outside the exec lock: the caller holds the knowledge git
        runtime lock, which an agent's ``git push`` takes (``push_if_configured``)
        while its exec holds the exec lock, so waiting here would deadlock. It
        grants nothing; a concurrent kill only fails the settings save loudly.
        """
        for session_id, session in self._sessions.items():
            if session_owner(self._session_factory, session_id) != owner:
                continue
            if not await self._runtime.is_running(session.container_id):
                continue
            await self._session_lifecycle.setup_git_identity(session.container_id, session_id)

    async def ensure_warm_pool(self, target_size: int) -> int:
        return await self._session_lifecycle.ensure_warm_pool(target_size)

    def _get_or_create_token(self, session_id: str) -> str:
        return self._session_lifecycle.get_or_create_token(session_id)

    async def _log_container_tail(self, container_id: str, session_id: str) -> None:
        await self._session_lifecycle.log_container_tail(container_id, session_id)

    def _get_exec_lock(self, session_id: str) -> Lock:
        return self._exec_coordinator.get_exec_lock(session_id)

    def _get_startup_lock(self, session_id: str) -> Lock:
        return self._startup_locks.setdefault(session_id, Lock())

    def _save_transient_sandbox_snapshot(
        self,
        session_id: str,
        status: SandboxStatus,
        *,
        last_error: str | None = None,
    ) -> None:
        existing = load_sandbox_snapshot(self._session_factory, session_id)
        snapshot = SessionSandboxSnapshot(
            exists=existing.exists if existing is not None else False,
            runtime=self._runtime.runtime_kind,
            status=status,
            sandbox_id=existing.sandbox_id if existing is not None and existing.exists else None,
            resource_id=existing.resource_id if existing is not None else None,
            resource_kind=existing.resource_kind if existing is not None else None,
            storage_present=existing.storage_present if existing is not None else False,
            provisioned_bytes=existing.provisioned_bytes if existing is not None else None,
            last_measured_used_bytes=existing.last_measured_used_bytes if existing is not None else None,
            last_measured_at=existing.last_measured_at if existing is not None else None,
            updated_at=datetime.now(tz=UTC),
            last_error=last_error,
        )
        save_sandbox_snapshot(self._session_factory, session_id, snapshot)

    async def ensure_session(self, session_id: str) -> SessionContainer:
        """Return the session's running sandbox, starting, resuming or re-attaching it as needed.

        This is the single entry point for sandbox startup. It is serialized per
        session because parallel tool calls would otherwise each find no live
        sandbox and race to claim or create one. Nothing under the lock may call
        back into ``ensure_session`` (the lock is not reentrant); the exec path
        takes its exec lock before this one.
        """
        async with self._get_startup_lock(session_id):
            return await self._start_session(session_id, recreated=False)

    async def recreate_session(self, session_id: str) -> SessionContainer:
        """Replace a sandbox whose container vanished.

        Runtime setup always reruns here: the lifecycle may re-attach to a pod the
        runtime already restarted on its own, which looks like a healthy sandbox
        but has lost everything outside the persistent workspace.
        """
        async with self._get_startup_lock(session_id):
            self._session_lifecycle.prepare_session_recreate(session_id)
            return await self._start_session(session_id, recreated=True)

    async def _start_session(self, session_id: str, *, recreated: bool) -> SessionContainer:
        """Start or attach the sandbox and keep the persisted snapshot in sync. Requires the startup lock."""
        sc = self._sessions.get(session_id)
        needs_startup = sc is None or not await self._runtime.is_running(sc.container_id)
        if needs_startup:
            await self._enforce_sandbox_limit(session_id)
            self._save_transient_sandbox_snapshot(session_id, "pending")

        try:
            # A sandbox that is already up costs nothing worth a span on every exec.
            with span("sandbox", "ensure") if needs_startup or recreated else nullcontext():
                ensured_sc = await self._attach_or_start(session_id, recreated=recreated)
        except BaseException as exc:
            if needs_startup:
                try:
                    await self.refresh_sandbox_snapshot(session_id)
                except Exception:
                    logger.exception(
                        f"Failed to refresh sandbox snapshot after startup failure for session {session_id}"
                    )
                    self._save_transient_sandbox_snapshot(session_id, "error", last_error=str(exc))
            raise

        if needs_startup or recreated:
            # A sandbox that just started or came back has no profile, or an old one; nothing waits for it.
            self._profile_sync.start(ensured_sc, marker=None)
        if needs_startup:
            try:
                await self.refresh_sandbox_snapshot(session_id, container_id=ensured_sc.container_id)
            except Exception:
                logger.exception(f"Failed to refresh sandbox snapshot after startup for session {session_id}")
        return ensured_sc

    async def count_user_sandboxes(self, user: str) -> int:
        """Count the sandboxes *user* holds, running or suspended."""
        retained = await self._runtime.retained_sandbox_session_ids()
        return count_owned_sessions(self._session_factory, user, retained)

    async def _enforce_sandbox_limit(self, session_id: str) -> None:
        """Refuse to give *session_id* a new sandbox once its owner is at the limit.

        A session that already holds a sandbox is resumed or recreated in place, which
        never adds one, so it is never refused. The startup lock is per session, so
        parallel starts of different sessions can overshoot the limit by a few.
        """
        if self._max_sandboxes_per_user == 0:
            return
        retained = await self._runtime.retained_sandbox_session_ids()
        if session_id in retained:
            return
        count = count_owned_sessions(self._session_factory, session_owner(self._session_factory, session_id), retained)
        if count >= self._max_sandboxes_per_user:
            raise SandboxLimitError(
                f"You have {count}/{self._max_sandboxes_per_user} sandboxes. Delete old sessions to start a new one."
            )

    async def _attach_or_start(self, session_id: str, *, recreated: bool) -> SessionContainer:
        """Run the lifecycle and restore runtime-only state on a fresh runtime. Requires the startup lock."""
        sc, needs_runtime_setup = await self._session_lifecycle.ensure_session(session_id)
        if needs_runtime_setup or recreated:
            await self._session_lifecycle.setup_git_identity(sc.container_id, session_id)
        return sc

    def _sandbox_name(self, session_id: str) -> str:
        return self._session_lifecycle.sandbox_name(session_id)

    def _build_proxy_env(self, session_id: str, proxy_token: str, proxy_url: str) -> dict[str, str]:
        return self._session_lifecycle.build_proxy_env(session_id, proxy_token, proxy_url)

    async def refresh_sandbox_snapshot(
        self,
        session_id: str,
        *,
        measure_usage: bool = False,
        container_id: str | None = None,
    ) -> SessionSandboxSnapshot:
        sandbox_name = self._sandbox_name(session_id)
        resolved_container_id = container_id
        if resolved_container_id is None:
            sc = self._sessions.get(session_id)
            if sc is not None:
                resolved_container_id = sc.container_id
            else:
                existing_id = await self._runtime.sandbox_exists(sandbox_name)
                resolved_container_id = existing_id if isinstance(existing_id, str) and existing_id else None

        inspection = await self._runtime.inspect_sandbox(session_id, sandbox_name, resolved_container_id)
        existing = load_sandbox_snapshot(self._session_factory, session_id)
        measured_used_bytes = existing.last_measured_used_bytes if existing is not None else None
        measured_at = existing.last_measured_at if existing is not None else None
        if measure_usage:
            current_used_bytes = await self._runtime.measure_workspace_usage(session_id, resolved_container_id)
            if current_used_bytes is not None:
                measured_used_bytes = current_used_bytes
                measured_at = datetime.now(tz=UTC)
        if not inspection.storage_present:
            measured_used_bytes = None
            measured_at = None

        snapshot = SessionSandboxSnapshot(
            exists=inspection.exists,
            runtime=self._runtime.runtime_kind,
            status=inspection.status,
            sandbox_id=self._session_lifecycle.sandbox_id_for_session(session_id) if inspection.exists else None,
            resource_id=inspection.resource_id,
            resource_kind=inspection.resource_kind,
            storage_present=inspection.storage_present,
            provisioned_bytes=inspection.provisioned_bytes,
            last_measured_used_bytes=measured_used_bytes,
            last_measured_at=measured_at,
            updated_at=datetime.now(tz=UTC),
        )
        save_sandbox_snapshot(self._session_factory, session_id, snapshot)
        return snapshot

    async def _exec_in_container(
        self,
        sc: SessionContainer,
        command: str,
        timeout: int = 30,
        *,
        workdir: str | None = None,
        stdin: bytes | None = None,
    ) -> ExecResult:
        return await self._exec_coordinator.exec_in_container(
            sc, command, timeout=timeout, workdir=workdir, stdin=stdin
        )

    async def _exec(
        self,
        session_id: str,
        command: str,
        timeout: int = 30,
        *,
        workdir: str | None = None,
        stdin: bytes | None = None,
    ) -> ExecResult:
        return await self._exec_coordinator.exec(
            session_id,
            command,
            timeout=timeout,
            ensure_session=self.ensure_session,
            recreate_session=self.recreate_session,
            log_container_tail=self._log_container_tail,
            exec_in_container=self._exec_in_container,
            workdir=workdir,
            stdin=stdin,
        )

    _KNOWLEDGE_WORKDIR = "/workspace"

    async def exec_command(self, session_id: str, command: str, timeout: int = 3600) -> ExecResult:
        """Run a command in the sandbox and return the result."""
        result = await self._exec(session_id, command, timeout=timeout, workdir=self._KNOWLEDGE_WORKDIR)
        output = result.output
        if result.exit_code != 0 and f"[exit code: {result.exit_code}]" not in output:
            logger.debug(f"Command failed in session {session_id} (exit {result.exit_code}): {command}")
            output += f"\n[exit code: {result.exit_code}]"
        return result.model_copy(update={"output": output or "(no output)"})

    async def sync_skill_profile(self, session_id: str) -> str | None:
        """Bring the session's skill profile to its plan and wait for it: why it failed, or None."""
        return await self._exec_coordinator.sync_skill_profile(session_id, ensure_session=self.ensure_session)

    # ------------------------------------------------------------------
    # Sandbox git status / sync (B1: /workspace clone ↔ backend repo).
    # These run via _exec_in_container directly — NOT the agent exec path —
    # so they never appear as agent tool calls ("without telling the agent").
    # The cloned origin URL embeds credentials, so plain git commands work.
    # The origin is the sandbox API host, which is in NO_PROXY, so these need
    # no proxy bypass. Whatever writes to .git takes the exec lock: the kill at
    # the start of every exec would otherwise hit a running fetch, pull or push
    # and leave stale lock files behind.
    # ------------------------------------------------------------------

    async def _git_in_workspace(self, sc: SessionContainer, args: str, *, timeout: int = 30) -> ExecResult:
        return await self._exec_in_container(
            sc,
            f"git -C {self._KNOWLEDGE_WORKDIR} {args}",
            timeout=timeout,
        )

    async def _running_container(self, session_id: str) -> SessionContainer | None:
        """Return the session's container only if it is already running — never boots it.

        Reading git state must not resume a spun-down sandbox (mirrors the
        delete flow, which avoids booting just to inspect git state). A running
        container is adopted via ``ensure_session`` (which re-attaches without
        booting), so this works even when ``_sessions`` is cold (e.g. after a
        server restart) — matching how the sandbox snapshot detects "running".
        """
        sc = self._sessions.get(session_id)
        if sc is not None and await self._runtime.is_running(sc.container_id):
            return sc

        existing_id = await self._runtime.sandbox_exists(self._sandbox_name(session_id))
        if isinstance(existing_id, str) and existing_id and await self._runtime.is_running(existing_id):
            # Bypass self.ensure_session: it writes a transient "pending" sandbox
            # snapshot when the cache is cold, which would wrongly flip UI state for
            # a read-only status check. The container is already running, so this
            # re-attaches without booting and without touching the snapshot.
            async with self._get_startup_lock(session_id):
                return await self._attach_or_start(session_id, recreated=False)
        return None

    async def sandbox_git_status(self, session_id: str, *, fetch: bool) -> SandboxGitStatus:
        """Return ahead/behind of the sandbox clone vs the backend repo.

        Does not boot a stopped sandbox — returns ``running=False`` instead.
        The read-only commands run without the exec lock, so the status never waits
        for a running command; a kill only fails that one status call. The fetch
        writes to .git, so it runs only while no command does.
        """
        sc = await self._running_container(session_id)
        if sc is None:
            return SandboxGitStatus(running=False)

        fetched = False
        exec_lock = self._get_exec_lock(session_id)
        # An uncontended acquire does not yield, so nothing can take the lock in between.
        if fetch and not exec_lock.locked():
            async with exec_lock:
                fr = await self._git_in_workspace(sc, "fetch origin", timeout=60)
            fetched = fr.exit_code == 0

        branch_res = await self._git_in_workspace(sc, "rev-parse --abbrev-ref HEAD", timeout=10)
        branch = branch_res.output.strip() if branch_res.exit_code == 0 else None

        upstream = await self._git_in_workspace(sc, "rev-parse --abbrev-ref --symbolic-full-name @{u}", timeout=10)
        if upstream.exit_code != 0:
            return SandboxGitStatus(branch=branch, upstream=False, fetched=fetched)

        counts = await self._git_in_workspace(sc, "rev-list --left-right --count @{u}...HEAD", timeout=10)
        behind, ahead = self._parse_left_right(counts)
        return SandboxGitStatus(branch=branch, upstream=True, ahead=ahead, behind=behind, fetched=fetched)

    async def sandbox_git_pull(self, session_id: str) -> GitActionResult:
        """Pull the sandbox clone from the backend repo (fast-forward only)."""
        async with self._get_exec_lock(session_id):
            sc = await self.ensure_session(session_id)
            res = await self._git_in_workspace(sc, "pull --ff-only", timeout=120)
        ok = res.exit_code == 0
        return GitActionResult(ok=ok, message=res.output.strip() or ("Pulled." if ok else "Pull failed."))

    async def sandbox_git_push(self, session_id: str) -> GitActionResult:
        """Push the sandbox clone to the backend repo (sentinel-gated via pre-receive)."""
        async with self._get_exec_lock(session_id):
            sc = await self.ensure_session(session_id)
            res = await self._git_in_workspace(sc, "push origin HEAD", timeout=600)
        ok = res.exit_code == 0
        denied = not ok and "DENIED" in res.output
        message = res.output.strip() or ("Pushed." if ok else "Push failed.")
        return GitActionResult(ok=ok, message=message, denied=denied)

    @staticmethod
    def _parse_left_right(res: ExecResult) -> tuple[int, int]:
        """Parse ``git rev-list --left-right --count`` output into ``(left, right)``."""
        if res.exit_code != 0:
            return 0, 0
        parts = res.output.split()
        if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
            return 0, 0
        return int(parts[0]), int(parts[1])

    # ------------------------------------------------------------------
    # File operations (executed inside the sandbox container via
    # shell commands and small inline Python snippets).
    # Data is passed as base64 CLI args to avoid shell-escaping issues.
    # ------------------------------------------------------------------

    async def file_read(self, session_id: str, path: str, *, offset: int = 0, limit: int = 100) -> str:
        return await self._sandbox_file_ops.file_read(session_id, path, offset=offset, limit=limit)

    async def file_read_bytes(
        self, session_id: str, path: str, *, max_bytes: int = READ_IMAGE_MAX_BYTES
    ) -> bytes | str:
        return await self._sandbox_file_ops.file_read_bytes(session_id, path, max_bytes=max_bytes)

    async def file_write(self, session_id: str, path: str, content: str) -> ExecResult:
        return await self._sandbox_file_ops.file_write(session_id, path, content)

    async def file_str_replace(
        self,
        session_id: str,
        path: str,
        old_string: str,
        new_string: str,
        *,
        replace_all: bool = False,
    ) -> ExecResult:
        return await self._sandbox_file_ops.file_str_replace(
            session_id,
            path,
            old_string,
            new_string,
            replace_all=replace_all,
        )

    # Downloads return their data on stdout, so the command stays short. Every chunk is a
    # full exec round trip (~0.3 s per chunk through send_file on Kubernetes), so they stay large.
    _DOWNLOAD_CHUNK_BYTES = 4 * 1024 * 1024
    _UPLOAD_READ_BYTES = 1024 * 1024

    async def upload_tmp_file(
        self,
        session_id: str,
        filename: str,
        read_chunk: Callable[[int], Awaitable[bytes]],
        *,
        max_bytes: int,
    ) -> str:
        """Write an uploaded file into the sandbox ``/tmp`` and return its absolute path.

        Reads all of *read_chunk* (e.g. ``UploadFile.read``) and pipes it into the sandbox on
        the stdin of a single exec. If ``/tmp/<name>`` already exists a short hash is inserted
        before the extension to avoid collisions. Raises ``UploadTooLargeError`` past
        *max_bytes* and ``UploadError`` on a write failure, removing any partial file first.
        """
        base = os.path.basename(filename).strip() or "upload"
        stem, suffix = os.path.splitext(base)
        if not stem:
            stem, suffix = suffix, ""

        data = bytearray()
        while chunk := await read_chunk(self._UPLOAD_READ_BYTES):
            data += chunk
            if len(data) > max_bytes:
                raise UploadTooLargeError(f"File exceeds {max_bytes} bytes")

        target = f"/tmp/{stem}{suffix}"
        probe = await self.exec_command(session_id, f"test -e {shlex.quote(target)} && echo EXISTS || true", timeout=10)
        if "EXISTS" in probe.output:
            target = f"/tmp/{stem}-{secrets.token_hex(4)}{suffix}"
        qpath = shlex.quote(target)
        result = await self._exec(
            session_id, f"cat > {qpath} || {{ rm -f {qpath}; exit 1; }}", timeout=120, stdin=bytes(data)
        )
        if result.exit_code != 0:
            raise UploadError(f"Failed to write upload to sandbox: {result.output}")
        return target

    async def download_tmp_file(self, session_id: str, path: str, dest: Path, *, max_bytes: int) -> int:
        """Stream a sandbox file out to *dest* on the server and return its byte size.

        Reverse of :meth:`upload_tmp_file`: reads the file in chunks via
        ``tail -c +N | head -c M | base64`` (portable, no exec stdin) and base64-decodes
        each chunk server-side. Raises ``UploadError`` when the file is missing or a read
        fails, and ``UploadTooLargeError`` past *max_bytes*.
        """
        qpath = shlex.quote(path)
        probe = await self.exec_command(
            session_id, f"test -f {qpath} && stat -c %s {qpath} || echo MISSING", timeout=10
        )
        out = probe.output.strip()
        if probe.exit_code != 0 or not out.isdigit():
            raise UploadError(f"File not found in sandbox: {path}")
        size = int(out)
        if size > max_bytes:
            raise UploadTooLargeError(f"File exceeds {max_bytes} bytes")

        chunk = self._DOWNLOAD_CHUNK_BYTES
        offset = 0
        with open(dest, "wb") as fh:
            while offset < size:
                cmd = f"tail -c +{offset + 1} {qpath} | head -c {chunk} | base64"
                result = await self.exec_command(session_id, cmd, timeout=120)
                if result.exit_code != 0 or "[stderr]" in result.output:
                    # The output can hold megabytes of base64 ahead of the stderr that explains the failure.
                    raise UploadError(f"Failed to read file from sandbox: {result.output[-_READ_ERROR_TAIL_CHARS:]}")
                data = base64.b64decode(result.output)
                if not data:
                    break
                fh.write(data)
                offset += len(data)
        if offset != size:
            raise UploadError(f"Short read from sandbox: got {offset} of {size} bytes for {path}")
        return size

    async def cleanup_session(self, session_id: str) -> None:
        sc = self._sessions.get(session_id)
        if sc is not None:
            try:
                await self.refresh_sandbox_snapshot(session_id, measure_usage=True, container_id=sc.container_id)
            except Exception:
                logger.exception(f"Failed to refresh sandbox snapshot before cleanup for session {session_id}")
        await self._session_lifecycle.cleanup_session(session_id)
        try:
            await self.refresh_sandbox_snapshot(session_id)
        except Exception:
            logger.exception(f"Failed to refresh sandbox snapshot after cleanup for session {session_id}")

    async def destroy_session(self, session_id: str) -> None:
        await self._session_lifecycle.destroy_session(session_id)
        clear_sandbox_snapshot(self._session_factory, session_id)

    async def reset_session(self, session_id: str) -> None:
        await self._session_lifecycle.reset_session(session_id)
        save_sandbox_snapshot(
            self._session_factory,
            session_id,
            SessionSandboxSnapshot(
                runtime=self._runtime.runtime_kind,
                updated_at=datetime.now(tz=UTC),
            ),
        )

    async def cleanup_idle(self) -> None:
        await self._session_lifecycle.cleanup_idle(self.cleanup_session)

    async def cleanup_all(self) -> None:
        await self._session_lifecycle.cleanup_all(self.cleanup_session)

    async def verify_no_direct_egress(self, resolv_conf: Path) -> None:
        await self._session_lifecycle.verify_no_direct_egress(resolv_conf)

    async def cleanup_orphaned_sandboxes(self, known_sessions: set[str]) -> int:
        return await self._session_lifecycle.cleanup_orphaned_sandboxes(known_sessions)

    def set_session_env(self, session_id: str, env: dict[str, str]) -> None:
        self._session_lifecycle.set_session_env(session_id, env)

    def get_session_env(self, session_id: str) -> dict[str, str]:
        return self._session_lifecycle.get_session_env(session_id)

    def verify_session_token(self, session_id: str, token: str) -> bool:
        return self._session_lifecycle.verify_session_token(session_id, token)

    def get_domain_info(self, session_id: str) -> list[dict[str, str]]:
        return self._exec_coordinator.get_domain_info(session_id)

    def get_effective_domains(self, session_id: str) -> set[str]:
        return self._exec_coordinator.get_effective_domains(session_id)

    def mark_credential_notified(self, session_id: str, vault_path: str) -> bool:
        return self._exec_coordinator.mark_credential_notified(session_id, vault_path)

    def running_exec(self, session_id: str) -> RunningExec | None:
        return self._exec_coordinator.running_exec(session_id)

    async def open_tunnels(self, running: RunningExec, tunnels: list[Tunnel]) -> str | None:
        """Open *tunnels* until the running exec ends; why they could not be opened, or None.

        Raises ``ExecEndedError`` when the exec ended first.
        """
        return await self._exec_coordinator.open_tunnels(running, tunnels)

    def is_running(self, running: RunningExec) -> bool:
        return self._exec_coordinator.is_running(running)

    def notify_domain_access(self, session_id: str, domain: str, allowed: bool, refusal: str | None = None) -> None:
        self._exec_coordinator.notify_domain_access(session_id, domain, allowed, refusal)

    # ------------------------------------------------------------------
    # Proxy domain approval
    # ------------------------------------------------------------------

    def set_domain_approval_callback(
        self, session_id: str, cb: Callable[[str, RunningExec], Awaitable[BoundaryEvaluation]] | None
    ) -> None:
        self._exec_coordinator.set_domain_approval_callback(session_id, cb)

    def set_domain_notify_callback(
        self,
        session_id: str,
        cb: Callable[[str, str, ApprovalSource | None, ApprovalVerdict | None, str | None], None] | None,
    ) -> None:
        self._exec_coordinator.set_domain_notify_callback(session_id, cb)

    async def request_domain_approval(self, session_id: str, domain: str) -> BoundaryEvaluation:
        return await self._exec_coordinator.request_domain_approval(session_id, domain)

    def _cleanup_tracking(
        self,
        session_id: str,
    ) -> None:
        self._session_lifecycle.cleanup_tracking(session_id)
        self._exec_coordinator.cleanup_tracking(session_id)
