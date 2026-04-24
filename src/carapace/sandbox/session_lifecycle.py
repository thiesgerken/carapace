from __future__ import annotations

import asyncio
import secrets
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from loguru import logger
from pydantic import BaseModel

from carapace.sandbox.runtime import ContainerRuntime, SandboxConfig
from carapace.security.context import ApprovalSource, ApprovalVerdict


class SessionContainer(BaseModel):
    container_id: str
    session_id: str
    ip_address: str | None = None
    created_at: float
    last_used: float
    session_env: dict[str, str] = {}


@dataclass
class SandboxSessionLifecycleState:
    sessions: dict[str, SessionContainer]
    token_to_session: dict[str, str]
    session_tokens: dict[str, str]
    allowed_domains: dict[str, set[str]]
    exec_temp_domains: dict[str, set[str]]
    exec_context_skill_domains: dict[str, set[str]]
    session_current_command: dict[str, str]
    domain_approval_cbs: dict[str, Callable[[str, str], Awaitable[bool]]]
    domain_notify_cbs: dict[
        str,
        Callable[[str, str, ApprovalSource | None, ApprovalVerdict | None, str | None], None],
    ]
    exec_locks: dict[str, asyncio.Lock]
    proxy_bypass_sessions: set[str]
    stashed_session_env: dict[str, dict[str, str]]
    credential_cache: dict[str, dict[str, str]]
    session_current_contexts: dict[str, list[str]]
    exec_notified_domains: dict[str, set[str]]
    exec_notified_credentials: dict[str, set[str]]


class SandboxSessionLifecycle:
    _READY_MARKER = "carapace sandbox ready"
    _COMMIT_TRAILER_KEY = "Carapace-Session"

    def __init__(
        self,
        *,
        runtime: ContainerRuntime,
        state: SandboxSessionLifecycleState,
        data_dir: Path,
        knowledge_dir: Path,
        base_image: str,
        network_name: str,
        idle_timeout: int,
        proxy_port: int,
        sandbox_port: int,
        git_author: str,
    ) -> None:
        self._runtime = runtime
        self._state = state
        self._data_dir = data_dir
        self._knowledge_dir = knowledge_dir
        self._base_image = base_image
        self._network_name = network_name
        self._idle_timeout = idle_timeout
        self._proxy_port = proxy_port
        self._sandbox_port = sandbox_port
        self._git_author = git_author

    def _token_path(self, session_id: str) -> Path:
        return self._data_dir / "sessions" / session_id / "token"

    def _load_persisted_token(self, session_id: str) -> str | None:
        token_path = self._token_path(session_id)
        if not token_path.exists():
            return None
        token = token_path.read_text().strip()
        if not token:
            logger.warning(f"Ignoring empty persisted token for session {session_id}")
            return None
        self._state.session_tokens[session_id] = token
        self._state.token_to_session[token] = session_id
        logger.debug(f"Restored token for session {session_id} from disk")
        return token

    def get_or_create_token(self, session_id: str) -> str:
        """Return the proxy token for *session_id*, loading or creating as needed."""
        token = self._state.session_tokens.get(session_id)
        if token:
            return token

        token = self._load_persisted_token(session_id)
        if token is not None:
            return token

        token = secrets.token_hex(16)
        token_path = self._token_path(session_id)
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(token)
        self._state.session_tokens[session_id] = token
        self._state.token_to_session[token] = session_id
        return token

    def sandbox_name(self, session_id: str) -> str:
        """Derive the sandbox resource name for a session."""
        return f"carapace-sandbox-{session_id}"

    def build_proxy_env(self, session_id: str, proxy_token: str, proxy_url: str) -> dict[str, str]:
        """Build HTTP_PROXY / NO_PROXY env vars for session containers."""
        if not proxy_url:
            return {}

        scheme, rest = proxy_url.split("://", 1)
        authed_url = f"{scheme}://{session_id}:{proxy_token}@{rest}"
        no_proxy_host = rest.rsplit(":", 1)[0]
        no_proxy = ",".join([no_proxy_host, "localhost", "127.0.0.1"])
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
            "PIP_PROXY": authed_url,
            "npm_config_proxy": authed_url,
            "npm_config_https_proxy": authed_url,
            "GIT_REPO_URL": git_url,
            "CARAPACE_API_URL": f"{scheme}://{session_id}:{proxy_token}@{no_proxy_host}:{self._sandbox_port}",
            "CARAPACE_SESSION_ID": session_id,
        }

    async def ensure_session(self, session_id: str) -> tuple[SessionContainer, bool]:
        """Return ``(container, was_created)`` — *was_created* is True when a new container was spun up."""
        sandbox_name = self.sandbox_name(session_id)

        if session_id in self._state.sessions:
            sc = self._state.sessions[session_id]
            if await self._runtime.is_running(sc.container_id):
                logger.debug(f"Reusing existing container {sc.container_id[:12]} for session {session_id}")
                sc.last_used = time.time()
                return sc, False
            try:
                await self._runtime.resume_sandbox(sandbox_name)
                sc.last_used = time.time()
                await self.wait_for_ready(sc.container_id, session_id)
                logger.info(f"Resumed sandbox {sandbox_name} for session {session_id}")
                return sc, False
            except Exception:
                logger.opt(exception=True).debug(f"Resume failed for {sandbox_name}, will recreate")
            await self.log_container_tail(sc.container_id, session_id)
            self.prepare_session_recreate(session_id)
        else:
            existing_id = await self._runtime.sandbox_exists(sandbox_name)
            if isinstance(existing_id, str) and existing_id:
                try:
                    if await self._runtime.is_running(existing_id):
                        logger.info(f"Re-attached to running sandbox {sandbox_name} for session {session_id}")
                    else:
                        await self._runtime.resume_sandbox(sandbox_name)
                        await self.wait_for_ready(existing_id, session_id)
                        logger.info(f"Resumed orphaned sandbox {sandbox_name} for session {session_id}")
                    ip = await self._runtime.get_ip(existing_id, self._network_name)
                    sc = SessionContainer(
                        container_id=existing_id,
                        session_id=session_id,
                        ip_address=ip,
                        created_at=time.time(),
                        last_used=time.time(),
                    )
                    self._state.sessions[session_id] = sc
                    return sc, False
                except Exception:
                    logger.opt(exception=True).debug(
                        f"Failed to re-attach/resume orphaned sandbox {sandbox_name}, will recreate"
                    )

        proxy_token = self.get_or_create_token(session_id)
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

            env = self.build_proxy_env(session_id, proxy_token, proxy_url)
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
            await self.wait_for_ready(container_id, session_id)
            await self.clone_knowledge_repo(container_id, session_id)
        except BaseException:
            self.cleanup_tracking(session_id)
            raise

        sc = SessionContainer(
            container_id=container_id,
            session_id=session_id,
            ip_address=ip,
            created_at=time.time(),
            last_used=time.time(),
        )
        stashed_env = self._state.stashed_session_env.pop(session_id, None)
        if stashed_env:
            sc.session_env.update(stashed_env)
        self._state.sessions[session_id] = sc
        logger.info(f"Created sandbox container {container_id[:12]} for session {session_id} (IP: {ip})")
        return sc, True

    async def log_container_tail(self, container_id: str, session_id: str) -> None:
        """Log the last lines of a dead/stopped container for troubleshooting."""
        try:
            tail = await self._runtime.logs(container_id)
            if tail and tail.strip():
                logger.info(f"Last logs from container {container_id[:12]} (session {session_id}):\n{tail}")
        except Exception:
            logger.opt(exception=True).warning(f"Could not retrieve logs from container {container_id[:12]}")

    async def wait_for_ready(self, container_id: str, session_id: str) -> None:
        """Poll container logs until the ready marker appears (up to 30s)."""
        for _ in range(30):
            log_output = await self._runtime.logs(container_id, tail=10)
            if self._READY_MARKER in log_output:
                return
            await asyncio.sleep(1)
        logger.warning(f"Sandbox for {session_id} did not become ready within 30s")

    async def clone_knowledge_repo(self, container_id: str, session_id: str) -> None:
        """Clone the knowledge repo into the sandbox if not already present."""
        probe = await self._runtime.exec(container_id, "test -d /workspace/.git", timeout=5)
        if probe.exit_code == 0:
            logger.debug(f"Knowledge repo already present in sandbox for {session_id}")
            return

        result = await self._runtime.exec(container_id, "git clone $GIT_REPO_URL /workspace", timeout=60)
        if result.exit_code != 0:
            raise RuntimeError(
                f"Git clone failed in sandbox for {session_id} (exit {result.exit_code}): {result.output}"
            )

        await self.setup_git_identity(container_id, session_id)
        await self.install_commit_msg_hook(container_id, session_id)

    async def setup_git_identity(self, container_id: str, session_id: str) -> None:
        """Configure git user.name and user.email inside the sandbox."""
        name_tpl = self._git_author.replace("%s", session_id)
        if "<" in name_tpl and name_tpl.endswith(">"):
            name, _, email = name_tpl.rpartition("<")
            name, email = name.strip(), email.rstrip(">").strip()
        else:
            name, email = name_tpl, f"{session_id}@carapace"
        name_sh = name.replace("%h", "$(hostname)")
        email_sh = email.replace("%h", "$(hostname)")
        cmd = f'git -C /workspace config user.name "{name_sh}" && git -C /workspace config user.email "{email_sh}"'
        await self._runtime.exec(container_id, cmd, timeout=10)

    async def install_commit_msg_hook(self, container_id: str, session_id: str) -> None:
        """Install a commit-msg hook that appends a session trailer to commits."""
        key = self._COMMIT_TRAILER_KEY
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

    def prepare_session_recreate(self, session_id: str) -> None:
        """Drop container reference while keeping all session state."""
        sc = self._state.sessions.pop(session_id, None)
        if sc and sc.session_env:
            self._state.stashed_session_env[session_id] = dict(sc.session_env)

    def cleanup_tracking(self, session_id: str) -> None:
        """Roll back all in-memory tracking for a session."""
        self._state.sessions.pop(session_id, None)
        self._state.stashed_session_env.pop(session_id, None)
        token = self._state.session_tokens.pop(session_id, None)
        if token:
            self._state.token_to_session.pop(token, None)
        self._state.allowed_domains.pop(session_id, None)
        self._state.exec_temp_domains.pop(session_id, None)
        self._state.exec_context_skill_domains.pop(session_id, None)
        self._state.session_current_command.pop(session_id, None)
        self._state.proxy_bypass_sessions.discard(session_id)
        self._state.session_current_contexts.pop(session_id, None)
        self._state.exec_locks.pop(session_id, None)

    async def cleanup_session(self, session_id: str) -> None:
        """Suspend the sandbox while preserving broader session state."""
        sc = self._state.sessions.pop(session_id, None)
        if sc:
            await self._runtime.suspend_sandbox(self.sandbox_name(session_id), sc.container_id)
            logger.info(f"Suspended sandbox for session {session_id}")

    async def destroy_session(self, session_id: str) -> None:
        """Permanently remove the sandbox and purge all tracking state."""
        sc = self._state.sessions.pop(session_id, None)
        sandbox_name = self.sandbox_name(session_id)
        if sc:
            await self._runtime.destroy_sandbox(session_id, sandbox_name, sc.container_id)
            logger.info(f"Destroyed sandbox for session {session_id}")
        else:
            existing_id = await self._runtime.sandbox_exists(sandbox_name)
            if existing_id:
                await self._runtime.destroy_sandbox(session_id, sandbox_name, existing_id)
                logger.info(f"Destroyed orphaned sandbox for session {session_id}")

        token = self._state.session_tokens.pop(session_id, None)
        if token:
            self._state.token_to_session.pop(token, None)
        self._state.allowed_domains.pop(session_id, None)
        self._state.exec_temp_domains.pop(session_id, None)
        self._state.exec_context_skill_domains.pop(session_id, None)
        self._state.session_current_command.pop(session_id, None)
        self._state.domain_approval_cbs.pop(session_id, None)
        self._state.domain_notify_cbs.pop(session_id, None)
        self._state.exec_locks.pop(session_id, None)
        self._state.proxy_bypass_sessions.discard(session_id)
        self._state.credential_cache.pop(session_id, None)
        self._state.session_current_contexts.pop(session_id, None)
        self._state.exec_notified_domains.pop(session_id, None)
        self._state.exec_notified_credentials.pop(session_id, None)

    async def reset_session(self, session_id: str) -> None:
        """Full sandbox reset: destroy and let ``ensure_session`` create a fresh one."""
        sc = self._state.sessions.pop(session_id, None)
        sandbox_name = self.sandbox_name(session_id)
        if sc:
            await self._runtime.destroy_sandbox(session_id, sandbox_name, sc.container_id)
            logger.info(f"Reset sandbox for session {session_id}")
        else:
            existing_id = await self._runtime.sandbox_exists(sandbox_name)
            if existing_id:
                await self._runtime.destroy_sandbox(session_id, sandbox_name, existing_id)
                logger.info(f"Reset orphaned sandbox for session {session_id}")

    async def cleanup_idle(self) -> None:
        """Remove containers that have been idle longer than the timeout."""
        now = time.time()
        to_remove = [sid for sid, sc in self._state.sessions.items() if now - sc.last_used > self._idle_timeout]
        if to_remove:
            logger.info(f"Cleaning up {len(to_remove)} idle sandbox session(s)")
        for sid in to_remove:
            await self.cleanup_session(sid)

    async def cleanup_all(self) -> None:
        """Remove all sandbox containers while preserving restartable session state."""
        count = len(self._state.sessions)
        if count:
            logger.info(f"Cleaning up all {count} sandbox session(s)")
        for sid in list(self._state.sessions):
            await self.cleanup_session(sid)

    async def cleanup_orphaned_sandboxes(self, known_sessions: set[str]) -> int:
        """Destroy sandbox resources whose session no longer exists on disk."""
        live = await self._runtime.list_sandboxes()
        orphans = {sid: cid for sid, cid in live.items() if sid not in known_sessions}
        for sid, container_id in orphans.items():
            sandbox_name = self.sandbox_name(sid)
            await self._runtime.destroy_sandbox(sid, sandbox_name, container_id)
            logger.info(f"Removed orphaned sandbox for deleted session {sid}")
        return len(orphans)

    def set_session_env(self, session_id: str, env: dict[str, str]) -> None:
        """Merge *env* into the persistent session environment."""
        sc = self._state.sessions.get(session_id)
        if sc:
            sc.session_env.update(env)

    def get_session_env(self, session_id: str) -> dict[str, str]:
        """Return a copy of the current session environment."""
        sc = self._state.sessions.get(session_id)
        return dict(sc.session_env) if sc else {}

    def verify_session_token(self, session_id: str, token: str) -> bool:
        """Return True if *token* is valid for *session_id*."""
        if session_id not in self._state.session_tokens:
            self._load_persisted_token(session_id)
        return self._state.token_to_session.get(token) == session_id
