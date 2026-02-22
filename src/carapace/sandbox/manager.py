from __future__ import annotations

import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger

from carapace.sandbox.runtime import ContainerConfig, ContainerGoneError, ContainerRuntime, Mount, SkillVenvError


@dataclass
class SessionContainer:
    container_id: str
    session_id: str
    ip_address: str | None = None
    created_at: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.time)
    activated_skills: list[str] = field(default_factory=list)


class SandboxManager:
    def __init__(
        self,
        runtime: ContainerRuntime,
        data_dir: Path,
        base_image: str = "carapace-sandbox:latest",
        network_name: str = "carapace-sandbox",
        idle_timeout_minutes: int = 15,
    ) -> None:
        self._runtime = runtime
        self._data_dir = data_dir
        self._base_image = base_image
        self._network_name = network_name
        self._idle_timeout = idle_timeout_minutes * 60
        self._sessions: dict[str, SessionContainer] = {}
        self._ip_to_session: dict[str, str] = {}
        logger.info(
            f"SandboxManager initialized (image={base_image}, "
            + f"network={network_name}, idle_timeout={idle_timeout_minutes}m)"
        )

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

        session_skills_dir = self._data_dir / "sessions" / session_id / "skills"
        session_skills_dir.mkdir(parents=True, exist_ok=True)
        session_tmp_dir = self._data_dir / "sessions" / session_id / "tmp"
        session_tmp_dir.mkdir(parents=True, exist_ok=True)

        mounts = self._build_mounts(session_id)
        config = ContainerConfig(
            image=self._base_image,
            name=f"carapace-session-{session_id}",
            labels={"carapace.session": session_id, "carapace.managed": "true"},
            mounts=mounts,
            network=self._network_name,
            command=["sleep", "infinity"],
        )

        container_id = await self._runtime.create(config)
        ip = await self._runtime.get_ip(container_id, self._network_name)

        sc = SessionContainer(
            container_id=container_id,
            session_id=session_id,
            ip_address=ip,
        )
        self._sessions[session_id] = sc
        if ip:
            self._ip_to_session[ip] = session_id

        logger.info(f"Created sandbox container {container_id[:12]} for session {session_id} (IP: {ip})")
        return sc

    def _build_mounts(self, session_id: str) -> list[Mount]:
        mounts: list[Mount] = []

        for filename in ("AGENTS.md", "SOUL.md", "USER.md"):
            path = self._data_dir / filename
            if path.exists():
                mounts.append(
                    Mount(
                        source=str(path.resolve()),
                        target=f"/workspace/{filename}",
                        read_only=True,
                    )
                )

        memory_dir = self._data_dir / "memory"
        if memory_dir.exists():
            mounts.append(
                Mount(
                    source=str(memory_dir.resolve()),
                    target="/workspace/memory",
                    read_only=True,
                )
            )

        session_skills = self._data_dir / "sessions" / session_id / "skills"
        mounts.append(
            Mount(
                source=str(session_skills.resolve()),
                target="/workspace/skills",
                read_only=False,
            )
        )

        session_tmp = self._data_dir / "sessions" / session_id / "tmp"
        mounts.append(
            Mount(
                source=str(session_tmp.resolve()),
                target="/workspace/tmp",
                read_only=False,
            )
        )

        return mounts

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
        sc = await self.ensure_session(session_id)

        master_skill_dir = self._data_dir / "skills" / skill_name
        if not master_skill_dir.exists():
            logger.warning(f"Skill '{skill_name}' not found for session {session_id}")
            return f"Skill '{skill_name}' not found."

        session_skill_dir = self._data_dir / "sessions" / session_id / "skills" / skill_name

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
        skill_host_path = self._data_dir / "sessions" / session_id / "skills" / skill_name
        build_name = f"carapace-build-{session_id[:8]}-{skill_name}"

        logger.info(f"Building venv for skill '{skill_name}' (session {session_id})")
        config = ContainerConfig(
            image=self._base_image,
            name=build_name,
            labels={"carapace.build": "true", "carapace.session": session_id},
            mounts=[Mount(source=str(skill_host_path.resolve()), target="/build", read_only=False)],
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
        session_skill_dir = self._data_dir / "sessions" / session_id / "skills" / skill_name
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

    def get_session_by_ip(self, ip: str) -> str | None:
        return self._ip_to_session.get(ip)

    def _cleanup_tracking(self, session_id: str) -> None:
        sc = self._sessions.pop(session_id, None)
        if sc and sc.ip_address:
            self._ip_to_session.pop(sc.ip_address, None)
