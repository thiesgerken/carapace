from __future__ import annotations

import asyncio
import base64
import json
import re
import secrets
import shlex
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

from loguru import logger
from pydantic import BaseModel

from carapace.sandbox.runtime import (
    ContainerConfig,
    ContainerGoneError,
    ContainerRuntime,
    ExecResult,
    Mount,
    SkillVenvError,
)

_SKILL_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")

# Inline Python scripts executed inside the sandbox container.
# Data is passed as base64-encoded CLI args to avoid shell-escaping issues.
# Scripts use only double quotes so that shlex.quote (single-quote wrapping)
# works without any escaping.

_EDIT_SCRIPT = """\
import sys, base64, difflib
p, o_b64, n_b64 = sys.argv[1], sys.argv[2], sys.argv[3]
old = base64.b64decode(o_b64).decode()
new = base64.b64decode(n_b64).decode()
try:
    text = open(p).read()
except FileNotFoundError:
    print(f"Error: file not found: {p}")
    sys.exit(1)
except PermissionError:
    print(f"Error: permission denied: {p}")
    sys.exit(1)
count = text.count(old)
if count == 0:
    print("Error: old_string not found")
    sys.exit(1)
if count > 1:
    print(f"Error: old_string appears {count} times (must be unique)")
    sys.exit(1)
updated = text.replace(old, new, 1)
try:
    open(p, "w").write(updated)
except PermissionError:
    print(f"Error: permission denied (read-only): {p}")
    sys.exit(1)
d = difflib.unified_diff(text.splitlines(keepends=True), updated.splitlines(keepends=True), f"a/{p}", f"b/{p}", n=3)
print("".join(d))\
"""

_PATCH_SCRIPT = """\
import sys, base64, json, os
changes = json.loads(base64.b64decode(sys.argv[1]).decode())
for i, c in enumerate(changes):
    p = c.get("path", "")
    old = base64.b64decode(c["old_b64"]).decode() if c.get("old_b64") else ""
    new = base64.b64decode(c["new_b64"]).decode() if c.get("new_b64") else ""
    if not p:
        print(f"Change {i+1}: missing path")
        continue
    if not old:
        d = os.path.dirname(p)
        if d:
            os.makedirs(d, exist_ok=True)
        try:
            open(p, "w").write(new)
            print(f"Change {i+1}: created {p}")
        except PermissionError:
            print(f"Change {i+1} ({p}): permission denied")
        continue
    if not os.path.exists(p):
        print(f"Change {i+1}: file not found: {p}")
        continue
    try:
        t = open(p).read()
    except PermissionError:
        print(f"Change {i+1} ({p}): permission denied")
        continue
    cnt = t.count(old)
    if cnt == 0:
        print(f"Change {i+1} ({p}): old_string not found")
        continue
    if cnt > 1:
        print(f"Change {i+1} ({p}): old_string appears {cnt} times (must be unique)")
        continue
    try:
        open(p, "w").write(t.replace(old, new, 1))
        print(f"Change {i+1}: edited {p}")
    except PermissionError:
        print(f"Change {i+1} ({p}): permission denied")\
"""


class SessionContainer(BaseModel):
    container_id: str
    session_id: str
    ip_address: str | None = None
    created_at: float
    last_used: float


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
        host_data_dir: Path | None = None,
        proxy_port: int = 3128,
        sandbox_port: int = 8322,
    ) -> None:
        self._runtime = runtime
        self._data_dir = data_dir
        self._knowledge_dir = knowledge_dir
        self._host_data_dir = host_data_dir
        self._base_image = base_image
        self._network_name = network_name
        self._idle_timeout = idle_timeout_minutes * 60
        self._proxy_port = proxy_port
        self._sandbox_port = sandbox_port
        self._sessions: dict[str, SessionContainer] = {}
        self._token_to_session: dict[str, str] = {}
        self._session_tokens: dict[str, str] = {}
        self._tokens_path = self._data_dir / "sandbox_tokens.json"
        self._load_tokens()
        self._allowed_domains: dict[str, set[str]] = {}
        self._exec_temp_domains: dict[str, set[str]] = {}  # session_id -> domains, cleared after each exec
        self._session_current_command: dict[str, str] = {}
        self._domain_approval_cbs: dict[str, Callable[[str, str], Awaitable[bool]]] = {}
        self._exec_locks: dict[str, asyncio.Lock] = {}
        self._proxy_bypass_sessions: set[str] = set()
        self._get_activated_skills_cb: Callable[[str], list[str]] | None = None
        logger.info(
            f"SandboxManager initialized (image={base_image}, "
            + f"network={network_name}, proxy_port={proxy_port}, idle_timeout={idle_timeout_minutes}m)"
        )
        if host_data_dir:
            logger.info(f"Host data dir override: {host_data_dir} (container sees {data_dir})")

    def set_activated_skills_callback(self, cb: Callable[[str], list[str]]) -> None:
        """Register a callback to retrieve activated skills for a session (from persisted state)."""
        self._get_activated_skills_cb = cb

    def _load_tokens(self) -> None:
        """Restore session tokens from disk so sandbox auth survives server restarts."""
        if not self._tokens_path.exists():
            return
        try:
            data = json.loads(self._tokens_path.read_text())
            self._session_tokens = data
            self._token_to_session = {t: s for s, t in data.items()}
            logger.info(f"Restored {len(data)} session token(s) from {self._tokens_path.name}")
        except Exception as exc:
            logger.warning(f"Failed to load session tokens: {exc}")

    def _save_tokens(self) -> None:
        """Persist session tokens to disk."""
        try:
            self._tokens_path.write_text(json.dumps(self._session_tokens))
        except Exception as exc:
            logger.warning(f"Failed to save session tokens: {exc}")

    async def _log_container_tail(self, container_id: str, session_id: str) -> None:
        """Log the last lines of a dead/stopped container for troubleshooting."""
        try:
            tail = await self._runtime.logs(container_id)
            if tail and tail.strip():
                logger.info(f"Last logs from container {container_id[:12]} (session {session_id}):\n{tail}")
        except Exception:
            logger.debug(f"Could not retrieve logs from container {container_id[:12]}")

    def _get_exec_lock(self, session_id: str) -> asyncio.Lock:
        if session_id not in self._exec_locks:
            self._exec_locks[session_id] = asyncio.Lock()
        return self._exec_locks[session_id]

    async def ensure_session(self, session_id: str) -> tuple[SessionContainer, bool]:
        """Return ``(container, was_created)`` — *was_created* is True when a new container was spun up."""
        if session_id in self._sessions:
            sc = self._sessions[session_id]
            if await self._runtime.is_running(sc.container_id):
                logger.debug(f"Reusing existing container {sc.container_id[:12]} for session {session_id}")
                sc.last_used = time.time()
                return sc, False
            logger.warning(
                f"Container {sc.container_id[:12]} for session {session_id} is no longer running, recreating"
            )
            await self._log_container_tail(sc.container_id, session_id)
            self._prepare_session_recreate(session_id)

        session_workspace = self._data_dir / "sessions" / session_id / "workspace"
        session_workspace.mkdir(parents=True, exist_ok=True)
        # Make world-writable so sandbox containers running as UID 1000
        # can write to PVC subPath mounts (chown may not be available).
        session_workspace.chmod(0o777)

        proxy_token = secrets.token_hex(16)
        # Evict any orphaned token left by a previous failed attempt for this
        # session (one that never reached _sessions so _cleanup_tracking was
        # never called on retry).
        old_token = self._session_tokens.get(session_id)
        if old_token:
            self._token_to_session.pop(old_token, None)
        self._token_to_session[proxy_token] = session_id
        self._session_tokens[session_id] = proxy_token
        self._save_tokens()
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

            mounts = self._build_mounts(session_id)
            env = self._build_proxy_env(session_id, proxy_token, proxy_url)
            config = ContainerConfig(
                image=self._base_image,
                name=f"carapace-sandbox-{session_id}",
                labels={"carapace.session": session_id, "carapace.managed": "true"},
                mounts=mounts,
                network=self._network_name,
                command=[
                    "sh",
                    "-c",
                    "setup-proxy.sh && echo 'carapace sandbox ready' && exec sleep infinity",
                ],
                environment=env,
            )

            container_id = await self._runtime.create(config)
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
        self._sessions[session_id] = sc
        logger.info(f"Created sandbox container {container_id[:12]} for session {session_id} (IP: {ip})")
        return sc, True

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
            "test -d /workspace/knowledge/.git",
            timeout=5,
        )
        if probe.exit_code == 0:
            logger.debug(f"Knowledge repo already present in sandbox for {session_id}")
            return
        result = await self._runtime.exec(
            container_id,
            "git clone $GIT_REPO_URL /workspace/knowledge",
            timeout=60,
        )
        if result.exit_code != 0:
            logger.error(f"Git clone failed in sandbox for {session_id} (exit {result.exit_code}): {result.output}")

    def _host_path(self, path: Path) -> str:
        """Translate a container-local path to its host-side equivalent for bind mounts.

        When running inside Docker (DooD), the Docker daemon needs host-absolute
        paths but we only see the container-internal mount point.  If
        ``_host_data_dir`` is set we rewrite the ``_data_dir`` prefix accordingly.
        """
        resolved = path.resolve()
        if self._host_data_dir is None:
            return str(resolved)
        try:
            rel = resolved.relative_to(self._data_dir.resolve())
        except ValueError:
            # Path is not under data_dir — use it as-is (no rewriting needed).
            return str(resolved)
        return str(self._host_data_dir / rel)

    def _build_mounts(self, session_id: str) -> list[Mount]:
        session_workspace = self._data_dir / "sessions" / session_id / "workspace"
        return [
            Mount(
                source=self._host_path(session_workspace),
                target="/workspace",
                read_only=False,
            ),
        ]

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
        }

    async def _exec(
        self,
        session_id: str,
        command: str,
        timeout: int = 30,
        *,
        bypass_proxy: bool = False,
        workdir: str | None = None,
    ) -> ExecResult:
        """Run a command in the sandbox and return the raw ExecResult.

        When *bypass_proxy* is True, all proxy domains are temporarily allowed
        for the duration of this exec (used during venv builds).  The bypass
        flag is set/cleared **under the exec lock** so no concurrent command
        can exploit the open window.
        """
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
                self._exec_temp_domains[session_id] = set()
                try:
                    return await self._runtime.exec(
                        sc.container_id,
                        command,
                        timeout=timeout,
                        workdir=workdir,
                    )
                except ContainerGoneError:
                    logger.warning(f"Container gone for session {session_id}, recreating sandbox")
                    await self._log_container_tail(sc.container_id, session_id)
                    self._prepare_session_recreate(session_id)
                    sc, _ = await self.ensure_session(session_id)
                    await self._rebuild_skill_venvs(session_id)
                    return await self._runtime.exec(
                        sc.container_id,
                        command,
                        timeout=timeout,
                        workdir=workdir,
                    )
            finally:
                if bypass_proxy:
                    self._proxy_bypass_sessions.discard(session_id)
                    logger.info(f"Proxy bypass DISABLED for session {session_id}")
                self._session_current_command.pop(session_id, None)
                self._exec_temp_domains.pop(session_id, None)

    _KNOWLEDGE_WORKDIR = "/workspace/knowledge"

    async def exec_command(self, session_id: str, command: str, timeout: int = 30) -> str:
        """Run a command in the sandbox and return formatted output."""
        result = await self._exec(
            session_id,
            command,
            timeout=timeout,
            workdir=self._KNOWLEDGE_WORKDIR,
        )
        output = result.output
        if result.exit_code != 0 and f"[exit code: {result.exit_code}]" not in output:
            logger.debug(f"Command failed in session {session_id} (exit {result.exit_code}): {command}")
            output += f"\n[exit code: {result.exit_code}]"
        return output or "(no output)"

    # ------------------------------------------------------------------
    # File operations (executed inside the sandbox container via
    # shell commands and small inline Python snippets).
    # Data is passed as base64 CLI args to avoid shell-escaping issues.
    # ------------------------------------------------------------------

    async def file_read(self, session_id: str, path: str) -> str:
        """Read a file or list a directory inside the sandbox."""
        pq = shlex.quote(path)
        cmd = f'if [ -d {pq} ]; then echo "::DIR::"; ls -1 {pq}; else cat {pq}; fi'
        result = await self._exec(session_id, cmd, timeout=10)
        if result.exit_code != 0:
            return result.output or f"Error: cannot read {path}"
        output = result.output
        if output.startswith("::DIR::\n"):
            return f"Directory listing of {path}/:\n" + output[len("::DIR::\n") :]
        return output or "(empty file)"

    async def file_write(self, session_id: str, path: str, content: str) -> str:
        """Write content to a file inside the sandbox."""
        pq = shlex.quote(path)
        content_b64 = base64.b64encode(content.encode()).decode()
        cmd = f'mkdir -p "$(dirname {pq})" && printf %s {content_b64} | base64 -d > {pq}'
        result = await self._exec(session_id, cmd, timeout=10)
        if result.exit_code != 0:
            return result.output or f"Error: cannot write {path}"
        return f"Written to {path}"

    async def file_edit(self, session_id: str, path: str, old_string: str, new_string: str) -> str:
        """Edit a file inside the sandbox (search-and-replace)."""
        pq = shlex.quote(path)
        old_b64 = base64.b64encode(old_string.encode()).decode()
        new_b64 = base64.b64encode(new_string.encode()).decode()
        cmd = f"python3 -c {shlex.quote(_EDIT_SCRIPT)} {pq} {old_b64} {new_b64}"
        result = await self._exec(session_id, cmd, timeout=10)
        if result.exit_code != 0:
            return result.output or f"Error: cannot edit {path}"
        return f"Edited {path}:\n```diff\n{result.output}```"

    async def file_apply_patch(self, session_id: str, changes: list[dict[str, str]]) -> str:
        """Apply structured edits across files inside the sandbox."""
        encoded_changes: list[dict[str, str]] = []
        for change in changes:
            encoded: dict[str, str] = {"path": change.get("path", "")}
            if change.get("old_string"):
                encoded["old_b64"] = base64.b64encode(change["old_string"].encode()).decode()
            if change.get("new_string"):
                encoded["new_b64"] = base64.b64encode(change["new_string"].encode()).decode()
            encoded_changes.append(encoded)

        payload_b64 = base64.b64encode(json.dumps(encoded_changes).encode()).decode()
        cmd = f"python3 -c {shlex.quote(_PATCH_SCRIPT)} {payload_b64}"
        result = await self._exec(session_id, cmd, timeout=10)
        return result.output or "(no output)"

    async def activate_skill(self, session_id: str, skill_name: str) -> str:
        if err := _validate_skill_name(skill_name):
            return err

        await self.ensure_session(session_id)

        # Check that the skill exists in the server-side knowledge store.
        # The sandbox already has it at /workspace/knowledge/skills/{name} via git clone.
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
                    f"Skill '{skill_name}' activated at /workspace/knowledge/skills/{skill_name}/ but "
                    f"dependency install failed: {exc}\n"
                    "The skill is available but its Python dependencies are NOT installed. "
                    "You may need to install them manually inside the sandbox."
                ) from exc

        logger.info(f"Activated skill '{skill_name}' in session {session_id}")
        result = f"Skill '{skill_name}' activated at /workspace/knowledge/skills/{skill_name}/"
        if venv_msg:
            result += f"\n{venv_msg}"
        return result

    async def _build_skill_venv(self, session_id: str, skill_name: str) -> None:
        """Build a skill venv inside the session container with proxy bypass.

        Runs ``uv sync`` inside the session container.  The proxy is temporarily
        bypassed (all domains allowed) for the duration of the install.
        """
        if err := _validate_skill_name(skill_name):
            raise SkillVenvError(err)

        logger.info(f"Building venv for skill '{skill_name}' (session {session_id})")
        skill_dir = f"/workspace/knowledge/skills/{shlex.quote(skill_name)}"
        result = await self._exec(
            session_id,
            f"uv sync --directory {skill_dir}",
            timeout=120,
            bypass_proxy=True,
        )
        if result.exit_code != 0:
            logger.error(f"Venv build failed for skill '{skill_name}' (exit {result.exit_code}): {result.output[:300]}")
            raise SkillVenvError(f"exit {result.exit_code}: {result.output[:500]}")
        logger.info(f"Venv built successfully for skill '{skill_name}'")

    async def _sync_skill_venv(self, session_id: str, skill_name: str) -> str:
        """Restore trusted pyproject.toml + uv.lock from git, then rebuild venv."""
        master = self._knowledge_dir / "skills" / skill_name
        if not (master / "pyproject.toml").exists():
            return ""

        # Restore committed dependency manifests inside the sandbox,
        # preventing the sandbox from running modified dependencies.
        skill_path = f"skills/{shlex.quote(skill_name)}"
        result = await self._exec(
            session_id,
            f"git checkout HEAD -- {skill_path}/pyproject.toml",
            timeout=10,
            workdir=self._KNOWLEDGE_WORKDIR,
        )
        if result.exit_code != 0:
            raise SkillVenvError(f"Failed to restore trusted pyproject.toml: {result.output}")
        await self._exec(
            session_id,
            f"git checkout HEAD -- {skill_path}/uv.lock 2>/dev/null || true",
            timeout=10,
            workdir=self._KNOWLEDGE_WORKDIR,
        )

        await self._build_skill_venv(session_id, skill_name)
        return "Venv rebuilt successfully."

    async def rebuild_skill_venvs(self, session_id: str, activated_skills: list[str]) -> None:
        """Rebuild venvs for all activated skills.  Called by SessionEngine after container recreation."""
        for skill_name in activated_skills:
            master_skill_dir = self._knowledge_dir / "skills" / skill_name
            if (master_skill_dir / "pyproject.toml").exists():
                logger.info(f"Rebuilding venv for skill '{skill_name}' after container recreation")
                try:
                    await self._sync_skill_venv(session_id, skill_name)
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
        sc = self._sessions.get(session_id)
        if sc:
            await self._runtime.remove(sc.container_id)
            self._cleanup_tracking(session_id)
            logger.info(f"Cleaned up sandbox for session {session_id}")

    async def cleanup_idle(self) -> None:
        now = time.time()
        to_remove = [sid for sid, sc in self._sessions.items() if now - sc.last_used > self._idle_timeout]
        if to_remove:
            logger.info(f"Cleaning up {len(to_remove)} idle sandbox session(s)")
        for sid in to_remove:
            await self.cleanup_session(sid)

    async def cleanup_all(self) -> None:
        count = len(self._sessions)
        if count:
            logger.info(f"Cleaning up all {count} sandbox session(s)")
        for sid in list(self._sessions):
            await self.cleanup_session(sid)

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
    # Proxy domain approval
    # ------------------------------------------------------------------

    def set_domain_approval_callback(self, session_id: str, cb: Callable[[str, str], Awaitable[bool]] | None) -> None:
        """Register or remove a per-session callback for proxy domain approval."""
        if cb is None:
            self._domain_approval_cbs.pop(session_id, None)
        else:
            self._domain_approval_cbs[session_id] = cb

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
        """Drop container/token tracking while keeping policy state."""
        self._cleanup_tracking(
            session_id,
            clear_domain_state=False,
            clear_exec_state=False,
        )

    def _cleanup_tracking(
        self,
        session_id: str,
        *,
        clear_domain_state: bool = True,
        clear_exec_state: bool = True,
    ) -> None:
        self._sessions.pop(session_id, None)
        token = self._session_tokens.pop(session_id, None)
        if token:
            self._token_to_session.pop(token, None)
        if token or session_id in self._session_tokens:
            self._save_tokens()
        if clear_domain_state:
            self._allowed_domains.pop(session_id, None)
        if clear_exec_state:
            self._exec_temp_domains.pop(session_id, None)
            self._session_current_command.pop(session_id, None)
            self._proxy_bypass_sessions.discard(session_id)
            self._exec_locks.pop(session_id, None)
        if clear_domain_state:
            self._domain_approval_cbs.pop(session_id, None)
