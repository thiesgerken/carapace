from __future__ import annotations

import re
import secrets
import shutil
import time
from pathlib import Path

from loguru import logger
from pydantic import BaseModel

from carapace.sandbox.runtime import ContainerConfig, ContainerGoneError, ContainerRuntime, Mount, SkillVenvError

_SKILL_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")


class SessionContainer(BaseModel):
    container_id: str
    session_id: str
    ip_address: str | None = None
    created_at: float
    last_used: float
    activated_skills: list[str] = []


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
        base_image: str = "carapace-sandbox:latest",
        network_name: str = "carapace-sandbox",
        idle_timeout_minutes: int = 15,
        host_data_dir: Path | None = None,
        proxy_url: str = "",
        internal_network: bool = False,
    ) -> None:
        self._runtime = runtime
        self._data_dir = data_dir
        self._host_data_dir = host_data_dir
        self._base_image = base_image
        self._network_name = network_name
        self._idle_timeout = idle_timeout_minutes * 60
        self._proxy_url = proxy_url
        self._internal_network = internal_network
        self._sessions: dict[str, SessionContainer] = {}
        self._token_to_session: dict[str, str] = {}
        self._session_tokens: dict[str, str] = {}
        self._allowed_domains: dict[str, set[str]] = {}
        logger.info(
            f"SandboxManager initialized (image={base_image}, "
            + f"network={network_name}, idle_timeout={idle_timeout_minutes}m)"
        )
        if proxy_url:
            logger.info(f"Proxy URL for sandbox containers: {proxy_url}")
        if host_data_dir:
            logger.info(f"Host data dir override: {host_data_dir} (container sees {data_dir})")

    async def ensure_session(self, session_id: str) -> SessionContainer:
        if session_id in self._sessions:
            sc = self._sessions[session_id]
            if await self._runtime.is_running(sc.container_id):
                logger.debug(f"Reusing existing container {sc.container_id[:12]} for session {session_id}")
                sc.last_used = time.time()
                return sc
            logger.warning(
                f"Container {sc.container_id[:12]} for session {session_id} is no longer running, recreating"
            )
            self._cleanup_tracking(session_id)

        session_workspace = self._data_dir / "sessions" / session_id / "workspace"
        (session_workspace / "skills").mkdir(parents=True, exist_ok=True)
        (session_workspace / "tmp").mkdir(parents=True, exist_ok=True)

        proxy_token = secrets.token_hex(16)
        self._token_to_session[proxy_token] = session_id
        self._session_tokens[session_id] = proxy_token

        mounts = self._build_mounts(session_id)
        env = self._build_proxy_env(proxy_token)
        config = ContainerConfig(
            image=self._base_image,
            name=f"carapace-session-{session_id}",
            labels={"carapace.session": session_id, "carapace.managed": "true"},
            mounts=mounts,
            network=self._network_name,
            internal_network=self._internal_network,
            command=["sleep", "infinity"],
            environment=env,
        )

        container_id = await self._runtime.create(config)
        ip = await self._runtime.get_ip(container_id, self._network_name)

        sc = SessionContainer(
            container_id=container_id,
            session_id=session_id,
            ip_address=ip,
            created_at=time.time(),
            last_used=time.time(),
        )
        self._sessions[session_id] = sc
        logger.info(f"Created sandbox container {container_id[:12]} for session {session_id} (IP: {ip})")
        return sc

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
            return str(resolved)
        return str(self._host_data_dir / rel)

    def _build_mounts(self, session_id: str) -> list[Mount]:
        mounts: list[Mount] = []

        for filename in ("AGENTS.md", "SOUL.md", "USER.md"):
            path = self._data_dir / filename
            if path.exists():
                mounts.append(
                    Mount(
                        source=self._host_path(path),
                        target=f"/workspace/{filename}",
                        read_only=True,
                    )
                )

        memory_dir = self._data_dir / "memory"
        if memory_dir.exists():
            mounts.append(
                Mount(
                    source=self._host_path(memory_dir),
                    target="/workspace/memory",
                    read_only=True,
                )
            )

        session_workspace = self._data_dir / "sessions" / session_id / "workspace"
        mounts.append(
            Mount(
                source=self._host_path(session_workspace / "skills"),
                target="/workspace/skills",
                read_only=False,
            )
        )

        mounts.append(
            Mount(
                source=self._host_path(session_workspace / "tmp"),
                target="/workspace/tmp",
                read_only=False,
            )
        )

        return mounts

    def _build_proxy_env(self, proxy_token: str) -> dict[str, str]:
        """Build HTTP_PROXY / NO_PROXY env vars for session containers."""
        if not self._proxy_url:
            return {}
        # Embed the per-session token as proxy auth: http://token@host:port
        scheme, rest = self._proxy_url.split("://", 1)
        authed_url = f"{scheme}://{proxy_token}@{rest}"
        # Extract host (without scheme/port/auth) for NO_PROXY
        no_proxy_host = rest.rsplit(":", 1)[0]
        return {
            "HTTP_PROXY": authed_url,
            "HTTPS_PROXY": authed_url,
            "http_proxy": authed_url,
            "https_proxy": authed_url,
            "NO_PROXY": no_proxy_host,
            "no_proxy": no_proxy_host,
        }

    async def exec_command(self, session_id: str, command: str, timeout: int = 30) -> str:
        sc = await self.ensure_session(session_id)
        sc.last_used = time.time()
        logger.debug(f"Exec in session {session_id}: {command}")

        try:
            result = await self._runtime.exec(sc.container_id, command, timeout=timeout)
        except ContainerGoneError:
            logger.warning(f"Container gone for session {session_id}, recreating sandbox")
            self._cleanup_tracking(session_id)
            sc = await self.ensure_session(session_id)
            result = await self._runtime.exec(sc.container_id, command, timeout=timeout)

        output = result.output
        if result.exit_code != 0 and f"[exit code: {result.exit_code}]" not in output:
            logger.debug(f"Command failed in session {session_id} (exit {result.exit_code}): {command}")
            output += f"\n[exit code: {result.exit_code}]"
        return output or "(no output)"

    async def activate_skill(self, session_id: str, skill_name: str) -> str:
        if err := _validate_skill_name(skill_name):
            return err

        sc = await self.ensure_session(session_id)

        master_skill_dir = self._data_dir / "skills" / skill_name
        if not master_skill_dir.exists():
            logger.warning(f"Skill '{skill_name}' not found for session {session_id}")
            return f"Skill '{skill_name}' not found."

        session_skill_dir = self._data_dir / "sessions" / session_id / "workspace" / "skills" / skill_name

        if session_skill_dir.exists():
            shutil.rmtree(session_skill_dir)
        shutil.copytree(master_skill_dir, session_skill_dir)

        has_pyproject = (session_skill_dir / "pyproject.toml").exists()
        venv_msg = ""
        if has_pyproject:
            try:
                await self._build_skill_venv(session_id, skill_name)
                venv_msg = "Venv built successfully."
            except SkillVenvError as exc:
                sc.activated_skills.append(skill_name)
                sc.last_used = time.time()
                logger.info(f"Activated skill '{skill_name}' in session {session_id} (with errors)")
                raise SkillVenvError(
                    f"Skill '{skill_name}' activated at /workspace/skills/{skill_name}/ but "
                    f"dependency install failed: {exc}\n"
                    "The skill was copied but its Python dependencies are NOT available. "
                    "You may need to install them manually inside the sandbox."
                ) from exc

        sc.activated_skills.append(skill_name)
        sc.last_used = time.time()

        logger.info(f"Activated skill '{skill_name}' in session {session_id}")
        result = f"Skill '{skill_name}' activated at /workspace/skills/{skill_name}/"
        if venv_msg:
            result += f"\n{venv_msg}"
        return result

    async def _build_skill_venv(self, session_id: str, skill_name: str) -> None:
        """Build a venv in an ephemeral build container. Raises SkillVenvError on failure."""
        if err := _validate_skill_name(skill_name):
            raise SkillVenvError(err)

        skill_host_path = self._data_dir / "sessions" / session_id / "workspace" / "skills" / skill_name
        build_name = f"carapace-build-{session_id[:8]}-{skill_name}"

        logger.info(f"Building venv for skill '{skill_name}' (session {session_id})")
        config = ContainerConfig(
            image=self._base_image,
            name=build_name,
            labels={"carapace.build": "true", "carapace.session": session_id},
            mounts=[Mount(source=self._host_path(skill_host_path), target="/build", read_only=False)],
            command=["sleep", "infinity"],
        )

        container_id: str | None = None
        try:
            container_id = await self._runtime.create(config)
            result = await self._runtime.exec(
                container_id,
                ["uv", "sync", "--directory", "/build"],
                timeout=120,
            )
            if result.exit_code == 0:
                logger.info(f"Venv built successfully for skill '{skill_name}'")
                return
            logger.error(f"Venv build failed for skill '{skill_name}' (exit {result.exit_code}): {result.output[:300]}")
            raise SkillVenvError(f"exit {result.exit_code}: {result.output[:500]}")
        except SkillVenvError:
            raise
        except Exception as exc:
            logger.error(f"Venv build crashed for skill '{skill_name}': {exc}")
            raise SkillVenvError(str(exc)) from exc
        finally:
            if container_id:
                await self._runtime.remove(container_id)

    async def save_skill(self, session_id: str, skill_name: str) -> str:
        if err := _validate_skill_name(skill_name):
            return err

        session_skill_dir = self._data_dir / "sessions" / session_id / "workspace" / "skills" / skill_name
        if not session_skill_dir.exists():
            logger.warning(f"Cannot save skill '{skill_name}' — not found in session {session_id}")
            return f"Skill '{skill_name}' not found in session."

        master_skill_dir = self._data_dir / "skills" / skill_name
        master_skill_dir.parent.mkdir(parents=True, exist_ok=True)

        if master_skill_dir.exists():
            shutil.rmtree(master_skill_dir)

        shutil.copytree(
            session_skill_dir,
            master_skill_dir,
            ignore=shutil.ignore_patterns(".venv", "__pycache__"),
        )

        logger.info(f"Saved skill '{skill_name}' from session {session_id} to {master_skill_dir}")
        return f"Skill '{skill_name}' saved to data/skills/{skill_name}/"

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

    def get_session_by_token(self, token: str) -> str | None:
        return self._token_to_session.get(token)

    def allow_domains(self, session_id: str, domains: set[str]) -> None:
        """Add *domains* to the proxy allowlist for *session_id*."""
        existing = self._allowed_domains.setdefault(session_id, set())
        existing.update(domains)
        logger.info(f"Allowed domains for session {session_id}: {existing}")

    def get_allowed_domains(self, session_id: str) -> set[str]:
        return self._allowed_domains.get(session_id, set())

    def _cleanup_tracking(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
        token = self._session_tokens.pop(session_id, None)
        if token:
            self._token_to_session.pop(token, None)
        self._allowed_domains.pop(session_id, None)
