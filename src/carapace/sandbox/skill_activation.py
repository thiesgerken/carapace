from __future__ import annotations

import base64
import shlex
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from carapace.sandbox.file_ops import ContextFileCredential, SessionContainerLike, WrittenContextFile
from carapace.sandbox.runtime import ExecResult, SkillActivationError, SkillActivationInputs

SKILL_COMMAND_SHIM_DIR = "/root/.carapace/bin"


@dataclass(frozen=True)
class SkillActivationProvider:
    name: str
    trusted_files: tuple[str, ...]
    status_message: str
    command: str
    timeout: int = 120
    matcher: Callable[[Path], bool] | None = None

    def matches(self, skill_dir: Path) -> bool:
        if self.matcher is None:
            return False
        return self.matcher(skill_dir)


def _has_all_files(*names: str) -> Callable[[Path], bool]:
    def _matcher(skill_dir: Path) -> bool:
        return all((skill_dir / name).exists() for name in names)

    return _matcher


def _matches_npm_provider(skill_dir: Path) -> bool:
    return (
        _has_all_files("package.json", "package-lock.json")(skill_dir) and not (skill_dir / "pnpm-lock.yaml").exists()
    )


SKILL_ACTIVATION_PROVIDERS: tuple[SkillActivationProvider, ...] = (
    SkillActivationProvider(
        name="uv",
        trusted_files=("pyproject.toml", "uv.lock"),
        status_message="Python dependencies synced.",
        command="uv sync --locked",
        matcher=_has_all_files("pyproject.toml", "uv.lock"),
    ),
    SkillActivationProvider(
        name="npm",
        trusted_files=("package.json", "package-lock.json"),
        status_message="npm dependencies installed.",
        command="npm ci",
        matcher=_matches_npm_provider,
    ),
    SkillActivationProvider(
        name="pnpm",
        trusted_files=("package.json", "pnpm-lock.yaml"),
        status_message="pnpm dependencies installed.",
        command="pnpm install --frozen-lockfile",
        matcher=_has_all_files("package.json", "pnpm-lock.yaml"),
    ),
    SkillActivationProvider(
        name="setup.sh",
        trusted_files=("setup.sh",),
        status_message="setup.sh completed.",
        command="sh ./setup.sh",
        matcher=_has_all_files("setup.sh"),
    ),
)


class SkillActivationRunner:
    def __init__(
        self,
        *,
        knowledge_workdir: str,
        get_activation_inputs: Callable[[str, str], Awaitable[SkillActivationInputs]],
        exec_in_session: Callable[..., Awaitable[ExecResult]],
        exec_in_container: Callable[..., Awaitable[ExecResult]],
        write_context_file_credentials: Callable[..., Awaitable[list[WrittenContextFile]]],
        delete_context_file_credentials: Callable[[str, list[WrittenContextFile]], Awaitable[None]],
    ) -> None:
        self._knowledge_workdir = knowledge_workdir
        self._get_activation_inputs = get_activation_inputs
        self._exec_in_session = exec_in_session
        self._exec_in_container = exec_in_container
        self._write_context_file_credentials = write_context_file_credentials
        self._delete_context_file_credentials = delete_context_file_credentials

    def matching_providers(self, skill_dir: Path) -> list[SkillActivationProvider]:
        return [provider for provider in SKILL_ACTIVATION_PROVIDERS if provider.matches(skill_dir)]

    def trusted_files_for(self, providers: list[SkillActivationProvider]) -> set[str]:
        trusted_files = {"carapace.yaml"}
        for provider in providers:
            trusted_files.update(provider.trusted_files)
        return trusted_files

    async def restore_trusted_files(
        self,
        skill_name: str,
        trusted_files: set[str],
        *,
        session_id: str | None = None,
        sc: SessionContainerLike | None = None,
    ) -> None:
        if (session_id is None) == (sc is None):
            raise ValueError("Exactly one of session_id and sc must be set")

        skill_path = f"skills/{shlex.quote(skill_name)}"
        for fname in sorted(trusted_files):
            command = f"git checkout @{{upstream}} -- {skill_path}/{fname} 2>/dev/null || true"
            if session_id is not None:
                await self._exec_in_session(
                    session_id,
                    command,
                    timeout=10,
                    workdir=self._knowledge_workdir,
                )
                continue

            assert sc is not None
            await self._exec_in_container(
                sc,
                command,
                timeout=10,
                workdir=self._knowledge_workdir,
            )

    async def restore_and_run_detected_providers(
        self,
        sc: SessionContainerLike,
        skill_name: str,
        skill_dir: Path,
        *,
        command_aliases: list[tuple[str, str]] | None = None,
        run_session_id: str | None = None,
    ) -> list[str]:
        providers = self.matching_providers(skill_dir)
        if not providers and not command_aliases:
            return []

        trusted_files = self.trusted_files_for(providers)
        await self.restore_trusted_files(
            skill_name,
            trusted_files,
            session_id=run_session_id,
            sc=None if run_session_id is not None else sc,
        )

        activation_inputs = await self._get_activation_inputs(run_session_id or sc.session_id, skill_name)
        if run_session_id is not None:
            status_lines = await self.run_providers(
                skill_name,
                providers,
                activation_inputs,
                session_id=run_session_id,
            )
            if command_aliases:
                status_lines.extend(
                    await self.register_command_aliases(
                        command_aliases,
                        session_id=run_session_id,
                    )
                )
            return status_lines

        status_lines = await self.run_providers(skill_name, providers, activation_inputs, sc=sc)
        if command_aliases:
            status_lines.extend(await self.register_command_aliases(command_aliases, sc=sc))
        return status_lines

    def _command_shim_path(self, alias: str) -> str:
        return f"{SKILL_COMMAND_SHIM_DIR}/{alias}"

    def _command_wrapper_content(self, command: str) -> str:
        return f'#!/bin/sh\nexec {command} "$@"\n'

    async def register_command_aliases(
        self,
        command_aliases: list[tuple[str, str]],
        *,
        session_id: str | None = None,
        sc: SessionContainerLike | None = None,
    ) -> list[str]:
        if (session_id is None) == (sc is None):
            raise ValueError("Exactly one of session_id and sc must be set")

        shell_commands = [f"mkdir -p {shlex.quote(SKILL_COMMAND_SHIM_DIR)}"]

        for alias, command in command_aliases:
            wrapper = self._command_wrapper_content(command)
            wrapper_b64 = base64.b64encode(wrapper.encode()).decode()
            shell_commands.append(
                f"printf %s {shlex.quote(wrapper_b64)} | base64 -d > {shlex.quote(self._command_shim_path(alias))}"
            )
            shell_commands.append(f"chmod +x {shlex.quote(self._command_shim_path(alias))}")

        command = " && ".join(shell_commands)
        if session_id is not None:
            result = await self._exec_in_session(
                session_id,
                command,
                timeout=30,
                bypass_proxy=True,
                workdir=self._knowledge_workdir,
            )
        else:
            assert sc is not None
            result = await self._exec_in_container(
                sc,
                command,
                timeout=30,
                bypass_proxy=True,
                workdir=self._knowledge_workdir,
            )

        if result.exit_code != 0:
            raise SkillActivationError(f"command alias registration exit {result.exit_code}: {result.output[:500]}")

        if not command_aliases:
            return []
        names = ", ".join(alias for alias, _command in command_aliases)
        return [f"Command aliases registered: {names}."]

    def _activation_file_credentials(
        self,
        skill_name: str,
        activation_inputs: SkillActivationInputs,
    ) -> list[ContextFileCredential]:
        return [(skill_name, cred.path, cred.value) for cred in activation_inputs.file_credentials]

    async def run_provider(
        self,
        skill_name: str,
        provider: SkillActivationProvider,
        activation_inputs: SkillActivationInputs,
        *,
        session_id: str | None = None,
        sc: SessionContainerLike | None = None,
    ) -> ExecResult:
        if (session_id is None) == (sc is None):
            raise ValueError("Exactly one of session_id and sc must be set")

        skill_dir = f"/workspace/skills/{skill_name}"
        extra_env = activation_inputs.environment or None
        file_creds = self._activation_file_credentials(skill_name, activation_inputs)
        if session_id is not None:
            return await self._exec_in_session(
                session_id,
                provider.command,
                timeout=provider.timeout,
                bypass_proxy=True,
                workdir=skill_dir,
                extra_env=extra_env,
                context_file_creds=file_creds or None,
            )

        assert sc is not None
        written_files: list[WrittenContextFile] = []
        try:
            if file_creds:
                written_files = await self._write_context_file_credentials(sc, file_creds)
            return await self._exec_in_container(
                sc,
                provider.command,
                timeout=provider.timeout,
                workdir=skill_dir,
                bypass_proxy=True,
                extra_env=extra_env,
            )
        finally:
            if written_files:
                await self._delete_context_file_credentials(sc.session_id, written_files)

    async def run_providers(
        self,
        skill_name: str,
        providers: list[SkillActivationProvider],
        activation_inputs: SkillActivationInputs,
        *,
        session_id: str | None = None,
        sc: SessionContainerLike | None = None,
    ) -> list[str]:
        if (session_id is None) == (sc is None):
            raise ValueError("Exactly one of session_id and sc must be set")

        status_lines: list[str] = []
        for provider in providers:
            logger.info(f"Running skill activation provider '{provider.name}' for skill '{skill_name}'")
            result = await self.run_provider(
                skill_name,
                provider,
                activation_inputs,
                session_id=session_id,
                sc=sc,
            )
            if result.exit_code != 0:
                logger.error(
                    f"Skill activation provider '{provider.name}' failed for '{skill_name}' "
                    + f"(exit {result.exit_code}): {result.output[:300]}"
                )
                raise SkillActivationError(f"{provider.name} exit {result.exit_code}: {result.output[:500]}")
            status_lines.append(provider.status_message)

        return status_lines
