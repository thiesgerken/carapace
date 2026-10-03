from __future__ import annotations

import asyncio
import secrets
import shlex
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from loguru import logger
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError

from ..database.engine import SessionFactory
from ..database.models import SandboxTokenRow
from ..security.context import ApprovalSource, ApprovalVerdict
from .runtime import ContainerRuntime, DuplicateSandboxError, SandboxConfig
from .state import load_sandbox_snapshot


class SessionContainer(BaseModel):
    container_id: str
    session_id: str
    sandbox_id: str | None = None
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
    _COMMIT_TRAILER_KEY = "carapace-session"
    _WARM_POOL_PREFIX = "pool-"
    _READY_TIMEOUT_SECONDS = 180

    def __init__(
        self,
        *,
        runtime: ContainerRuntime,
        state: SandboxSessionLifecycleState,
        data_dir: Path,
        session_factory: SessionFactory,
        base_image: str,
        network_name: str,
        idle_timeout: int,
        proxy_port: int,
        sandbox_port: int,
        warm_pool_size: int,
        knowledge_repo_name_for_session: Callable[[str], str],
        git_author_for_session: Callable[[str], str],
    ) -> None:
        self._runtime = runtime
        self._state = state
        self._data_dir = data_dir
        self._session_factory = session_factory
        self._base_image = base_image
        self._network_name = network_name
        self._idle_timeout = idle_timeout
        self._proxy_port = proxy_port
        self._sandbox_port = sandbox_port
        self._warm_pool_size = warm_pool_size
        self._knowledge_repo_name_for_session = knowledge_repo_name_for_session
        self._git_author_for_session = git_author_for_session
        self._warm_claim_lock = asyncio.Lock()
        self._warm_refill_tasks: set[asyncio.Task[int]] = set()

    def schedule_warm_pool_refill(self) -> None:
        """Replenish the warm pool in the background without blocking session start."""
        if self._runtime.runtime_kind != "kubernetes":
            return
        task = asyncio.create_task(self._refill_warm_pool())
        self._warm_refill_tasks.add(task)
        task.add_done_callback(self._warm_refill_tasks.discard)

    async def _refill_warm_pool(self) -> int:
        try:
            return await self.ensure_warm_pool(self._warm_pool_size)
        except Exception:
            logger.opt(exception=True).warning("Failed to replenish warm sandbox pool")
            return 0

    def _repo_name_for_session(self, session_id: str) -> str:
        return self._knowledge_repo_name_for_session(session_id)

    def _author_for_session(self, session_id: str) -> str:
        return self._git_author_for_session(session_id)

    def _load_persisted_token(self, session_id: str) -> str | None:
        with self._session_factory() as db:
            row = db.get(SandboxTokenRow, session_id)
        if row is None:
            return None
        token = row.token.strip()
        if not token:
            logger.warning(f"Ignoring empty persisted token for session {session_id}")
            return None
        self._state.session_tokens[session_id] = token
        self._state.token_to_session[token] = session_id
        logger.debug(f"Restored token for session {session_id} from database")
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
        try:
            with self._session_factory.begin() as db:
                existing = db.get(SandboxTokenRow, session_id)
                if existing is not None:
                    token = existing.token
                else:
                    db.add(SandboxTokenRow(session_id=session_id, token=token))
        except IntegrityError:
            # Lost a race against a concurrent writer — reuse the token they persisted.
            with self._session_factory() as db:
                row = db.get(SandboxTokenRow, session_id)
            if row is None:
                raise
            token = row.token
        self._state.session_tokens[session_id] = token
        self._state.token_to_session[token] = session_id
        return token

    def default_sandbox_id(self, session_id: str) -> str:
        """Return the default sandbox identifier for a session."""
        return session_id

    def sandbox_id_for_session(self, session_id: str) -> str:
        """Return the sandbox identifier currently assigned to *session_id*."""
        sc = self._state.sessions.get(session_id)
        if sc is not None and sc.sandbox_id:
            return sc.sandbox_id
        snapshot = load_sandbox_snapshot(self._session_factory, session_id)
        if snapshot is not None and snapshot.sandbox_id:
            return snapshot.sandbox_id
        return self.default_sandbox_id(session_id)

    def sandbox_name_for_id(self, sandbox_id: str) -> str:
        """Derive the sandbox resource name for a sandbox identifier."""
        return f"carapace-sandbox-{sandbox_id}"

    def sandbox_name(self, session_id: str) -> str:
        """Derive the sandbox resource name for a session."""
        return self.sandbox_name_for_id(self.sandbox_id_for_session(session_id))

    def assigned_sandbox_id(self, session_id: str, sc: object | None = None) -> str:
        """Return the assigned sandbox ID, preferring live session state when available."""
        sandbox_id = getattr(sc, "sandbox_id", None)
        if isinstance(sandbox_id, str) and sandbox_id:
            return sandbox_id
        return self.sandbox_id_for_session(session_id)

    def sandbox_name_for_live_resource(self, session_id: str, container_id: str) -> str:
        """Return the actual resource name for a live sandbox entry."""
        if self._runtime.runtime_kind == "kubernetes" and container_id.endswith("-0"):
            return container_id.removesuffix("-0")
        return self.sandbox_name(session_id)

    def sandbox_id_for_live_resource(self, session_id: str, container_id: str) -> str:
        """Return the sandbox ID associated with a live sandbox entry."""
        sandbox_name = self.sandbox_name_for_live_resource(session_id, container_id)
        prefix = "carapace-sandbox-"
        if sandbox_name.startswith(prefix):
            return sandbox_name.removeprefix(prefix)
        return self.sandbox_id_for_session(session_id)

    def new_pool_sandbox_id(self) -> str:
        """Return a fresh, unique sandbox ID for a warm-pool member.

        A random id (never a recycled sequence) makes it impossible for a deleted
        sandbox's id to be reused and accidentally reattach a stale session to a
        sandbox now owned by someone else. Kept short (12 hex chars) so the derived
        StatefulSet name plus k8s's controller-revision-hash stays within the 63-byte
        label limit.
        """
        return f"{self._WARM_POOL_PREFIX}{secrets.token_hex(6)}"

    def _sandbox_command(self, *, configure_proxy: bool) -> list[str]:
        prefix = "setup-proxy.sh && " if configure_proxy else ""
        return ["sh", "-c", f"{prefix}echo '{self._READY_MARKER}' && exec sleep infinity"]

    async def build_session_proxy_env(self, session_id: str) -> dict[str, str]:
        """Resolve the proxy URL and build the session's proxy env vars."""
        proxy_token = self.get_or_create_token(session_id)
        host_ip = await self._runtime.get_host_ip(self._network_name)
        if not host_ip:
            raise RuntimeError(
                f"Cannot build proxy env for session {session_id}: "
                f"no IP found on network '{self._network_name}'. "
                "Is the proxy network configured correctly?"
            )
        proxy_url = f"http://{host_ip}:{self._proxy_port}"
        logger.info(f"Proxy URL for session {session_id}: {proxy_url}")
        return self.build_proxy_env(session_id, proxy_token, proxy_url)

    def build_proxy_env(self, session_id: str, proxy_token: str, proxy_url: str) -> dict[str, str]:
        """Build HTTP_PROXY / NO_PROXY env vars for session containers."""
        if not proxy_url:
            return {}

        scheme, rest = proxy_url.split("://", 1)
        authed_url = f"{scheme}://{session_id}:{proxy_token}@{rest}"
        no_proxy_host = rest.rsplit(":", 1)[0]
        no_proxy = ",".join([no_proxy_host, "localhost", "127.0.0.1"])
        repo_name = self._repo_name_for_session(session_id)
        git_url = f"{scheme}://{session_id}:{proxy_token}@{no_proxy_host}:{self._sandbox_port}/git/{repo_name}"
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

    async def log_assignment(
        self,
        container_id: str,
        *,
        sandbox_id: str,
        session_id: str,
        event: str,
    ) -> None:
        """Emit a sandbox-assignment line into the container stdout."""
        message = f"carapace sandbox assignment event={event} sandbox_id={sandbox_id} session_id={session_id}"
        try:
            await self._runtime.write_stdout_log(container_id, message)
        except Exception:
            logger.opt(exception=True).warning(
                f"Failed to write sandbox assignment log for session {session_id} ({container_id[:12]})"
            )

    async def ensure_session(self, session_id: str) -> tuple[SessionContainer, bool]:
        """Return ``(container, needs_runtime_setup)``.

        ``needs_runtime_setup`` is True when the sandbox runtime was newly created or
        resumed after being stopped. In those cases, skill setup must rerun because
        runtime-only state like generated command shims is lost.

        Not serialized here: callers go through ``SandboxManager``, which holds the
        per-session startup lock around this call and the skill setup rerun.
        """
        sandbox_id = self.sandbox_id_for_session(session_id)
        sandbox_name = self.sandbox_name_for_id(sandbox_id)

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
                await self.log_assignment(
                    sc.container_id,
                    sandbox_id=sc.sandbox_id or sandbox_id,
                    session_id=session_id,
                    event="resume",
                )
                logger.info(f"Resumed sandbox {sandbox_name} for session {session_id}")
                return sc, True
            except Exception:
                logger.opt(exception=True).debug(f"Resume failed for {sandbox_name}, will recreate")
            await self.log_container_tail(sc.container_id, session_id)
            self.prepare_session_recreate(session_id)
        else:
            existing_id = await self._runtime.sandbox_exists(sandbox_name)
            if self._runtime.runtime_kind == "kubernetes":
                owned_ids = (await self._runtime.list_sandboxes()).get(session_id, [])
                if len(owned_ids) > 1:
                    # No safe way to pick one; attaching to either could hijack the
                    # sandbox the other code path is still using or tearing down.
                    raise DuplicateSandboxError(
                        f"Session {session_id} has more than one live sandbox: {', '.join(owned_ids)}"
                    )
                owned = owned_ids[0] if owned_ids else None
                if existing_id and owned != existing_id:
                    # The sandbox at our snapshot's name is labelled for a different
                    # session. Pool ids are random uuids, so this should never happen;
                    # never silently hijack another session's sandbox.
                    raise RuntimeError(
                        f"Sandbox {sandbox_name} exists but is owned by another session, not {session_id}"
                    )
                if not existing_id and isinstance(owned, str) and owned:
                    existing_id = owned
                    sandbox_name = self.sandbox_name_for_live_resource(session_id, owned)
                    sandbox_id = self.sandbox_id_for_live_resource(session_id, owned)
            if isinstance(existing_id, str) and existing_id:
                try:
                    if await self._runtime.is_running(existing_id):
                        logger.info(f"Re-attached to running sandbox {sandbox_name} for session {session_id}")
                        needs_runtime_setup = False
                    else:
                        await self._runtime.resume_sandbox(sandbox_name)
                        await self.wait_for_ready(existing_id, session_id)
                        logger.info(f"Resumed orphaned sandbox {sandbox_name} for session {session_id}")
                        needs_runtime_setup = True
                    ip = await self._runtime.get_ip(existing_id, self._network_name)
                    sc = SessionContainer(
                        container_id=existing_id,
                        session_id=session_id,
                        sandbox_id=sandbox_id,
                        ip_address=ip,
                        created_at=time.time(),
                        last_used=time.time(),
                    )
                    # Claimed warm sandboxes carry no proxy env in their pod spec, so
                    # rebuild it here; exec relies on session_env to reach the proxy.
                    try:
                        sc.session_env = await self.build_session_proxy_env(session_id)
                    except Exception:
                        logger.opt(exception=True).warning(
                            f"Failed to rebuild proxy env on reattach for session {session_id}"
                        )
                    stashed_env = self._state.stashed_session_env.pop(session_id, None)
                    if stashed_env:
                        sc.session_env.update(stashed_env)
                    self._state.sessions[session_id] = sc
                    await self.log_assignment(
                        existing_id,
                        sandbox_id=sandbox_id,
                        session_id=session_id,
                        event="reattach" if not needs_runtime_setup else "resume",
                    )
                    return sc, needs_runtime_setup
                except Exception:
                    logger.opt(exception=True).debug(
                        f"Failed to re-attach/resume orphaned sandbox {sandbox_name}, will recreate"
                    )

        try:
            env = await self.build_session_proxy_env(session_id)
            command = self._sandbox_command(configure_proxy=True)

            claimed = await self.claim_warm_sandbox(session_id, env)
            if claimed is not None:
                self.schedule_warm_pool_refill()
                return claimed, True

            sandbox_config = SandboxConfig(
                name=sandbox_name,
                sandbox_id=sandbox_id,
                session_id=session_id,
                image=self._base_image,
                labels={
                    "carapace.session": session_id,
                    "carapace.sandbox": sandbox_id,
                    "carapace.managed": "true",
                },
                environment=env,
                command=command,
            )
            container_id = await self._runtime.create_sandbox(sandbox_config)
            ip = await self._runtime.get_ip(container_id, self._network_name)
            await self.wait_for_ready(container_id, session_id)
            await self.log_assignment(
                container_id,
                sandbox_id=sandbox_id,
                session_id=session_id,
                event="create",
            )
            await self.clone_knowledge_repo(container_id, session_id, env=env)
        except BaseException:
            self.cleanup_tracking(session_id)
            raise

        sc = SessionContainer(
            container_id=container_id,
            session_id=session_id,
            sandbox_id=sandbox_id,
            ip_address=ip,
            created_at=time.time(),
            last_used=time.time(),
        )
        stashed_env = self._state.stashed_session_env.pop(session_id, None)
        if stashed_env:
            sc.session_env.update(stashed_env)
        self._state.sessions[session_id] = sc
        logger.info(f"Created sandbox container {container_id[:12]} for session {session_id} (IP: {ip})")
        self.schedule_warm_pool_refill()
        return sc, True

    async def ensure_warm_pool(self, target_size: int) -> int:
        """Ensure *target_size* unattached warm sandboxes exist and are running."""
        if self._runtime.runtime_kind != "kubernetes":
            return 0
        if target_size <= 0:
            target_size = 0

        # Serialize against claim_warm_sandbox so pool maintenance never resumes,
        # recreates, or destroys a pool entry while a claim is mid-flight.
        async with self._warm_claim_lock:
            pool = await self._runtime.list_pool_sandboxes()
            for sandbox_id in sorted(pool):
                await self.ensure_warm_sandbox(sandbox_id)

            pool = await self._runtime.list_pool_sandboxes()
            while len(pool) > target_size:
                sandbox_id = sorted(pool)[-1]
                container_id = pool.pop(sandbox_id)
                sandbox_name = self.sandbox_name_for_id(sandbox_id)
                await self._runtime.destroy_sandbox(sandbox_id, sandbox_name, container_id)

            while len(pool) < target_size:
                sandbox_id = self.new_pool_sandbox_id()
                pool[sandbox_id] = await self.ensure_warm_sandbox(sandbox_id)
            return len(pool)

    async def claim_warm_sandbox(self, session_id: str, env: dict[str, str]) -> SessionContainer | None:
        """Attach an existing warm sandbox to *session_id* when supported by the runtime."""
        if self._warm_pool_size <= 0 or self._runtime.runtime_kind != "kubernetes":
            return None

        async with self._warm_claim_lock:
            assigned = {sc.sandbox_id for sc in self._state.sessions.values() if sc.sandbox_id}
            pool = await self._runtime.list_pool_sandboxes()
            for sandbox_id in sorted(pool):
                if sandbox_id in assigned:
                    continue

                container_id = pool[sandbox_id]
                sandbox_name = self.sandbox_name_for_id(sandbox_id)
                try:
                    if not await self._runtime.is_running(container_id):
                        await self._runtime.resume_sandbox(sandbox_name)
                        await self.wait_for_ready(container_id, session_id)
                    claimed = await self._runtime.claim_warm_sandbox(sandbox_name, session_id)
                    if not claimed:
                        continue
                    ip = await self._runtime.get_ip(container_id, self._network_name)
                    sc = SessionContainer(
                        container_id=container_id,
                        session_id=session_id,
                        sandbox_id=sandbox_id,
                        ip_address=ip,
                        created_at=time.time(),
                        last_used=time.time(),
                        session_env=dict(env),
                    )
                    stashed_env = self._state.stashed_session_env.pop(session_id, None)
                    if stashed_env:
                        sc.session_env.update(stashed_env)
                    self._state.sessions[session_id] = sc
                    await self.log_assignment(
                        container_id,
                        sandbox_id=sandbox_id,
                        session_id=session_id,
                        event="claim",
                    )
                    await self.setup_proxy(container_id, session_id, sc.session_env)
                    await self.clone_knowledge_repo(container_id, session_id, env=sc.session_env)
                    logger.info(f"Claimed warm sandbox {sandbox_name} for session {session_id}")
                    return sc
                except BaseException:
                    self._state.sessions.pop(session_id, None)
                    self._state.stashed_session_env.pop(session_id, None)
                    try:
                        await self._runtime.destroy_sandbox(session_id, sandbox_name, container_id)
                    except Exception:
                        logger.opt(exception=True).warning(
                            f"Failed to destroy warm sandbox {sandbox_name} after failed claim for {session_id}"
                        )
                    logger.opt(exception=True).warning(
                        f"Failed to claim warm sandbox {sandbox_name} for {session_id}, falling back to cold create"
                    )
                    continue

        return None

    async def ensure_warm_sandbox(self, sandbox_id: str) -> str:
        """Ensure an unattached warm sandbox exists for *sandbox_id*."""
        sandbox_name = self.sandbox_name_for_id(sandbox_id)
        existing_id = await self._runtime.sandbox_exists(sandbox_name)
        if isinstance(existing_id, str) and existing_id:
            if await self._runtime.is_running(existing_id):
                return existing_id
            try:
                await self._runtime.resume_sandbox(sandbox_name)
                await self.wait_for_ready(existing_id, sandbox_id)
                logger.info(f"Resumed warm sandbox {sandbox_name}")
                return existing_id
            except Exception:
                logger.opt(exception=True).debug(f"Resume failed for warm sandbox {sandbox_name}, will recreate")
                await self.log_container_tail(existing_id, sandbox_id)
                await self._runtime.destroy_sandbox(sandbox_id, sandbox_name, existing_id)

        sandbox_config = SandboxConfig(
            name=sandbox_name,
            sandbox_id=sandbox_id,
            session_id=sandbox_id,
            image=self._base_image,
            labels={
                # No carapace.session yet: a pool member has no owning session until
                # claimed. The selector keys off carapace.sandbox; carapace.session is
                # stamped on claim.
                "carapace.sandbox": sandbox_id,
                "carapace.pool": "true",
                "carapace.managed": "true",
            },
            environment={},
            command=self._sandbox_command(configure_proxy=False),
        )
        container_id = await self._runtime.create_sandbox(sandbox_config)
        await self.wait_for_ready(container_id, sandbox_id)
        logger.info(f"Created warm sandbox {sandbox_name} ({container_id[:12]})")
        return container_id

    async def log_container_tail(self, container_id: str, session_id: str) -> None:
        """Log the last lines of a dead/stopped container for troubleshooting."""
        try:
            tail = await self._runtime.logs(container_id)
            if tail and tail.strip():
                logger.info(f"Last logs from container {container_id[:12]} (session {session_id}):\n{tail}")
        except Exception:
            logger.opt(exception=True).warning(f"Could not retrieve logs from container {container_id[:12]}")

    async def wait_for_ready(self, container_id: str, session_id: str) -> None:
        """Poll container logs until the ready marker appears."""
        last_output = ""
        for _ in range(self._READY_TIMEOUT_SECONDS):
            last_output = await self._runtime.logs(container_id, tail=10)
            if self._READY_MARKER in last_output:
                return
            await asyncio.sleep(1)
        logger.warning(
            f"Sandbox for {session_id} did not become ready within {self._READY_TIMEOUT_SECONDS}s "
            f"(container={container_id}); last log tail: {last_output!r}"
        )

    async def clone_knowledge_repo(
        self,
        container_id: str,
        session_id: str,
        *,
        env: dict[str, str] | None = None,
    ) -> None:
        """Clone the knowledge repo into the sandbox if not already present."""
        probe = await self._runtime.exec(container_id, "test -d /workspace/.git", timeout=5)
        if probe.exit_code == 0:
            logger.debug(f"Knowledge repo already present in sandbox for {session_id}")
        else:
            result = await self._runtime.exec(
                container_id,
                "git clone $GIT_REPO_URL /workspace",
                timeout=60,
                env=env,
            )
            if result.exit_code != 0:
                raise RuntimeError(
                    f"Git clone failed in sandbox for {session_id} (exit {result.exit_code}): {result.output}"
                )

        # Always (re)apply identity and hook: both are repo-local, living on the
        # persistent /workspace PVC, but a fresh pod after suspend/resume may have
        # raced ahead of the original clone or predate this repo-local scheme.
        await self.setup_git_identity(container_id, session_id)
        await self.install_commit_msg_hook(container_id, session_id)

    async def setup_proxy(self, container_id: str, session_id: str, env: dict[str, str]) -> None:
        """Run sandbox proxy bootstrap so claimed warm sandboxes match cold-start behavior."""
        result = await self._runtime.exec(container_id, "setup-proxy.sh", timeout=30, env=env)
        if result.exit_code != 0:
            raise RuntimeError(
                f"Proxy setup failed in sandbox for {session_id} (exit {result.exit_code}): {result.output}"
            )

    async def setup_git_identity(self, container_id: str, session_id: str) -> None:
        """Configure git user.name and user.email for the knowledge repo.

        Written as repo-local config (``/workspace/.git/config``) rather than
        ``--global``: only ``/workspace`` is on the persistent PVC, so a global
        ``~/.gitconfig`` would be wiped whenever the pod is recreated (e.g. on
        suspend/resume), leaving the agent's first commit to fail with an unknown
        author. Repo-local config survives on the PVC.
        """
        name_tpl = self._author_for_session(session_id).replace("%s", session_id)
        if "<" in name_tpl and name_tpl.endswith(">"):
            name, _, email = name_tpl.rpartition("<")
            name, email = name.strip(), email.rstrip(">").strip()
        else:
            name, email = name_tpl, f"{session_id}@carapace"
        name_sh = name.replace("%h", "$(hostname)")
        email_sh = email.replace("%h", "$(hostname)")
        cmd = (
            "cd /workspace && "
            f"git config user.name {shlex.quote(name_sh)} && "
            f"git config user.email {shlex.quote(email_sh)}"
        )
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
            sandbox_name = self.sandbox_name_for_id(self.assigned_sandbox_id(session_id, sc))
            await self._runtime.suspend_sandbox(sandbox_name, sc.container_id)
            logger.info(f"Suspended sandbox for session {session_id}")

    async def destroy_session(self, session_id: str) -> None:
        """Permanently remove the sandbox and purge all tracking state."""
        sc = self._state.sessions.pop(session_id, None)
        sandbox_name = self.sandbox_name_for_id(self.assigned_sandbox_id(session_id, sc))
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
        sandbox_name = self.sandbox_name_for_id(self.assigned_sandbox_id(session_id, sc))
        if sc:
            await self._runtime.destroy_sandbox(session_id, sandbox_name, sc.container_id)
            logger.info(f"Reset sandbox for session {session_id}")
        else:
            existing_id = await self._runtime.sandbox_exists(sandbox_name)
            if existing_id:
                await self._runtime.destroy_sandbox(session_id, sandbox_name, existing_id)
                logger.info(f"Reset orphaned sandbox for session {session_id}")

    async def _cleanup_many(
        self,
        session_ids: list[str],
        cleanup_fn: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        cleanup = cleanup_fn or self.cleanup_session
        for sid in session_ids:
            await cleanup(sid)

    def _idle_session_ids(self) -> list[str]:
        now = time.time()
        return [sid for sid, sc in self._state.sessions.items() if now - sc.last_used > self._idle_timeout]

    async def cleanup_idle(self, cleanup_fn: Callable[[str], Awaitable[None]] | None = None) -> None:
        """Remove containers that have been idle longer than the timeout."""
        to_remove = self._idle_session_ids()
        if to_remove:
            logger.info(f"Cleaning up {len(to_remove)} idle sandbox session(s)")
        await self._cleanup_many(to_remove, cleanup_fn)

    async def cleanup_all(self, cleanup_fn: Callable[[str], Awaitable[None]] | None = None) -> None:
        """Remove all sandbox containers while preserving restartable session state."""
        session_ids = list(self._state.sessions)
        if session_ids:
            logger.info(f"Cleaning up all {len(session_ids)} sandbox session(s)")
        await self._cleanup_many(session_ids, cleanup_fn)

    async def cleanup_orphaned_sandboxes(self, known_sessions: set[str]) -> int:
        """Destroy sandbox resources whose session no longer exists on disk."""
        live = await self._runtime.list_sandboxes()
        removed = 0
        for sid, container_ids in live.items():
            if sid in known_sessions:
                continue
            for container_id in container_ids:
                sandbox_name = self.sandbox_name_for_live_resource(sid, container_id)
                await self._runtime.destroy_sandbox(sid, sandbox_name, container_id)
                logger.info(f"Removed orphaned sandbox {sandbox_name} for deleted session {sid}")
                removed += 1
        return removed

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
