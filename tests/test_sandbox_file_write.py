"""Tests for sandbox file writes and str_replace, which pass their data on exec stdin."""

from __future__ import annotations

import json
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import cast

import pytest

from carapace.sandbox.file_ops import SandboxFileOps, _file_write_command
from carapace.sandbox.runtime import ExecResult

# The Nix build sandbox has no /bin/bash; take bash from PATH.
BASH = shutil.which("bash")
needs_bash = pytest.mark.skipif(BASH is None, reason="bash not on PATH")


def _run_write(path: Path, data: bytes, *, mode: int | None = None) -> subprocess.CompletedProcess[bytes]:
    cmd = _file_write_command(str(path), mode=mode, quote=True)
    return subprocess.run([cast(str, BASH), "-c", cmd], input=data, capture_output=True, check=False)


@needs_bash
def test_write_creates_parent_dir_and_writes_stdin(tmp_path: Path) -> None:
    target = tmp_path / "a" / "b" / "out.bin"
    data = bytes(range(256)) * 4096
    assert _run_write(target, data).returncode == 0
    assert target.read_bytes() == data


@needs_bash
def test_write_replaces_read_only_file_and_applies_mode(tmp_path: Path) -> None:
    target = tmp_path / "cred"
    target.write_text("old")
    target.chmod(0o400)
    assert _run_write(target, b"new", mode=0o400).returncode == 0
    assert target.read_text() == "new"
    assert target.stat().st_mode & 0o777 == 0o400


@needs_bash
def test_empty_write_truncates(tmp_path: Path) -> None:
    target = tmp_path / "f"
    target.write_text("old")
    assert _run_write(target, b"").returncode == 0
    assert target.read_bytes() == b""


@pytest.mark.asyncio
async def test_run_file_write_passes_content_on_stdin() -> None:
    calls: list[tuple[str, bytes]] = []

    async def exec_one(cmd: str, data: bytes) -> ExecResult:
        calls.append((cmd, data))
        return ExecResult(stdout="", exit_code=0, output="")

    result = await SandboxFileOps._run_file_write(exec_one, "/tmp/f", "a\nb", mode=None, quote=True)
    assert result.output == "Wrote 2 line(s) to /tmp/f."
    assert calls == [(_file_write_command("/tmp/f", mode=None, quote=True), b"a\nb")]


@pytest.mark.asyncio
async def test_run_file_write_reports_failure() -> None:
    async def exec_one(_cmd: str, _data: bytes) -> ExecResult:
        return ExecResult(stdout="", exit_code=1, output="")

    result = await SandboxFileOps._run_file_write(exec_one, "/tmp/f", "x", mode=None, quote=True)
    assert result.exit_code == 1
    assert result.output == "Error: cannot write /tmp/f (exit 1)."


@needs_bash
@pytest.mark.asyncio
async def test_str_replace_sends_payload_on_stdin(tmp_path: Path) -> None:
    target = tmp_path / "big.txt"
    old = "￿" * 100_000
    target.write_text(f"head {old} tail")

    async def exec_in_session(_session_id: str, cmd: str, **kwargs: object) -> ExecResult:
        stdin = kwargs["stdin"]
        assert isinstance(stdin, bytes)
        assert json.loads(stdin)["old"] == old
        # Swap the sandbox's python3 for this interpreter and run the script for real.
        local_cmd = cmd.replace("python3 -c", f"{shlex.quote(sys.executable)} -c", 1)
        done = subprocess.run([cast(str, BASH), "-c", local_cmd], input=stdin, capture_output=True, check=False)
        return ExecResult(stdout=done.stdout.decode(), exit_code=done.returncode, output=done.stdout.decode())

    ops = SandboxFileOps(exec_in_session=exec_in_session, exec_in_container=exec_in_session, get_session=lambda _: None)
    result = await ops.file_str_replace("s", str(target), old, "new")

    assert result.exit_code == 0, result.output
    assert target.read_text() == "head new tail"
