from __future__ import annotations

import base64
import shlex
from collections.abc import Awaitable, Callable
from typing import Annotated, Literal

from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from ..models.skills import SkillCommandDecl
from .file_ops import ContextFileCredential, SessionContainerLike, WrittenContextFile
from .runtime import ExecResult, SkillActivationError, SkillActivationInputs

SKILL_ACTIVATOR_PROTOCOL_VERSION = 1
SKILL_ACTIVATOR_MARKER = "@@CARAPACE_SKILL_ACTIVATOR@@"
SKILL_COMMAND_SHIM_DIR = "/workspace/.carapace/bin"

type ActivationCommand = tuple[str, str]
type ActivationMessage = Annotated[str, Field(min_length=1, max_length=1000)]


class SkillActivatorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    protocol_version: Literal[1] = SKILL_ACTIVATOR_PROTOCOL_VERSION
    skill: str
    skill_dir: str
    workspace: str
    source_revision: Annotated[str, Field(pattern=r"^[0-9a-f]{40,64}$")]
    commands: list[SkillCommandDecl] = []


class SkillActivatorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    protocol_version: Literal[1]
    command_overrides: dict[str, str] = Field(default_factory=dict, max_length=256)
    messages: list[ActivationMessage] = Field(default_factory=list, max_length=50)
    error: Annotated[str, Field(min_length=1, max_length=1000)] | None = None

    @field_validator("messages", mode="before")
    @classmethod
    def _validate_messages(cls, value: object) -> object:
        if isinstance(value, list):
            return [cls._single_line(item, "activation message") for item in value]
        return value

    @field_validator("error", mode="before")
    @classmethod
    def _validate_error(cls, value: object) -> object:
        if isinstance(value, str):
            return cls._single_line(value, "activation error")
        return value

    @staticmethod
    def _single_line(value: object, label: str) -> object:
        if not isinstance(value, str):
            return value
        stripped = value.strip()
        if "\n" in stripped or "\r" in stripped:
            raise ValueError(f"{label} must be a single line")
        return stripped

    @model_validator(mode="after")
    def _validate_error_result(self) -> SkillActivatorResponse:
        if self.error is not None and (self.command_overrides or self.messages):
            raise ValueError("an activation error response cannot include overrides or messages")
        return self


class SkillActivationRunner:
    def __init__(
        self,
        *,
        knowledge_workdir: str,
        activator_path: str | None,
        activator_timeout: int,
        get_activation_inputs: Callable[[str, str], Awaitable[SkillActivationInputs]],
        exec_in_session: Callable[..., Awaitable[ExecResult]],
        exec_in_container: Callable[..., Awaitable[ExecResult]],
        write_context_file_credentials: Callable[..., Awaitable[list[WrittenContextFile]]],
        delete_context_file_credentials: Callable[[str, list[WrittenContextFile]], Awaitable[None]],
    ) -> None:
        self._knowledge_workdir = knowledge_workdir
        self._activator_path = activator_path
        self._activator_timeout = activator_timeout
        self._get_activation_inputs = get_activation_inputs
        self._exec_in_session = exec_in_session
        self._exec_in_container = exec_in_container
        self._write_context_file_credentials = write_context_file_credentials
        self._delete_context_file_credentials = delete_context_file_credentials

    @property
    def enabled(self) -> bool:
        return self._activator_path is not None

    def _command_shim_path(self, alias: str) -> str:
        return f"{SKILL_COMMAND_SHIM_DIR}/{alias}"

    def _command_wrapper_content(self, command: str) -> str:
        return f'#!/bin/sh\nexec {command} "$@"\n'

    async def register_command_aliases(
        self,
        command_aliases: list[ActivationCommand],
        *,
        session_id: str | None = None,
        sc: SessionContainerLike | None = None,
    ) -> list[str]:
        if not command_aliases:
            return []

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

        names = ", ".join(alias for alias, _command in command_aliases)
        return [f"Command aliases registered: {names}."]

    def _activation_file_credentials(
        self,
        skill_name: str,
        activation_inputs: SkillActivationInputs,
    ) -> list[ContextFileCredential]:
        return [(skill_name, cred.path, cred.value) for cred in activation_inputs.file_credentials]

    def _invocation(self, request: SkillActivatorRequest) -> str:
        assert self._activator_path is not None
        path = shlex.quote(self._activator_path)
        encoded = base64.b64encode(request.model_dump_json().encode()).decode()
        return f"test -x {path} || exit 126; exec {path} --request-base64 {shlex.quote(encoded)}"

    def _parse_response(self, output: str) -> SkillActivatorResponse:
        marked = [
            line.removeprefix(SKILL_ACTIVATOR_MARKER)
            for line in output.splitlines()
            if line.startswith(SKILL_ACTIVATOR_MARKER)
        ]
        if len(marked) != 1:
            raise SkillActivationError("skill activator must emit exactly one marked JSON response")
        try:
            return SkillActivatorResponse.model_validate_json(marked[0])
        except ValidationError as exc:
            raise SkillActivationError("skill activator returned an invalid protocol response") from exc

    def _resolved_commands(
        self,
        declared: list[ActivationCommand],
        overrides: dict[str, str],
    ) -> list[ActivationCommand]:
        resolved = dict(declared)
        for alias, command in overrides.items():
            if alias not in resolved:
                raise SkillActivationError(f"skill activator returned an override for undeclared command {alias!r}")
            try:
                resolved[alias] = SkillCommandDecl(name=alias, command=command).command
            except ValidationError as exc:
                raise SkillActivationError(
                    f"skill activator returned an invalid override for command {alias!r}"
                ) from exc
        return [(alias, resolved[alias]) for alias, _command in declared]

    async def _exec_activator(
        self,
        skill_name: str,
        request: SkillActivatorRequest,
        activation_inputs: SkillActivationInputs,
        *,
        session_id: str | None = None,
        sc: SessionContainerLike | None = None,
    ) -> ExecResult:
        if (session_id is None) == (sc is None):
            raise ValueError("Exactly one of session_id and sc must be set")

        command = self._invocation(request)
        skill_dir = f"/workspace/skills/{skill_name}"
        extra_env = activation_inputs.environment or None
        file_creds = self._activation_file_credentials(skill_name, activation_inputs)
        if session_id is not None:
            return await self._exec_in_session(
                session_id,
                command,
                timeout=self._activator_timeout,
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
                command,
                timeout=self._activator_timeout,
                workdir=skill_dir,
                bypass_proxy=True,
                extra_env=extra_env,
            )
        finally:
            if written_files:
                await self._delete_context_file_credentials(sc.session_id, written_files)

    async def activate(
        self,
        sc: SessionContainerLike,
        skill_name: str,
        source_revision: str | None,
        *,
        command_aliases: list[ActivationCommand],
        run_session_id: str | None = None,
    ) -> list[str]:
        resolved_commands = command_aliases
        status_lines: list[str] = []

        if self.enabled:
            if source_revision is None:
                raise SkillActivationError("cannot run the skill activator without a committed source revision")
            request = SkillActivatorRequest(
                skill=skill_name,
                skill_dir=f"/workspace/skills/{skill_name}",
                workspace=self._knowledge_workdir,
                source_revision=source_revision,
                commands=[SkillCommandDecl(name=name, command=command) for name, command in command_aliases],
            )
            activation_inputs = await self._get_activation_inputs(run_session_id or sc.session_id, skill_name)
            logger.info(f"Running sandbox skill activator for skill '{skill_name}'")
            result = await self._exec_activator(
                skill_name,
                request,
                activation_inputs,
                session_id=run_session_id,
                sc=None if run_session_id is not None else sc,
            )

            response: SkillActivatorResponse | None = None
            try:
                response = self._parse_response(result.output)
            except SkillActivationError:
                if result.exit_code == 0:
                    raise

            if result.exit_code != 0:
                if response is not None and response.error is not None:
                    detail = response.error
                elif result.exit_code == 126:
                    detail = f"configured skill activator is missing or not executable: {self._activator_path}"
                elif result.exit_code == -1:
                    detail = f"skill activator timed out after {self._activator_timeout} seconds"
                else:
                    detail = f"skill activator exited with status {result.exit_code}"
                raise SkillActivationError(detail)

            assert response is not None
            if response.error is not None:
                raise SkillActivationError(response.error)
            resolved_commands = self._resolved_commands(command_aliases, response.command_overrides)
            status_lines.extend(response.messages)

        status_lines.extend(
            await self.register_command_aliases(
                resolved_commands,
                session_id=run_session_id,
                sc=None if run_session_id is not None else sc,
            )
        )
        return status_lines
