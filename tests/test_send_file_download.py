"""Tests for the send_file download path: sandbox read-out + server-side persistence."""

from __future__ import annotations

import base64
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from carapace.sandbox.manager import SandboxManager, UploadError, UploadTooLargeError
from carapace.sandbox.runtime import ExecResult
from carapace.session import sent_files


def _fake_manager(size: int, payload: bytes) -> SimpleNamespace:
    async def exec_command(_sid, command, **_kw):
        if "stat -c %s" in command:
            return ExecResult(stdout=f"{size}\n", exit_code=0, output=f"{size}\n")
        if "tail -c" in command:
            return ExecResult(
                stdout=base64.b64encode(payload).decode(), exit_code=0, output=base64.b64encode(payload).decode()
            )
        return ExecResult(stdout="", exit_code=0, output="")

    fake = SimpleNamespace()
    fake.exec_command = AsyncMock(side_effect=exec_command)
    fake._DOWNLOAD_CHUNK_BYTES = 1024
    return fake


@pytest.mark.asyncio
async def test_download_streams_bytes_to_dest(tmp_path: Path) -> None:
    payload = b"hello world"
    fake = _fake_manager(len(payload), payload)
    dest = tmp_path / "out.txt"
    size = await SandboxManager.download_tmp_file(fake, "s1", "/tmp/out.txt", dest, max_bytes=1000)
    assert size == len(payload)
    assert dest.read_bytes() == payload


@pytest.mark.asyncio
async def test_download_missing_file_raises(tmp_path: Path) -> None:
    async def exec_command(_sid, command, **_kw):
        return ExecResult(stdout="MISSING", exit_code=0, output="MISSING")

    fake = SimpleNamespace(exec_command=AsyncMock(side_effect=exec_command), _DOWNLOAD_CHUNK_BYTES=1024)
    with pytest.raises(UploadError):
        await SandboxManager.download_tmp_file(fake, "s1", "/tmp/nope", tmp_path / "x", max_bytes=1000)


@pytest.mark.asyncio
async def test_download_too_large_raises(tmp_path: Path) -> None:
    fake = _fake_manager(10_000, b"x")
    with pytest.raises(UploadTooLargeError):
        await SandboxManager.download_tmp_file(fake, "s1", "/tmp/big", tmp_path / "x", max_bytes=100)


def test_sent_files_roundtrip(tmp_path: Path) -> None:
    file_id, dest = sent_files.reserve(tmp_path, "sess", "chart.png")
    dest.write_bytes(b"PNGDATA")
    info = sent_files.finalize(tmp_path, "sess", file_id, "chart.png", 7)
    assert info.mime == "image/png"
    assert info.size == 7

    resolved = sent_files.resolve(tmp_path, "sess", file_id)
    assert resolved is not None
    blob, loaded = resolved
    assert blob.read_bytes() == b"PNGDATA"
    assert loaded.name == "chart.png"


def test_sent_files_rejects_path_traversal(tmp_path: Path) -> None:
    assert sent_files.resolve(tmp_path, "sess", "../../etc/passwd") is None
    assert sent_files.resolve(tmp_path, "sess", "deadbeef") is None  # too short / unknown
    assert sent_files.resolve(tmp_path, "sess", "0123456789abcdef") is None  # well-formed but absent
