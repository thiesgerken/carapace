"""Tests for the v5 pod exec framing used for exec stdin on Kubernetes."""

from __future__ import annotations

import json

import pytest

from carapace.sandbox.k8s_exec_v5 import EXEC_V5_PROTOCOL, STDIN_FRAME_BYTES, ExecProtocolError, exec_v5


class FakeWebSocket:
    def __init__(self, frames: list[bytes], subprotocol: str | None = EXEC_V5_PROTOCOL) -> None:
        self.subprotocol = subprotocol
        self.sent: list[bytes] = []
        self._frames = frames

    async def send_bytes(self, data: bytes) -> None:
        self.sent.append(data)

    async def receive_bytes(self) -> bytes:
        return self._frames.pop(0)


def _status(status: dict) -> bytes:
    return b"\x03" + json.dumps(status).encode()


_SUCCESS = _status({"status": "Success"})


@pytest.mark.asyncio
async def test_stdin_is_sliced_into_channel_frames_then_closed() -> None:
    data = bytes(range(256)) * (STDIN_FRAME_BYTES // 256 * 2 + 1)
    ws = FakeWebSocket([_SUCCESS])

    await exec_v5(ws, data)

    *stdin_frames, close = ws.sent
    assert len(stdin_frames) == 3
    assert all(frame[0] == 0 for frame in stdin_frames)
    assert b"".join(frame[1:] for frame in stdin_frames) == data
    assert close == bytes([255, 0])


@pytest.mark.asyncio
async def test_empty_stdin_only_closes() -> None:
    ws = FakeWebSocket([_SUCCESS])
    await exec_v5(ws, b"")
    assert ws.sent == [bytes([255, 0])]


@pytest.mark.asyncio
async def test_demuxes_output_and_skips_channel_opening_frames() -> None:
    ws = FakeWebSocket([b"\x01", b"\x02", b"\x03", b"\x01out", b"\x02err", b"\x01put", _SUCCESS])
    assert await exec_v5(ws, b"x") == (b"output", b"err", 0)


@pytest.mark.asyncio
async def test_exit_code_comes_from_the_status_frame() -> None:
    status = {
        "status": "Failure",
        "message": "command terminated with non-zero exit code",
        "details": {"causes": [{"reason": "ExitCode", "message": "7"}]},
    }
    ws = FakeWebSocket([_status(status)])
    assert await exec_v5(ws, b"") == (b"", b"", 7)


@pytest.mark.asyncio
async def test_failure_without_exit_code_raises() -> None:
    ws = FakeWebSocket([_status({"status": "Failure", "message": "container not found"})])
    with pytest.raises(ExecProtocolError, match="container not found"):
        await exec_v5(ws, b"")


@pytest.mark.asyncio
async def test_refuses_anything_but_v5() -> None:
    ws = FakeWebSocket([], subprotocol="v4.channel.k8s.io")
    with pytest.raises(ExecProtocolError, match=r"v4\.channel\.k8s\.io"):
        await exec_v5(ws, b"data")
    assert ws.sent == []


@pytest.mark.asyncio
async def test_unknown_channel_raises() -> None:
    ws = FakeWebSocket([b"\x04resize"])
    with pytest.raises(ExecProtocolError, match="channel 4"):
        await exec_v5(ws, b"")
