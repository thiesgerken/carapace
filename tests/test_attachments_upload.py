"""Tests for upload preamble building and the sandbox /tmp write."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from carapace.sandbox.manager import SandboxManager, UploadError, UploadTooLargeError
from carapace.sandbox.runtime import ExecResult
from carapace.session.attachments import augment_prompt, build_attachment_preamble


def _att(name: str, path: str) -> SimpleNamespace:
    return SimpleNamespace(name=name, path=path)


def test_build_attachment_preamble_empty() -> None:
    assert build_attachment_preamble([]) == ""


def test_build_attachment_preamble_lists_files() -> None:
    text = build_attachment_preamble([_att("abc.png", "/tmp/abc.png"), _att("d.csv", "/tmp/d-1a2b.csv")])
    assert text == (
        "The user has provided the following files:\n"
        "- abc.png (uploaded to /tmp/abc.png inside your sandbox)\n"
        "- d.csv (uploaded to /tmp/d-1a2b.csv inside your sandbox)"
    )


def test_augment_prompt() -> None:
    assert augment_prompt("hi", []) == "hi"
    assert augment_prompt("", [_att("a", "/tmp/a")]).startswith("The user has provided")
    out = augment_prompt("look at this", [_att("a", "/tmp/a")])
    assert out.endswith("\n\nlook at this")


def _fake_manager(exec_outputs: dict[str, ExecResult] | None = None) -> SimpleNamespace:
    async def exec_command(_sid, command, **_kw):
        if exec_outputs:
            for needle, result in exec_outputs.items():
                if needle in command:
                    return result
        return ExecResult(stdout="", exit_code=0, output="")

    fake = SimpleNamespace()
    fake.exec_command = AsyncMock(side_effect=exec_command)
    fake._exec = AsyncMock(return_value=ExecResult(stdout="", exit_code=0, output=""))
    fake._UPLOAD_READ_BYTES = 4
    return fake


def _reader(data: bytes):
    buf = bytearray(data)

    async def read(n: int) -> bytes:
        chunk = bytes(buf[:n])
        del buf[:n]
        return chunk

    return read


@pytest.mark.asyncio
async def test_upload_is_one_exec_with_the_file_on_stdin() -> None:
    fake = _fake_manager()
    path = await SandboxManager.upload_tmp_file(fake, "s1", "abc.png", _reader(b"hello world"), max_bytes=1000)
    assert path == "/tmp/abc.png"
    fake._exec.assert_awaited_once()
    assert fake._exec.call_args.args[1].startswith("cat > /tmp/abc.png")
    assert fake._exec.call_args.kwargs["stdin"] == b"hello world"


@pytest.mark.asyncio
async def test_upload_collision_inserts_hash() -> None:
    fake = _fake_manager({"test -e": ExecResult(stdout="EXISTS", exit_code=0, output="EXISTS")})
    path = await SandboxManager.upload_tmp_file(fake, "s1", "abc.png", _reader(b"x"), max_bytes=1000)
    assert path.startswith("/tmp/abc-") and path.endswith(".png")
    assert path != "/tmp/abc.png"


@pytest.mark.asyncio
async def test_upload_too_large_raises_before_touching_the_sandbox() -> None:
    fake = _fake_manager()
    with pytest.raises(UploadTooLargeError):
        await SandboxManager.upload_tmp_file(fake, "s1", "big.bin", _reader(b"0123456789"), max_bytes=4)
    fake.exec_command.assert_not_awaited()
    fake._exec.assert_not_awaited()


@pytest.mark.asyncio
async def test_upload_failure_raises() -> None:
    fake = _fake_manager()
    fake._exec.return_value = ExecResult(stdout="", exit_code=1, output="disk full")
    with pytest.raises(UploadError, match="disk full"):
        await SandboxManager.upload_tmp_file(fake, "s1", "a.bin", _reader(b"data"), max_bytes=1000)
