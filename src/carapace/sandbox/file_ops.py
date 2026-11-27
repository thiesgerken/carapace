from __future__ import annotations

import base64
import json
import shlex
from typing import Protocol

from .container_scripts import SANDBOX_FILE_READ_BYTES_SCRIPT, build_file_read_script
from .container_scripts import (
    SANDBOX_STR_REPLACE_SCRIPT as _STR_REPLACE_SCRIPT,
)
from .runtime import ExecResult

# Maximum characters returned for a single text file read (body only; headers are extra).
MAX_READ_OUTPUT_CHARS = 65536
# Maximum ``limit`` (line window) accepted by the agent read tool.
READ_TOOL_MAX_LINE_WINDOW = 1000
# Maximum size of an image returned to the model as a raw multimodal block (Anthropic ≈ 5 MB/image).
READ_IMAGE_MAX_BYTES = 5 * 1024 * 1024
# Printed between read-tool metadata and file body (agents/UI can split on this line).
SANDBOX_READ_BODY_SEPARATOR = "-" * 24

FILE_READ_SCRIPT = build_file_read_script(SANDBOX_READ_BODY_SEPARATOR)


def _shell_path(path: str) -> str:
    """Return a shell-safe path, expanding ``~/`` inside the shell when needed."""
    if path.startswith("~/"):
        suffix = path[2:]
        # Keep $HOME unquoted so shell expands it; quote only the suffix.
        return "$HOME/" if not suffix else f"$HOME/{shlex.quote(suffix)}"
    return shlex.quote(path)


def _file_write_command(path: str) -> str:
    """Return the command that writes its stdin to *path*, creating the parent dir.

    The old file is removed first, so a read-only file can be replaced. A failed write
    removes the partial file.
    """
    shell_path = _shell_path(path)
    return (
        f'mkdir -p "$(dirname {shell_path})" && rm -f {shell_path} '
        f"&& {{ cat > {shell_path} || {{ rm -f {shell_path}; exit 1; }}; }}"
    )


def _line_count(content: str) -> int:
    if not content:
        return 0
    return content.count("\n") + 1


class ExecInSession(Protocol):
    async def __call__(
        self,
        session_id: str,
        command: str,
        timeout: int = ...,
        *,
        tool_call_id: str | None,
        stdin: bytes | None = ...,
    ) -> ExecResult: ...


class SandboxFileOps:
    def __init__(
        self,
        *,
        exec_in_session: ExecInSession,
    ) -> None:
        self._exec_in_session = exec_in_session

    async def file_read(self, session_id: str, path: str, *, offset: int = 0, limit: int = 100) -> str:
        """Read a text file (windowed), summarize a binary file, or list a directory inside the sandbox."""
        pq = shlex.quote(path)
        cmd = f"python3 -c {shlex.quote(FILE_READ_SCRIPT)} {pq} {int(offset)} {int(limit)} {MAX_READ_OUTPUT_CHARS}"
        result = await self._exec_in_session(session_id, cmd, timeout=30, tool_call_id=None)
        if result.exit_code != 0:
            return result.output or f"Error: cannot read {path}"
        output = result.output
        if output.startswith("::DIR::\n"):
            return f"Directory listing of {path}/:\n" + output[len("::DIR::\n") :]
        return output or "(empty file)"

    async def file_read_bytes(
        self,
        session_id: str,
        path: str,
        *,
        max_bytes: int = READ_IMAGE_MAX_BYTES,
    ) -> bytes | str:
        """Return raw file bytes (base64 over the wire), or an error/too-big message string."""
        pq = shlex.quote(path)
        cmd = f"python3 -c {shlex.quote(SANDBOX_FILE_READ_BYTES_SCRIPT)} {pq} {int(max_bytes)}"
        result = await self._exec_in_session(session_id, cmd, timeout=30, tool_call_id=None)
        if result.exit_code != 0:
            return result.output or f"Error: cannot read {path}"
        output = result.output
        if output.startswith("::TOOBIG::"):
            size = output[len("::TOOBIG::") :].strip()
            return f"File too large to return as an image: {size} bytes (limit {max_bytes})."
        if output.startswith("::B64::"):
            try:
                return base64.b64decode(output[len("::B64::") :])
            except ValueError as exc:  # binascii.Error subclasses ValueError
                return f"Error: cannot decode {path}: {exc}"
        return output or f"Error: cannot read {path}"

    async def file_write(self, session_id: str, path: str, content: str) -> ExecResult:
        """Write content to a file inside the sandbox."""
        result = await self._exec_in_session(
            session_id, _file_write_command(path), timeout=10, tool_call_id=None, stdin=content.encode()
        )
        if result.exit_code != 0:
            output = result.output or f"Error: cannot write {path} (exit {result.exit_code})."
            return ExecResult(stdout=result.stdout, exit_code=result.exit_code, output=output)
        return ExecResult(stdout="", exit_code=0, output=f"Wrote {_line_count(content)} line(s) to {path}.")

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
        # The strings can be arbitrarily large, so they travel on stdin, not in the command.
        payload = json.dumps({"old": old_string, "new": new_string, "replace_all": replace_all})
        cmd = f"python3 -c {shlex.quote(_STR_REPLACE_SCRIPT)} {shlex.quote(path)}"
        result = await self._exec_in_session(session_id, cmd, timeout=10, tool_call_id=None, stdin=payload.encode())
        output = result.output or f"Error: cannot replace in {path}"
        return ExecResult(stdout=result.stdout, exit_code=result.exit_code, output=output)
