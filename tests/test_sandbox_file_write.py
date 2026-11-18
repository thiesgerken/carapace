"""Tests for chunked sandbox file writes (avoiding shell "Argument list too long")."""

from __future__ import annotations

import base64
import re

import httpx
import pytest

from carapace.sandbox.file_ops import (
    SANDBOX_EXEC_CHUNK_BYTES,
    SandboxFileOps,
    _file_write_commands,
)
from carapace.sandbox.runtime import ExecResult

# Linux caps a single argv string at MAX_ARG_STRLEN (128 KiB).
MAX_ARG_STRLEN = 128 * 1024


def _reconstruct(commands: list[str]) -> bytes:
    """Decode the base64 payloads back into the bytes the commands would write."""
    out = bytearray()
    for cmd in commands:
        for b64 in re.findall(r"printf %s (\S+) \| base64 -d", cmd):
            out += base64.b64decode(b64)
    return bytes(out)


def test_small_write_is_single_command() -> None:
    writes, chmod = _file_write_commands("/tmp/x.txt", "hello", mode=None, quote=True)
    assert len(writes) == 1
    assert chmod is None
    assert writes[0].startswith('mkdir -p "$(dirname')
    assert _reconstruct(writes) == b"hello"


def test_mode_folds_into_sole_write() -> None:
    # Single chunk + mode stays one exec (preserves prior behaviour for credential writes).
    writes, chmod = _file_write_commands("/tmp/x", "v", mode=0o400, quote=True)
    assert len(writes) == 1
    assert chmod is None
    assert writes[0].endswith("&& chmod 0400 /tmp/x")


def test_large_write_chunks_stay_within_arg_limit() -> None:
    content = "A" * (300 * 1024)
    writes, chmod = _file_write_commands("/tmp/big.bin", content, mode=0o644, quote=True)
    assert len(writes) > 1
    assert all(len(cmd) < MAX_ARG_STRLEN for cmd in writes)
    # First truncates, the rest append.
    assert " > /tmp/big.bin" in writes[0]
    assert all(" >> /tmp/big.bin" in cmd for cmd in writes[1:])
    # Multi-chunk: chmod is a separate trailing command, not folded into a data write.
    assert chmod == "chmod 0644 /tmp/big.bin"
    assert all("chmod" not in cmd for cmd in writes)
    assert _reconstruct(writes).decode() == content


def test_empty_content_truncates_file() -> None:
    writes, chmod = _file_write_commands("/tmp/x", "", mode=None, quote=True)
    assert len(writes) == 1
    assert chmod is None
    assert " > /tmp/x" in writes[0]
    assert _reconstruct(writes) == b""


def test_chunk_boundary_count() -> None:
    content = "B" * (SANDBOX_EXEC_CHUNK_BYTES * 2 + 1)
    writes, chmod = _file_write_commands("/tmp/x", content, mode=None, quote=True)
    assert len(writes) == 3
    assert chmod is None
    assert _reconstruct(writes).decode() == content


def _assert_fits_kubernetes_exec_url(cmd: str) -> None:
    # The Kubernetes runtime sends the command as URL query params; httpx caps a URL
    # component at 65536 chars and raises InvalidURL beyond that.
    httpx.URL("https://k8s/api/v1/pods/p/exec", params={"command": ["bash", "-c", cmd], "container": "sandbox"})


# Text whose UTF-8 encodes to bytes heavy in "+/" base64; the exact worst case is
# binary data, covered by test_binary_upload_chunks_fit_kubernetes_exec_url.
_LARGE_CONTENT = "\uffff" * SANDBOX_EXEC_CHUNK_BYTES


def test_binary_upload_chunks_fit_kubernetes_exec_url() -> None:
    # b"\xff" base64-encodes to all "/", each url-encoded to "%2F": the worst case.
    cmd = f"printf %s {base64.b64encode(b'\xff' * SANDBOX_EXEC_CHUNK_BYTES).decode()} | base64 -d >> /tmp/upload.bin"
    _assert_fits_kubernetes_exec_url(cmd)


def test_chunks_fit_kubernetes_exec_url() -> None:
    writes, _ = _file_write_commands("/workspace/" + "d" * 200 + "/out.txt", _LARGE_CONTENT, mode=0o644, quote=True)
    for cmd in writes:
        _assert_fits_kubernetes_exec_url(cmd)


@pytest.mark.asyncio
async def test_large_str_replace_fits_kubernetes_exec_url() -> None:
    calls: list[str] = []

    async def exec_in_session(_session_id: str, cmd: str, **_kwargs: object) -> ExecResult:
        calls.append(cmd)
        return ExecResult(stdout="", exit_code=0, output="ok")

    ops = SandboxFileOps(exec_in_session=exec_in_session, exec_in_container=exec_in_session, get_session=lambda _: None)
    result = await ops.file_str_replace("s", "/workspace/big.txt", _LARGE_CONTENT, _LARGE_CONTENT)

    assert result.exit_code == 0
    assert len(calls) > 2  # chunked payload writes, then the replace script
    assert calls[-1].startswith("python3 -c ")
    for cmd in calls:
        _assert_fits_kubernetes_exec_url(cmd)


async def _run(exec_one, content, *, mode=None, path="/tmp/f") -> tuple[ExecResult, list[str]]:
    calls: list[str] = []

    async def wrapped(cmd: str) -> ExecResult:
        calls.append(cmd)
        return await exec_one(cmd, calls)

    result = await SandboxFileOps._run_file_write(wrapped, path, content, mode=mode, quote=True)
    return result, calls


@pytest.mark.asyncio
async def test_multichunk_partial_failure_removes_file() -> None:
    async def exec_one(cmd: str, calls: list[str]) -> ExecResult:
        # Fail on the first append, after the first command already truncated+wrote.
        fail = ">>" in cmd and not any(">>" in c for c in calls[:-1])
        return (
            ExecResult(stdout="boom", exit_code=1, output="boom")
            if fail
            else ExecResult(stdout="", exit_code=0, output="")
        )

    result, calls = await _run(exec_one, "C" * (SANDBOX_EXEC_CHUNK_BYTES * 2))
    assert result.exit_code == 1
    assert any(c.startswith("rm -f /tmp/f") for c in calls)


@pytest.mark.asyncio
async def test_first_command_failure_leaves_existing_file() -> None:
    # mkdir/truncate fails before any chunk is written — must not delete a pre-existing file.
    async def exec_one(cmd: str, calls: list[str]) -> ExecResult:
        return ExecResult(stdout="denied", exit_code=1, output="denied")

    result, calls = await _run(exec_one, "C" * (SANDBOX_EXEC_CHUNK_BYTES * 2))
    assert result.exit_code == 1
    assert not any(c.startswith("rm -f") for c in calls)


@pytest.mark.asyncio
async def test_chmod_failure_keeps_written_file() -> None:
    # All data appended successfully; only the trailing chmod fails — keep the file.
    async def exec_one(cmd: str, calls: list[str]) -> ExecResult:
        if cmd.startswith("chmod"):
            return ExecResult(stdout="chmod denied", exit_code=1, output="chmod denied")
        return ExecResult(stdout="", exit_code=0, output="")

    result, calls = await _run(exec_one, "C" * (SANDBOX_EXEC_CHUNK_BYTES * 2), mode=0o644)
    assert result.exit_code == 1
    assert any(c.startswith("chmod") for c in calls)
    assert not any(c.startswith("rm -f") for c in calls)


@pytest.mark.asyncio
async def test_single_chunk_failure_does_not_remove_file() -> None:
    async def exec_one(cmd: str, calls: list[str]) -> ExecResult:
        return ExecResult(stdout="denied", exit_code=1, output="denied")

    result, calls = await _run(exec_one, "small")
    assert result.exit_code == 1
    assert not any(c.startswith("rm -f") for c in calls)
