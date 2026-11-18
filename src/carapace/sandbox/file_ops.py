from __future__ import annotations

import base64
import contextlib
import json
import secrets
import shlex
from collections.abc import Awaitable, Callable
from typing import Protocol

from loguru import logger

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


# Each chunk's base64 is inlined as a single shell argument (``printf %s <b64>``).
# Linux caps one argv string at MAX_ARG_STRLEN (128 KiB), but the tighter bound is
# the Kubernetes runtime: it ships the command as ``command=`` URL query params to
# the pod exec endpoint, and httpx rejects any URL component over 65536 chars
# (InvalidURL: "URL component 'query' too long"). Worst case (binary data whose
# base64 is all "/" or "+") every raw byte costs 4/3 * 3 = 4 url-encoded chars:
# 12 KiB raw -> 48 KiB encoded, leaving headroom for the path and the rest of the command.
SANDBOX_EXEC_CHUNK_BYTES = 12 * 1024


def _file_write_commands(path: str, content: str, *, mode: int | None, quote: bool) -> tuple[list[str], str | None]:
    """Return ``(writes, chmod)`` for writing *content* in argv-safe base64 chunks.

    Avoids "Argument list too long": each chunk's base64 is one shell argument. The
    first write creates the parent dir and truncates; later writes append. ``chmod`` is
    folded into the sole write when there is exactly one (keeps a credential write a
    single exec) and returned separately for multi-chunk writes, so a ``chmod`` failure
    isn't mistaken for a partial write. Empty content truncates the file.
    """
    shell_path = _shell_path(path, quote=quote)
    data = content.encode()
    writes: list[str] = []
    for start in range(0, len(data) or 1, SANDBOX_EXEC_CHUNK_BYTES):
        b64 = base64.b64encode(data[start : start + SANDBOX_EXEC_CHUNK_BYTES]).decode()
        if not writes:
            writes.append(
                f'mkdir -p "$(dirname {shell_path})" && rm -f {shell_path} '
                f"&& printf %s {b64} | base64 -d > {shell_path}"
            )
        else:
            writes.append(f"printf %s {b64} | base64 -d >> {shell_path}")
    chmod: str | None = None
    if mode is not None:
        chmod_cmd = f"chmod {mode:04o} {shell_path}"
        if len(writes) == 1:
            writes[0] += f" && {chmod_cmd}"
        else:
            chmod = chmod_cmd
    return writes, chmod


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
        result = await self._exec_in_session(session_id, cmd, timeout=30)
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

    @staticmethod
    async def _run_file_write(
        exec_one: Callable[[str], Awaitable[ExecResult]],
        path: str,
        content: str,
        *,
        mode: int | None,
        quote: bool,
    ) -> ExecResult:
        """Run the chunked write, cleaning up only a genuinely partial file.

        If a write fails *after* an earlier chunk already truncated and wrote the file,
        the file holds partial content — remove it (like ``upload_tmp_file``). A failure
        on the very first command leaves any pre-existing file untouched, and a ``chmod``
        failure happens after the content is fully written, so neither triggers cleanup.
        """
        writes, chmod_cmd = _file_write_commands(path, content, mode=mode, quote=quote)
        wrote_any = False
        for cmd in writes:
            result = await exec_one(cmd)
            if result.exit_code != 0:
                if wrote_any:
                    with contextlib.suppress(Exception):
                        await exec_one(f"rm -f {_shell_path(path, quote=quote)}")
                output = result.output or f"Error: cannot write {path} (exit {result.exit_code})."
                return ExecResult(stdout=result.stdout, exit_code=result.exit_code, output=output)
            wrote_any = True
        if chmod_cmd is not None:
            result = await exec_one(chmod_cmd)
            if result.exit_code != 0:
                output = result.output or f"Error: cannot chmod {path} (exit {result.exit_code})."
                return ExecResult(stdout=result.stdout, exit_code=result.exit_code, output=output)
        lines = _line_count(content)
        return ExecResult(stdout="", exit_code=0, output=f"Wrote {lines} line(s) to {path}.")

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
        return await self._run_file_write(
            lambda cmd: self._exec_in_session(session_id, cmd, timeout=10, workdir=workdir),
            path,
            content,
            mode=mode,
            quote=quote,
        )

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
        # The strings can be arbitrarily large, so they travel as a chunked payload file
        # instead of inline arguments (see SANDBOX_EXEC_CHUNK_BYTES); the script deletes it.
        payload_path = f"/tmp/carapace-str-replace-{secrets.token_hex(8)}.json"
        payload = json.dumps({"old": old_string, "new": new_string, "replace_all": replace_all})
        write_result = await self.file_write(session_id, payload_path, payload)
        if write_result.exit_code != 0:
            return write_result
        cmd = f"python3 -c {shlex.quote(_STR_REPLACE_SCRIPT)} {shlex.quote(path)} {payload_path}"
        result = await self._exec_in_session(session_id, cmd, timeout=10)
        output = result.output or f"Error: cannot replace in {path}"
        return ExecResult(stdout=result.stdout, exit_code=result.exit_code, output=output)

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
        return await self._run_file_write(
            lambda cmd: self._exec_in_container(sc, cmd, timeout=10, workdir=workdir),
            path,
            content,
            mode=mode,
            quote=quote,
        )

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
