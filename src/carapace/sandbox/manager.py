from __future__ import annotations

import asyncio
import base64
import re
import secrets
import shlex
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

from loguru import logger
from pydantic import BaseModel

from carapace.sandbox.container_scripts import (
    SANDBOX_STR_REPLACE_SCRIPT as _STR_REPLACE_SCRIPT,
)
from carapace.sandbox.container_scripts import (
    build_file_read_script,
)
from carapace.sandbox.runtime import (
    ContainerGoneError,
    ContainerRuntime,
    ExecResult,
    SandboxConfig,
    SkillVenvError,
)
from carapace.security.context import ApprovalSource, ApprovalVerdict

_SKILL_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")

# Maximum characters returned for a single text file read (body only; headers are extra).
MAX_READ_OUTPUT_CHARS = 65536
# Maximum ``limit`` (line window) accepted by the agent read tool.
READ_TOOL_MAX_LINE_WINDOW = 1000
# Printed between read-tool metadata and file body (agents/UI can split on this line).
SANDBOX_READ_BODY_SEPARATOR = "-" * 24


def _shell_path(path: str, *, quote: bool) -> str:
    """Return a shell-safe path, expanding ``~/`` inside the shell when needed."""
    if path.startswith("~/"):
        suffix = path[2:]
        if quote:
            # Keep $HOME unquoted so shell expands it; quote only the suffix.
            return "$HOME/" if not suffix else f"$HOME/{shlex.quote(suffix)}"
        return f'"$HOME/{suffix}"'
    return shlex.quote(path) if quote else f'"{path}"'


def _file_write_shell_command(path: str, content: str, *, mode: int | None, quote: bool) -> str:
    shell_path = _shell_path(path, quote=quote)
    content_b64 = base64.b64encode(content.encode()).decode()
    cmd = f'mkdir -p "$(dirname {shell_path})" && printf %s {content_b64} | base64 -d > {shell_path}'
    if mode is not None:
        cmd += f" && chmod {mode:04o} {shell_path}"
    return cmd


def _line_count(content: str) -> int:
    if not content:
        return 0
    return content.count("\n") + 1


FILE_READ_SCRIPT = build_file_read_script(SANDBOX_READ_BODY_SEPARATOR)


class SessionContainer(BaseModel):
    container_id: str
    session_id: str
    ip_address: str | None = None
    created_at: float
    last_used: float
    session_env: dict[str, str] = {}


def _validate_skill_name(skill_name: str) -> str | None:
    """Return an error message if ``skill_name`` is not a safe directory name; ``None`` if valid.

    Must be nonempty, start with an alphanumeric character, and contain only
    alphanumerics, hyphens, underscores, or dots.
    """
    if not skill_name or not _SKILL_NAME_RE.match(skill_name):
        return f"Invalid skill name: {skill_name!r}"
    return None


class SandboxManager:
    def __init__(
        self,
        runtime: ContainerRuntime,
        data_dir: Path,
        knowledge_dir: Path,
        base_image: str = "carapace-sandbox:latest",
        network_name: str = "carapace-sandbox",
        idle_timeout_minutes: int = 15,
        proxy_port: int = 3128,
        sandbox_port: int = 8322,
        git_author: str = "Carapace <carapace@%h>",
    ) -> None:
        self._runtime = runtime
        self._data_dir = data_dir
        self._knowledge_dir = knowledge_dir
        self._git_author = git_author
        self._base_image = base_image
        self._network_name = network_name
        self._idle_timeout = idle_timeout_minutes * 60
        self._proxy_port = proxy_port
        self._sandbox_port = sandbox_port
        self._sessions: dict[str, SessionContainer] = {}
        self._token_to_session: dict[str, str] = {}
        self._session_tokens: dict[str, str] = {}
        self._allowed_domains: dict[str, set[str]] = {}
        self._exec_temp_domains: dict[str, set[str]] = {}  # session_id -> domains, cleared after each exec
        self._exec_context_skill_domains: dict[str, set[str]] = {}  # skill-sourced subset of exec_temp_domains
        self._session_current_command: dict[str, str] = {}
        self._domain_approval_cbs: dict[str, Callable[[str, str], Awaitable[bool]]] = {}
        self._domain_notify_cbs: dict[
            str,
            Callable[[str, str, ApprovalSource | None, ApprovalVerdict | None, str | None], None],
        ] = {}
        self._exec_locks: dict[str, asyncio.Lock] = {}
        self._proxy_bypass_sessions: set[str] = set()
        self._stashed_session_env: dict[str, dict[str, str]] = {}
        self._credential_cache: dict[str, dict[str, str]] = {}  # session_id -> {vault_path: value}
        self._session_current_contexts: dict[str, list[str]] = {}
        self._exec_notified_domains: dict[str, set[str]] = {}  # dedupe silent-allow domain UI notifications
        self._exec_notified_credentials: dict[str, set[str]] = {}  # dedupe credential UI notifications
        self._get_activated_skills_cb: Callable[[str], list[str]] | None = None
        self._reinject_credentials_cb: Callable[[str, str], Awaitable[list[tuple[str, str]]]] | None = None
        logger.info(
            f"SandboxManager initialized (image={base_image}, "
            + f"network={network_name}, proxy_port={proxy_port}, idle_timeout={idle_timeout_minutes}m)"
        )

    def set_activated_skills_callback(self, cb: Callable[[str], list[str]]) -> None:
        """Register a callback to retrieve activated skills for a session (from persisted state)."""
        self._get_activated_skills_cb = cb

    def set_reinject_credentials_callback(self, cb: Callable[[str, str], Awaitable[list[tuple[str, str]]]]) -> None:
        """Register a callback to retrieve file credentials for re-injection."""
        self._reinject_credentials_cb = cb

    def _get_or_create_token(self, session_id: str) -> str:
        """Return the proxy token for *session_id*, loading or creating as needed.

        Order: in-memory → on-disk file → generate new.
        The result is always written back to memory and disk.
        """
        token = self._session_tokens.get(session_id)
        if token:
            return token

        token_path = self._data_dir / "sessions" / session_id / "token"
        if token_path.exists():
            token = token_path.read_text().strip()
            logger.debug(f"Restored token for session {session_id} from disk")
        else:
            token = secrets.token_hex(16)
            token_path.parent.mkdir(parents=True, exist_ok=True)
            token_path.write_text(token)

        self._session_tokens[session_id] = token
        self._token_to_session[token] = session_id
        return token

    async def _log_container_tail(self, container_id: str, session_id: str) -> None:
        """Log the last lines of a dead/stopped container for troubleshooting."""
        try:
            tail = await self._runtime.logs(container_id)
            if tail and tail.strip():
                logger.info(f"Last logs from container {container_id[:12]} (session {session_id}):\n{tail}")
        except Exception:
            logger.opt(exception=True).warning(f"Could not retrieve logs from container {container_id[:12]}")

    def _get_exec_lock(self, session_id: str) -> asyncio.Lock:
        if session_id not in self._exec_locks:
            self._exec_locks[session_id] = asyncio.Lock()
        return self._exec_locks[session_id]

    async def ensure_session(self, session_id: str) -> tuple[SessionContainer, bool]:
        """Return ``(container, was_created)`` — *was_created* is True when a new container was spun up."""
        sandbox_name = self._sandbox_name(session_id)

        if session_id in self._sessions:
            sc = self._sessions[session_id]
            if await self._runtime.is_running(sc.container_id):
                logger.debug(f"Reusing existing container {sc.container_id[:12]} for session {session_id}")
                sc.last_used = time.time()
                return sc, False
            # Container not running — try to resume (K8s scales up, Docker raises)
            try:
                await self._runtime.resume_sandbox(sandbox_name)
                sc.last_used = time.time()
                await self._wait_for_ready(sc.container_id, session_id)
                logger.info(f"Resumed sandbox {sandbox_name} for session {session_id}")
                return sc, False
            except Exception:
                logger.opt(exception=True).debug(f"Resume failed for {sandbox_name}, will recreate")
            await self._log_container_tail(sc.container_id, session_id)
            self._prepare_session_recreate(session_id)
        else:
            # No in-memory state (e.g. after server restart) — check if the
            # sandbox resource still exists in the runtime and try to resume it.
            existing_id = await self._runtime.sandbox_exists(sandbox_name)
            if existing_id:
                try:
                    if await self._runtime.is_running(existing_id):
                        logger.info(f"Re-attached to running sandbox {sandbox_name} for session {session_id}")
                    else:
                        await self._runtime.resume_sandbox(sandbox_name)
                        await self._wait_for_ready(existing_id, session_id)
                        logger.info(f"Resumed orphaned sandbox {sandbox_name} for session {session_id}")
                    ip = await self._runtime.get_ip(existing_id, self._network_name)
                    sc = SessionContainer(
                        container_id=existing_id,
                        session_id=session_id,
                        ip_address=ip,
                        created_at=time.time(),
                        last_used=time.time(),
                    )
                    self._sessions[session_id] = sc
                    return sc, False
                except Exception:
                    logger.opt(exception=True).debug(
                        f"Failed to re-attach/resume orphaned sandbox {sandbox_name}, will recreate"
                    )

        proxy_token = self._get_or_create_token(session_id)
        try:
            host_ip = await self._runtime.get_host_ip(self._network_name)
            if not host_ip:
                raise RuntimeError(
                    f"Cannot create sandbox for session {session_id}: "
                    f"no IP found on network '{self._network_name}'. "
                    "Is the proxy network configured correctly?"
                )
            proxy_url = f"http://{host_ip}:{self._proxy_port}"
            logger.info(f"Proxy URL for session {session_id}: {proxy_url}")

            env = self._build_proxy_env(session_id, proxy_token, proxy_url)
            command: list[str] = [
                "sh",
                "-c",
                "setup-proxy.sh && echo 'carapace sandbox ready' && exec sleep infinity",
            ]

            sandbox_config = SandboxConfig(
                name=sandbox_name,
                session_id=session_id,
                image=self._base_image,
                labels={"carapace.session": session_id, "carapace.managed": "true"},
                environment=env,
                command=command,
            )
            container_id = await self._runtime.create_sandbox(sandbox_config)

            ip = await self._runtime.get_ip(container_id, self._network_name)

            # Wait for the container to finish setup (proxy config etc.)
            # before running the git clone as a separate exec.
            await self._wait_for_ready(container_id, session_id)
            await self._clone_knowledge_repo(container_id, session_id)
        except BaseException:
            self._cleanup_tracking(session_id)
            raise

        sc = SessionContainer(
            container_id=container_id,
            session_id=session_id,
            ip_address=ip,
            created_at=time.time(),
            last_used=time.time(),
        )
        stashed_env = self._stashed_session_env.pop(session_id, None)
        if stashed_env:
            sc.session_env.update(stashed_env)
        self._sessions[session_id] = sc
        logger.info(f"Created sandbox container {container_id[:12]} for session {session_id} (IP: {ip})")
        return sc, True

    def _sandbox_name(self, session_id: str) -> str:
        """Derive the sandbox resource name for a session."""
        return f"carapace-sandbox-{session_id}"

    _READY_MARKER = "carapace sandbox ready"

    async def _wait_for_ready(self, container_id: str, session_id: str) -> None:
        """Poll container logs until the ready marker appears (up to 30s)."""
        for _ in range(30):
            log_output = await self._runtime.logs(container_id, tail=10)
            if self._READY_MARKER in log_output:
                return
            await asyncio.sleep(1)
        logger.warning(f"Sandbox for {session_id} did not become ready within 30s")

    async def _clone_knowledge_repo(self, container_id: str, session_id: str) -> None:
        """Clone the knowledge repo into the sandbox if not already present."""
        probe = await self._runtime.exec(
            container_id,
            "test -d /workspace/.git",
            timeout=5,
        )
        if probe.exit_code == 0:
            logger.debug(f"Knowledge repo already present in sandbox for {session_id}")
            return
        result = await self._runtime.exec(
            container_id,
            "git clone $GIT_REPO_URL /workspace",
            timeout=60,
        )
        if result.exit_code != 0:
            raise RuntimeError(
                f"Git clone failed in sandbox for {session_id} (exit {result.exit_code}): {result.output}"
            )

        await self._setup_git_identity(container_id, session_id)
        await self._install_commit_msg_hook(container_id, session_id)

    async def _setup_git_identity(self, container_id: str, session_id: str) -> None:
        """Configure git user.name and user.email inside the sandbox.

        Placeholders ``%s`` (session ID) are resolved server-side;
        ``%h`` is resolved inside the container via ``$(hostname)``.
        """
        # Resolve %s server-side, leave %h for shell expansion
        name_tpl = self._git_author.replace("%s", session_id)
        # Parse "Name <email>" format
        if "<" in name_tpl and name_tpl.endswith(">"):
            name, _, email = name_tpl.rpartition("<")
            name, email = name.strip(), email.rstrip(">").strip()
        else:
            name, email = name_tpl, f"{session_id}@carapace"
        # Shell-expand %h via $(hostname) inside the container
        name_sh = name.replace("%h", "$(hostname)")
        email_sh = email.replace("%h", "$(hostname)")
        cmd = f'git -C /workspace config user.name "{name_sh}" && git -C /workspace config user.email "{email_sh}"'
        await self._runtime.exec(container_id, cmd, timeout=10)

    _COMMIT_TRAILER_KEY = "Carapace-Session"

    async def _install_commit_msg_hook(self, container_id: str, session_id: str) -> None:
        """Install a commit-msg hook that appends a session trailer to commits."""
        key = self._COMMIT_TRAILER_KEY
        # The hook appends the trailer only if not already present.
        hook = (
            "#!/bin/sh\n"
            f'if ! grep -q "^{key}:" "$1"; then\n'
            f'  echo "" >> "$1"\n'
            f'  echo "{key}: $CARAPACE_SESSION_ID" >> "$1"\n'
            "fi\n"
        )
        cmd = (
            "mkdir -p /workspace/.git/hooks && "
            f"printf '%s' '{hook}' > /workspace/.git/hooks/commit-msg && "
            "chmod +x /workspace/.git/hooks/commit-msg"
        )
        await self._runtime.exec(container_id, cmd, timeout=10)

    def _build_proxy_env(self, session_id: str, proxy_token: str, proxy_url: str) -> dict[str, str]:
        """Build HTTP_PROXY / NO_PROXY env vars for session containers."""
        if not proxy_url:
            return {}
        # Embed credentials as session_id:token (standard Basic Auth)
        scheme, rest = proxy_url.split("://", 1)
        authed_url = f"{scheme}://{session_id}:{proxy_token}@{rest}"
        # Extract host (without scheme/port/auth) for NO_PROXY
        no_proxy_host = rest.rsplit(":", 1)[0]
        no_proxy = ",".join([no_proxy_host, "localhost", "127.0.0.1"])
        # Git clone URL — points at the API server (Basic Auth)
        git_url = (
            f"{scheme}://{session_id}:{proxy_token}@{no_proxy_host}:{self._sandbox_port}/git/{self._knowledge_dir.name}"
        )
        return {
            "HTTP_PROXY": authed_url,
            "HTTPS_PROXY": authed_url,
            "http_proxy": authed_url,
            "https_proxy": authed_url,
            "ALL_PROXY": authed_url,
            "NO_PROXY": no_proxy,
            "no_proxy": no_proxy,
            # pip: explicit proxy (maps to pip --proxy)
            "PIP_PROXY": authed_url,
            # npm / node-based tools
            "npm_config_proxy": authed_url,
            "npm_config_https_proxy": authed_url,
            # Git knowledge repo URL (cloned during sandbox setup)
            "GIT_REPO_URL": git_url,
            # Carapace API base URL (used by ccred and other sandbox-side tools)
            "CARAPACE_API_URL": f"{scheme}://{session_id}:{proxy_token}@{no_proxy_host}:{self._sandbox_port}",
            # Session ID (used by the commit-msg hook for trailers)
            "CARAPACE_SESSION_ID": session_id,
        }

    async def _exec_in_container(
        self,
        sc: SessionContainer,
        command: str,
        timeout: int = 30,
        *,
        bypass_proxy: bool = False,
        workdir: str | None = None,
        extra_env: dict[str, str] | None = None,
    ) -> ExecResult:
        """Run *command* in *sc* without acquiring the exec lock.

        When *bypass_proxy* is True, the bypass window covers only this call.
        Callers running under ``_exec`` with bypass already enabled must pass
        ``bypass_proxy=False`` so the session is not added to the set twice.

        *extra_env* is merged on top of the session env for this single exec
        (used for per-exec credential injection via contexts).
        """
        if bypass_proxy:
            self._proxy_bypass_sessions.add(sc.session_id)
            logger.info(f"Proxy bypass ENABLED for session {sc.session_id}")
        try:
            env = sc.session_env or None
            if extra_env:
                env = {**(sc.session_env or {}), **extra_env}
            return await self._runtime.exec(
                sc.container_id,
                command,
                timeout=timeout,
                workdir=workdir,
                env=env,
            )
        finally:
            if bypass_proxy:
                self._proxy_bypass_sessions.discard(sc.session_id)
                logger.info(f"Proxy bypass DISABLED for session {sc.session_id}")

    async def _exec(
        self,
        session_id: str,
        command: str,
        timeout: int = 30,
        *,
        bypass_proxy: bool = False,
        workdir: str | None = None,
        contexts: list[str] | None = None,
        extra_env: dict[str, str] | None = None,
        context_domains: set[str] | None = None,
        context_file_creds: list[tuple[str, str, str]] | None = None,
        after_exec_credential_notify: Callable[[], None] | None = None,
    ) -> ExecResult:
        """Run a command in the sandbox and return the raw ExecResult.

        When *bypass_proxy* is True, all proxy domains are temporarily allowed
        for the duration of this exec (used during venv builds).  The bypass
        flag is set/cleared **under the exec lock** so no concurrent command
        can exploit the open window.

        *contexts*: activated skill names active for this exec.
        *extra_env*: per-exec env vars (credential values).
        *context_domains*: skill-declared domains to add to exec-scoped temp allowlist.
        *context_file_creds*: ``(skill_name, file_path, vault_path)`` tuples; files
            are written before the command and deleted in the ``finally`` block.
        *after_exec_credential_notify*: optional sync hook invoked after the container
            command finishes but **before** per-exec notification state is torn down,
            so UI dedupe via `mark_credential_notified` still applies.
        """
        contexts = contexts or []
        written_files: list[tuple[str, str]] = []  # (file_path, skill_name)

        async with self._get_exec_lock(session_id):
            if bypass_proxy:
                self._proxy_bypass_sessions.add(session_id)
                logger.info(f"Proxy bypass ENABLED for session {session_id}")
            try:
                sc, was_created = await self.ensure_session(session_id)
                if was_created:
                    await self._rebuild_skill_venvs(session_id)
                sc.last_used = time.time()
                logger.debug(f"Exec in session {session_id}: {command}")

                self._session_current_command[session_id] = command
                self._session_current_contexts[session_id] = contexts
                self._exec_temp_domains[session_id] = set()
                self._exec_context_skill_domains[session_id] = set()
                self._exec_notified_domains[session_id] = set()
                self._exec_notified_credentials[session_id] = set()

                # Add context-scoped domains to exec-temp allowlist
                if context_domains:
                    self._exec_temp_domains[session_id].update(context_domains)
                    self._exec_context_skill_domains[session_id].update(context_domains)

                try:
                    # Write file-based credentials + run the command
                    if context_file_creds:
                        written_files = await self._write_context_file_credentials(sc, context_file_creds)
                    exec_result = await self._exec_in_container(
                        sc, command, timeout, workdir=workdir, bypass_proxy=False, extra_env=extra_env
                    )
                except ContainerGoneError:
                    logger.warning(f"Container gone for session {session_id}, recreating sandbox")
                    await self._log_container_tail(sc.container_id, session_id)
                    self._prepare_session_recreate(session_id)
                    sc, _ = await self.ensure_session(session_id)
                    await self._rebuild_skill_venvs(session_id)

                    # Re-write file credentials after container recreation
                    written_files.clear()
                    if context_file_creds:
                        written_files = await self._write_context_file_credentials(sc, context_file_creds)
                    exec_result = await self._exec_in_container(
                        sc, command, timeout, workdir=workdir, bypass_proxy=False, extra_env=extra_env
                    )

                if after_exec_credential_notify is not None:
                    after_exec_credential_notify()
                return exec_result
            finally:
                if bypass_proxy:
                    self._proxy_bypass_sessions.discard(session_id)
                    logger.info(f"Proxy bypass DISABLED for session {session_id}")
                self._session_current_command.pop(session_id, None)
                self._session_current_contexts.pop(session_id, None)
                self._exec_temp_domains.pop(session_id, None)
                self._exec_context_skill_domains.pop(session_id, None)
                self._exec_notified_domains.pop(session_id, None)
                self._exec_notified_credentials.pop(session_id, None)

                # Delete file-based credentials written for this exec
                if written_files:
                    await self._delete_context_file_credentials(session_id, written_files)

    _KNOWLEDGE_WORKDIR = "/workspace"

    async def exec_command(
        self,
        session_id: str,
        command: str,
        timeout: int = 3600,
        *,
        contexts: list[str] | None = None,
        extra_env: dict[str, str] | None = None,
        context_domains: set[str] | None = None,
        context_file_creds: list[tuple[str, str, str]] | None = None,
        after_exec_credential_notify: Callable[[], None] | None = None,
    ) -> ExecResult:
        """Run a command in the sandbox and return the result.

        *contexts*: activated skill names active for this exec.
        *extra_env*: per-exec env vars (credential values) — merged on top of session env.
        *context_domains*: domains to add to exec-scoped temp allowlist.
        *context_file_creds*: ``(skill_name, file_path, vault_path)`` tuples for file-based
            credentials to be written before exec and deleted after.
        *after_exec_credential_notify*: passed through to `_exec` (see there).
        """
        result = await self._exec(
            session_id,
            command,
            timeout=timeout,
            workdir=self._KNOWLEDGE_WORKDIR,
            contexts=contexts,
            extra_env=extra_env,
            context_domains=context_domains,
            context_file_creds=context_file_creds,
            after_exec_credential_notify=after_exec_credential_notify,
        )
        output = result.output
        if result.exit_code != 0 and f"[exit code: {result.exit_code}]" not in output:
            logger.debug(f"Command failed in session {session_id} (exit {result.exit_code}): {command}")
            output += f"\n[exit code: {result.exit_code}]"
        return ExecResult(exit_code=result.exit_code, output=output or "(no output)")

    # ------------------------------------------------------------------
    # File operations (executed inside the sandbox container via
    # shell commands and small inline Python snippets).
    # Data is passed as base64 CLI args to avoid shell-escaping issues.
    # ------------------------------------------------------------------

    async def file_read(self, session_id: str, path: str, *, offset: int = 0, limit: int = 100) -> str:
        """Read a text file (windowed), summarize a binary file, or list a directory inside the sandbox."""
        pq = shlex.quote(path)
        cmd = f"python3 -c {shlex.quote(FILE_READ_SCRIPT)} {pq} {int(offset)} {int(limit)} {MAX_READ_OUTPUT_CHARS}"
        result = await self._exec(session_id, cmd, timeout=30)
        if result.exit_code != 0:
            return result.output or f"Error: cannot read {path}"
        output = result.output
        if output.startswith("::DIR::\n"):
            return f"Directory listing of {path}/:\n" + output[len("::DIR::\n") :]
        return output or "(empty file)"

    async def file_write(
        self,
        session_id: str,
        path: str,
        content: str,
        *,
        mode: int | None = None,
        workdir: str | None = None,
        quote: bool = True,
    ) -> ExecResult:
        """Write content to a file inside the sandbox."""
        cmd = _file_write_shell_command(path, content, mode=mode, quote=quote)
        result = await self._exec(session_id, cmd, timeout=10, workdir=workdir)
        if result.exit_code != 0:
            output = result.output or f"Error: cannot write {path} (exit {result.exit_code})."
            return ExecResult(exit_code=result.exit_code, output=output)
        lines = _line_count(content)
        return ExecResult(exit_code=0, output=f"Wrote {lines} line(s) to {path}.")

    async def file_str_replace(
        self,
        session_id: str,
        path: str,
        old_string: str,
        new_string: str,
        *,
        replace_all: bool = False,
    ) -> ExecResult:
        """Replace text in a file inside the sandbox, optionally replacing all matches."""
        pq = shlex.quote(path)
        old_b64 = base64.b64encode(old_string.encode()).decode()
        new_b64 = base64.b64encode(new_string.encode()).decode()
        replace_all_flag = "1" if replace_all else "0"
        cmd = f"python3 -c {shlex.quote(_STR_REPLACE_SCRIPT)} {pq} {old_b64} {new_b64} {replace_all_flag}"
        result = await self._exec(session_id, cmd, timeout=10)
        output = result.output or f"Error: cannot replace in {path}"
        return ExecResult(exit_code=result.exit_code, output=output)

    async def activate_skill(self, session_id: str, skill_name: str) -> str:
        if err := _validate_skill_name(skill_name):
            return err

        await self.ensure_session(session_id)

        # Check that the skill exists in the server-side knowledge store.
        # The sandbox already has it at /workspace/skills/{name} via git clone.
        master_skill_dir = self._knowledge_dir / "skills" / skill_name
        if not master_skill_dir.exists():
            logger.warning(f"Skill '{skill_name}' not found for session {session_id}")
            return f"Skill '{skill_name}' not found."

        has_pyproject = (master_skill_dir / "pyproject.toml").exists()
        venv_msg = ""
        if has_pyproject:
            try:
                await self._build_skill_venv(session_id, skill_name)
                venv_msg = "Venv built successfully."
            except SkillVenvError as exc:
                logger.info(f"Activated skill '{skill_name}' in session {session_id} (with errors)")
                raise SkillVenvError(
                    f"Skill '{skill_name}' activated at /workspace/skills/{skill_name}/ but "
                    f"dependency install failed: {exc}\n"
                    "The skill is available but its Python dependencies are NOT installed. "
                    "You may need to install them manually inside the sandbox."
                ) from exc

        logger.info(f"Activated skill '{skill_name}' in session {session_id}")
        parts = [f"Skill '{skill_name}' activated at /workspace/skills/{skill_name}/"]
        if venv_msg:
            parts.append(venv_msg)
        return "\n".join(parts)

    async def _build_skill_venv(self, session_id: str, skill_name: str) -> None:
        """Build a skill venv inside the session container with proxy bypass.

        Runs ``uv sync`` inside the session container.  The proxy is temporarily
        bypassed (all domains allowed) for the duration of the install.
        """
        await self._build_skill_venv_in_session(skill_name, session_id=session_id)

    async def _build_skill_venv_in_session(
        self,
        skill_name: str,
        *,
        session_id: str | None = None,
        sc: SessionContainer | None = None,
    ) -> None:
        """Shared venv build: either via ``_exec`` (lock + ensure_session) or on a known *sc*."""
        if (session_id is None) == (sc is None):
            raise ValueError("Exactly one of session_id and sc must be set")

        if err := _validate_skill_name(skill_name):
            raise SkillVenvError(err)

        if session_id is not None:
            sid = session_id
        else:
            assert sc is not None
            sid = sc.session_id

        logger.info(f"Building venv for skill '{skill_name}' (session {sid})")
        skill_dir = f"/workspace/skills/{shlex.quote(skill_name)}"
        cmd = f"uv sync --directory {skill_dir}"
        if session_id is not None:
            result = await self._exec(session_id, cmd, timeout=120, bypass_proxy=True)
        else:
            assert sc is not None
            result = await self._exec_in_container(sc, cmd, timeout=120, bypass_proxy=True)
        if result.exit_code != 0:
            logger.error(f"Venv build failed for skill '{skill_name}' (exit {result.exit_code}): {result.output[:300]}")
            raise SkillVenvError(f"exit {result.exit_code}: {result.output[:500]}")
        logger.info(f"Venv built successfully for skill '{skill_name}'")

    async def _file_write_in_container(
        self,
        sc: SessionContainer,
        path: str,
        content: str,
        *,
        mode: int | None = None,
        workdir: str | None = None,
        quote: bool = True,
    ) -> ExecResult:
        """Write a file using an existing container while the exec lock is already held."""
        cmd = _file_write_shell_command(path, content, mode=mode, quote=quote)
        result = await self._exec_in_container(sc, cmd, timeout=10, workdir=workdir)
        if result.exit_code != 0:
            output = result.output or f"Error: cannot write {path} (exit {result.exit_code})."
            return ExecResult(exit_code=result.exit_code, output=output)
        lines = _line_count(content)
        return ExecResult(exit_code=0, output=f"Wrote {lines} line(s) to {path}.")

    async def _file_delete_in_container(
        self,
        sc: SessionContainer,
        path: str,
        *,
        workdir: str | None = None,
        quote: bool = True,
    ) -> ExecResult:
        """Delete a file using an existing container while the exec lock is already held."""
        shell_path = _shell_path(path, quote=quote)
        cmd = f"rm -f {shell_path}"
        return await self._exec_in_container(sc, cmd, timeout=5, workdir=workdir)

    async def _write_context_file_credentials(
        self,
        sc: SessionContainer,
        context_file_creds: list[tuple[str, str, str]],
    ) -> list[tuple[str, str]]:
        """Write file-based credentials into the container, returning written ``(file_path, skill_name)`` pairs."""
        written: list[tuple[str, str]] = []
        for skill_name, file_path, vault_path in context_file_creds:
            value = self.get_cached_credential(sc.session_id, vault_path)
            if value is None:
                logger.warning(f"Cached credential missing for {vault_path!r} (skill {skill_name!r}), skipping file")
                continue
            skill_dir = f"/workspace/skills/{skill_name}"
            fw = await self._file_write_in_container(sc, file_path, value, mode=0o400, workdir=skill_dir, quote=False)
            if fw.exit_code != 0:
                logger.error(f"Failed to write credential file {file_path} for {skill_name}: {fw.output}")
            else:
                written.append((file_path, skill_name))
        return written

    async def _delete_context_file_credentials(
        self,
        session_id: str,
        written_files: list[tuple[str, str]],
    ) -> None:
        """Delete file-based credentials that were written for an exec."""
        sc = self._sessions.get(session_id)
        if sc is None:
            return
        for file_path, skill_name in written_files:
            skill_dir = f"/workspace/skills/{skill_name}"
            try:
                dr = await self._file_delete_in_container(sc, file_path, workdir=skill_dir, quote=False)
            except Exception as exc:
                # Never let cleanup failures replace the exec's original exception (finally runs during unwind).
                logger.warning(f"Could not delete credential file {file_path} (skill {skill_name!r}) after exec: {exc}")
                continue
            if dr.exit_code != 0:
                logger.warning(
                    f"Failed to delete credential file {file_path} (skill {skill_name!r}) after exec: "
                    f"{dr.output or '(no output)'}"
                )

    async def _reinject_credential_files(self, sc: SessionContainer, skill_name: str) -> None:
        """Re-inject file-based credentials after container recreation.

        With context-scoped grants, file credentials are normally injected
        per-exec.  This method is kept as a fallback for container rebuilds
        that happen outside an exec context (e.g. venv rebuild).
        """
        if not self._reinject_credentials_cb:
            return
        credentials = await self._reinject_credentials_cb(sc.session_id, skill_name)
        if not credentials:
            return
        skill_dir = f"/workspace/skills/{skill_name}"
        for credential_file, credential_value in credentials:
            result = await self._file_write_in_container(
                sc,
                credential_file,
                credential_value,
                mode=0o400,
                workdir=skill_dir,
                quote=False,
            )
            if result.exit_code != 0:
                logger.error(
                    f"Failed to re-inject credential file {credential_file} for skill {skill_name}: {result.output}"
                )
                continue
            logger.info(f"Re-injected credential file {credential_file} for skill {skill_name}")

    async def _sync_skill_venv(self, sc: SessionContainer, skill_name: str) -> str:
        """Restore trusted skill config from git and rebuild the venv if needed."""
        master = self._knowledge_dir / "skills" / skill_name
        skill_path = f"skills/{shlex.quote(skill_name)}"

        # Restore committed config files inside the sandbox, preventing
        # the sandbox from tampering with credential/network declarations.
        for fname in ("carapace.yaml", "pyproject.toml", "uv.lock"):
            await self._exec_in_container(
                sc,
                f"git checkout HEAD -- {skill_path}/{fname} 2>/dev/null || true",
                timeout=10,
                workdir=self._KNOWLEDGE_WORKDIR,
            )

        venv_msg = ""
        if (master / "pyproject.toml").exists():
            await self._build_skill_venv_in_session(skill_name, sc=sc)
            venv_msg = "Venv rebuilt successfully."

        await self._reinject_credential_files(sc, skill_name)
        return venv_msg

    async def rebuild_skill_venvs(self, session_id: str, activated_skills: list[str]) -> None:
        """Restore trusted config and rebuild venvs for activated skills.

        Called by SessionEngine after container recreation.
        """
        sc = self._sessions.get(session_id)
        if sc is None:
            logger.warning(f"Cannot rebuild skill venvs: missing container state for session {session_id}")
            return
        for skill_name in activated_skills:
            logger.info(f"Syncing skill '{skill_name}' after container recreation")
            try:
                await self._sync_skill_venv(sc, skill_name)
            except SkillVenvError as exc:
                logger.error(f"Failed to rebuild venv for '{skill_name}': {exc}")

    async def _rebuild_skill_venvs(self, session_id: str) -> None:
        """Internal: rebuild venvs using the activated_skills callback (for _exec recreation)."""
        if not self._get_activated_skills_cb:
            return
        activated = self._get_activated_skills_cb(session_id)
        if activated:
            await self.rebuild_skill_venvs(session_id, activated)

    async def cleanup_session(self, session_id: str) -> None:
        """Suspend the sandbox — the runtime decides how (scale to 0 or remove).

        The entry is removed from ``self._sessions`` so ``cleanup_idle``
        does not re-suspend it every cycle.  ``ensure_session`` will
        rediscover the sandbox via ``sandbox_exists`` and resume it.
        """
        sc = self._sessions.pop(session_id, None)
        if sc:
            await self._runtime.suspend_sandbox(
                self._sandbox_name(session_id),
                sc.container_id,
            )
            logger.info(f"Suspended sandbox for session {session_id}")

    async def destroy_session(self, session_id: str) -> None:
        """Permanently remove the sandbox and all tracking state.

        The runtime decides how to destroy (delete STS + PVC, or remove
        container).  Unlike ``cleanup_session``, this purges tokens, domain
        allowlists, locks and other per-session bookkeeping.
        """
        sc = self._sessions.pop(session_id, None)
        sandbox_name = self._sandbox_name(session_id)
        if sc:
            await self._runtime.destroy_sandbox(sandbox_name, sc.container_id)
            logger.info(f"Destroyed sandbox for session {session_id}")
        else:
            existing_id = await self._runtime.sandbox_exists(sandbox_name)
            if existing_id:
                await self._runtime.destroy_sandbox(sandbox_name, existing_id)
                logger.info(f"Destroyed orphaned sandbox for session {session_id}")
        token = self._session_tokens.pop(session_id, None)
        if token:
            self._token_to_session.pop(token, None)
        self._allowed_domains.pop(session_id, None)
        self._exec_temp_domains.pop(session_id, None)
        self._exec_context_skill_domains.pop(session_id, None)
        self._session_current_command.pop(session_id, None)
        self._domain_approval_cbs.pop(session_id, None)
        self._domain_notify_cbs.pop(session_id, None)
        self._exec_locks.pop(session_id, None)
        self._proxy_bypass_sessions.discard(session_id)
        self._credential_cache.pop(session_id, None)
        self._session_current_contexts.pop(session_id, None)
        self._exec_notified_domains.pop(session_id, None)
        self._exec_notified_credentials.pop(session_id, None)

    async def reset_session(self, session_id: str) -> None:
        """Full sandbox reset: destroy and let ``ensure_session`` create a fresh one."""
        sc = self._sessions.pop(session_id, None)
        sandbox_name = self._sandbox_name(session_id)
        if sc:
            await self._runtime.destroy_sandbox(sandbox_name, sc.container_id)
            logger.info(f"Reset sandbox for session {session_id}")
        else:
            existing_id = await self._runtime.sandbox_exists(sandbox_name)
            if existing_id:
                await self._runtime.destroy_sandbox(sandbox_name, existing_id)
                logger.info(f"Reset orphaned sandbox for session {session_id}")

    async def cleanup_idle(self) -> None:
        """Remove containers that have been idle longer than the timeout.

        Only the container is destroyed; session state (tokens, domains)
        is preserved so the sandbox can be re-created on the next
        ``ensure_session`` call.
        """
        now = time.time()
        to_remove = [sid for sid, sc in self._sessions.items() if now - sc.last_used > self._idle_timeout]
        if to_remove:
            logger.info(f"Cleaning up {len(to_remove)} idle sandbox session(s)")
        for sid in to_remove:
            await self.cleanup_session(sid)

    async def cleanup_all(self) -> None:
        """Remove all sandbox containers (e.g. on server shutdown).

        Session state is preserved so sandboxes can be re-created after
        a restart.
        """
        count = len(self._sessions)
        if count:
            logger.info(f"Cleaning up all {count} sandbox session(s)")
        for sid in list(self._sessions):
            await self.cleanup_session(sid)

    async def cleanup_orphaned_sandboxes(self, known_sessions: set[str]) -> int:
        """Destroy sandbox resources whose session no longer exists on disk.

        Returns the number of orphans removed.
        """
        live = await self._runtime.list_sandboxes()
        orphans = {sid: cid for sid, cid in live.items() if sid not in known_sessions}
        for sid, container_id in orphans.items():
            sandbox_name = self._sandbox_name(sid)
            await self._runtime.destroy_sandbox(sandbox_name, container_id)
            logger.info(f"Removed orphaned sandbox for deleted session {sid}")
        return len(orphans)

    def set_session_env(self, session_id: str, env: dict[str, str]) -> None:
        """Merge *env* into the persistent session environment.

        Values are passed as ``env`` to every subsequent ``_exec()`` call
        so that credential-injected variables survive across commands.
        """
        sc = self._sessions.get(session_id)
        if sc:
            sc.session_env.update(env)

    def get_session_env(self, session_id: str) -> dict[str, str]:
        """Return a copy of the current session environment."""
        sc = self._sessions.get(session_id)
        return dict(sc.session_env) if sc else {}

    def verify_session_token(self, session_id: str, token: str) -> bool:
        """Return True if *token* is valid for *session_id*."""
        return self._token_to_session.get(token) == session_id

    def allow_domains(self, session_id: str, domains: set[str]) -> None:
        """Add *domains* to the proxy allowlist for *session_id*."""
        existing = self._allowed_domains.setdefault(session_id, set())
        existing.update(domains)
        logger.info(f"Allowed domains for session {session_id}: {existing}")

    def get_allowed_domains(self, session_id: str) -> set[str]:
        return self._allowed_domains.get(session_id, set())

    def get_domain_info(self, session_id: str) -> list[dict[str, str]]:
        """Return a list of allowed domain entries with their scope/expiry for display.

        Each entry has ``domain`` and ``scope``, where scope is one of:
        ``"permanent"`` or ``"exec"`` (current tool call only).
        """
        entries: list[dict[str, str]] = []
        for d in sorted(self._allowed_domains.get(session_id, set())):
            entries.append({"domain": d, "scope": "permanent"})
        for d in sorted(self._exec_temp_domains.get(session_id, set())):
            entries.append({"domain": d, "scope": "this exec only"})
        return entries

    def get_effective_domains(self, session_id: str) -> set[str]:
        """Return the union of permanent and current exec-scoped temp domains."""
        if session_id in self._proxy_bypass_sessions:
            return {"*"}
        domains = set(self._allowed_domains.get(session_id, set()))
        domains.update(self._exec_temp_domains.get(session_id, set()))
        return domains

    # ------------------------------------------------------------------
    # Credential cache (per-exec injection, not session_env)
    # ------------------------------------------------------------------

    def cache_credential(self, session_id: str, vault_path: str, value: str) -> None:
        """Store a credential value in memory for later per-exec injection."""
        self._credential_cache.setdefault(session_id, {})[vault_path] = value

    def get_cached_credential(self, session_id: str, vault_path: str) -> str | None:
        """Return a cached credential value, or *None* if not cached."""
        return self._credential_cache.get(session_id, {}).get(vault_path)

    def get_current_contexts(self, session_id: str) -> list[str]:
        """Return the contexts active for the current exec, if any."""
        return self._session_current_contexts.get(session_id, [])

    def is_domain_skill_granted(self, session_id: str, domain: str) -> bool:
        """Return True if *domain* is in the exec-scoped skill-granted set."""
        from carapace.sandbox.proxy import domain_matches

        skill_domains = self._exec_context_skill_domains.get(session_id, set())
        domain_lower = domain.lower()
        return any(domain_matches(domain_lower, p.lower()) for p in skill_domains)

    def is_domain_bypass(self, session_id: str) -> bool:
        """Return True if the session is currently in proxy bypass mode."""
        return session_id in self._proxy_bypass_sessions

    def mark_credential_notified(self, session_id: str, vault_path: str) -> bool:
        """Return True if *vault_path* was already notified in this exec; otherwise mark it."""
        notified = self._exec_notified_credentials.get(session_id)
        if notified is None:
            return False
        if vault_path in notified:
            return True
        notified.add(vault_path)
        return False

    def notify_domain_access(self, session_id: str, domain: str, allowed: bool) -> None:
        """Called by the proxy for silently allowed/denied domain accesses.

        Determines the approval source (skill, bypass, permanent allowlist)
        and fires the session's domain info callback.  Skill-granted and
        bypass domains are notified at most once per exec to avoid UI spam.
        """
        cb = self._domain_notify_cbs.get(session_id)
        if cb is None:
            return

        if allowed:
            if self.is_domain_bypass(session_id):
                notified = self._exec_notified_domains.get(session_id)
                if notified is not None and domain in notified:
                    return
                if notified is not None:
                    notified.add(domain)
                cb(domain, f"[bypass] {domain}", "bypass", "allow", "proxy bypass active")
            elif self.is_domain_skill_granted(session_id, domain):
                notified = self._exec_notified_domains.get(session_id)
                if notified is not None and domain in notified:
                    return
                if notified is not None:
                    notified.add(domain)
                cb(domain, f"[skill] {domain}", "skill", "allow", "skill-declared domain")
            else:
                # Permanently allowed or exec-temp sentinel-approved (already notified by sentinel)
                # Don't double-notify for sentinel-approved domains
                pass
        else:
            # Denied without sentinel evaluation (no approval callback set)
            cb(domain, f"[denied] {domain}", "unknown", "deny", "no approval callback configured")

    # ------------------------------------------------------------------
    # Proxy domain approval
    # ------------------------------------------------------------------

    def set_domain_approval_callback(self, session_id: str, cb: Callable[[str, str], Awaitable[bool]] | None) -> None:
        """Register or remove a per-session callback for proxy domain approval."""
        if cb is None:
            self._domain_approval_cbs.pop(session_id, None)
        else:
            self._domain_approval_cbs[session_id] = cb

    def set_domain_notify_callback(
        self,
        session_id: str,
        cb: Callable[[str, str, ApprovalSource | None, ApprovalVerdict | None, str | None], None] | None,
    ) -> None:
        """Register or remove a per-session domain access notification callback.

        Signature: ``cb(domain, detail, approval_source, approval_verdict, approval_explanation)``.
        """
        if cb is None:
            self._domain_notify_cbs.pop(session_id, None)
        else:
            self._domain_notify_cbs[session_id] = cb

    async def request_domain_approval(self, session_id: str, domain: str) -> bool:
        """Called by the proxy when a domain is not in the allowlist.

        Delegates to the per-session callback registered by SessionEngine.
        """
        cb = self._domain_approval_cbs.get(session_id)
        if cb is None:
            logger.warning(f"No domain approval callback for session {session_id}, denying {domain}")
            return False

        command = self._session_current_command.get(session_id, "")
        allowed = await cb(domain, command)
        if allowed:
            self._exec_temp_domains.setdefault(session_id, set()).add(domain)
            logger.info(f"Security approved {domain} for session {session_id}")
        else:
            logger.info(f"Security denied {domain} for session {session_id}")
        return allowed

    def _prepare_session_recreate(self, session_id: str) -> None:
        """Drop container reference while keeping all session state.

        Called when a container is detected as stopped/gone and will be
        replaced immediately.  Token and domain state survive because
        ``ensure_session`` reuses the same credentials and the domain
        allowlist is session-scoped.  The session_env is stashed so it
        can be restored onto the replacement container.
        """
        sc = self._sessions.pop(session_id, None)
        if sc and sc.session_env:
            self._stashed_session_env[session_id] = dict(sc.session_env)

    def _cleanup_tracking(
        self,
        session_id: str,
    ) -> None:
        """Roll back all in-memory tracking for a session.

        Only called from the ``ensure_session`` error path when container
        creation fails and we need to undo the partial setup.  The on-disk
        token file is not removed — it lives in the session directory and
        will be overwritten on the next attempt or deleted when the session
        is permanently removed.

        Credential cache entries are **not** cleared: values are tied to the
        session (``use_skill``), not to a specific container, and must survive
        a transient create failure so the next ``ensure_session`` can inject
        them on ``exec``.  ``destroy_session`` clears the cache when all
        session tracking is purged.
        """
        self._sessions.pop(session_id, None)
        self._stashed_session_env.pop(session_id, None)
        token = self._session_tokens.pop(session_id, None)
        if token:
            self._token_to_session.pop(token, None)
        self._allowed_domains.pop(session_id, None)
        self._exec_temp_domains.pop(session_id, None)
        self._exec_context_skill_domains.pop(session_id, None)
        self._session_current_command.pop(session_id, None)
        self._proxy_bypass_sessions.discard(session_id)
        self._session_current_contexts.pop(session_id, None)
        self._exec_locks.pop(session_id, None)
        self._domain_approval_cbs.pop(session_id, None)
        self._domain_notify_cbs.pop(session_id, None)
        self._exec_notified_domains.pop(session_id, None)
        self._exec_notified_credentials.pop(session_id, None)
