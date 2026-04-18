from __future__ import annotations

import base64
import shlex
from collections.abc import Awaitable, Callable
from typing import Protocol

from loguru import logger

from carapace.sandbox.container_scripts import (
    SANDBOX_STR_REPLACE_SCRIPT as _STR_REPLACE_SCRIPT,
)
from carapace.sandbox.container_scripts import build_file_read_script
from carapace.sandbox.runtime import ExecResult

# Maximum characters returned for a single text file read (body only; headers are extra).
MAX_READ_OUTPUT_CHARS = 65536
# Maximum ``limit`` (line window) accepted by the agent read tool.
READ_TOOL_MAX_LINE_WINDOW = 1000
# Printed between read-tool metadata and file body (agents/UI can split on this line).
SANDBOX_READ_BODY_SEPARATOR = "-" * 24

FILE_READ_SCRIPT = build_file_read_script(SANDBOX_READ_BODY_SEPARATOR)

type ContextFileCredential = tuple[str, str, str]
type WrittenContextFile = tuple[str, str]


class SessionContainerLike(Protocol):
    session_id: str


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


class SandboxFileOps:
    def __init__(
        self,
        *,
        exec_in_session: Callable[..., Awaitable[ExecResult]],
        exec_in_container: Callable[..., Awaitable[ExecResult]],
        get_session: Callable[[str], SessionContainerLike | None],
    ) -> None:
        self._exec_in_session = exec_in_session
        self._exec_in_container = exec_in_container
        self._get_session = get_session

    async def file_read(self, session_id: str, path: str, *, offset: int = 0, limit: int = 100) -> str:
        """Read a text file (windowed), summarize a binary file, or list a directory inside the sandbox."""
        pq = shlex.quote(path)
        cmd = f"python3 -c {shlex.quote(FILE_READ_SCRIPT)} {pq} {int(offset)} {int(limit)} {MAX_READ_OUTPUT_CHARS}"
        result = await self._exec_in_session(session_id, cmd, timeout=30)
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
        result = await self._exec_in_session(session_id, cmd, timeout=10, workdir=workdir)
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
        result = await self._exec_in_session(session_id, cmd, timeout=10)
        output = result.output or f"Error: cannot replace in {path}"
        return ExecResult(exit_code=result.exit_code, output=output)

    async def file_write_in_container(
        self,
        sc: SessionContainerLike,
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

    async def file_delete_in_container(
        self,
        sc: SessionContainerLike,
        path: str,
        *,
        workdir: str | None = None,
        quote: bool = True,
    ) -> ExecResult:
        """Delete a file using an existing container while the exec lock is already held."""
        shell_path = _shell_path(path, quote=quote)
        cmd = f"rm -f {shell_path}"
        return await self._exec_in_container(sc, cmd, timeout=5, workdir=workdir)

    async def write_context_file_credentials(
        self,
        sc: SessionContainerLike,
        context_file_creds: list[ContextFileCredential],
    ) -> list[WrittenContextFile]:
        """Write file-based credentials into the container, returning written ``(file_path, skill_name)`` pairs."""
        written: list[WrittenContextFile] = []
        for skill_name, file_path, value in context_file_creds:
            skill_dir = f"/workspace/skills/{skill_name}"
            result = await self.file_write_in_container(
                sc,
                file_path,
                value,
                mode=0o400,
                workdir=skill_dir,
                quote=False,
            )
            if result.exit_code != 0:
                logger.error(f"Failed to write credential file {file_path} for {skill_name}: {result.output}")
            else:
                written.append((file_path, skill_name))
        return written

    async def delete_context_file_credentials(
        self,
        session_id: str,
        written_files: list[WrittenContextFile],
    ) -> None:
        """Delete file-based credentials that were written for an exec."""
        sc = self._get_session(session_id)
        if sc is None:
            return
        for file_path, skill_name in written_files:
            skill_dir = f"/workspace/skills/{skill_name}"
            try:
                result = await self.file_delete_in_container(sc, file_path, workdir=skill_dir, quote=False)
            except Exception as exc:
                logger.warning(f"Could not delete credential file {file_path} (skill {skill_name!r}) after exec: {exc}")
                continue
            if result.exit_code != 0:
                logger.warning(
                    f"Failed to delete credential file {file_path} (skill {skill_name!r}) after exec: "
                    f"{result.output or '(no output)'}"
                )
