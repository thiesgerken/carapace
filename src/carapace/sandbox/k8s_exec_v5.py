"""Pod exec with stdin over the ``v5.channel.k8s.io`` websocket subprotocol.

kr8s only speaks v4, which has no way to close stdin, so a command like ``cat > file``
would never see EOF. v5 adds the close channel. Every binary frame starts with its
channel byte.
"""

from __future__ import annotations

import json
from typing import Protocol

EXEC_V5_PROTOCOL = "v5.channel.k8s.io"

_STDIN = 0
_STDOUT = 1
_STDERR = 2
_STATUS = 3
_CLOSE = 255

# One websocket message per slice, so no single frame grows with the payload.
STDIN_FRAME_BYTES = 256 * 1024


class ExecProtocolError(RuntimeError):
    """The API server broke the v5 exec protocol (or didn't agree to it)."""


class ExecWebSocket(Protocol):
    @property
    def subprotocol(self) -> str | None: ...

    async def send_bytes(self, data: bytes) -> None: ...

    async def receive_bytes(self) -> bytes: ...


async def exec_v5(ws: ExecWebSocket, stdin: bytes) -> tuple[bytes, bytes, int]:
    """Send *stdin*, close it, and collect ``(stdout, stderr, exit_code)`` until the status frame.

    ponytail: stdin is sent in full before reading, so a command that writes more output than
    the pipe buffers before draining its stdin would stall. The uploads that use this write
    nothing; read concurrently if that ever changes.
    """
    if ws.subprotocol != EXEC_V5_PROTOCOL:
        raise ExecProtocolError(f"API server negotiated exec subprotocol {ws.subprotocol!r}, need {EXEC_V5_PROTOCOL}")
    for start in range(0, len(stdin), STDIN_FRAME_BYTES):
        await ws.send_bytes(bytes([_STDIN]) + stdin[start : start + STDIN_FRAME_BYTES])
    await ws.send_bytes(bytes([_CLOSE, _STDIN]))

    stdout = bytearray()
    stderr = bytearray()
    while True:
        frame = await ws.receive_bytes()
        if not frame:
            raise ExecProtocolError("empty exec frame without a channel byte")
        channel, data = frame[0], frame[1:]
        # The server opens every channel with an empty frame.
        if not data:
            continue
        if channel == _STDOUT:
            stdout += data
        elif channel == _STDERR:
            stderr += data
        elif channel == _STATUS:
            return bytes(stdout), bytes(stderr), _exit_code(json.loads(data))
        else:
            raise ExecProtocolError(f"unexpected exec frame on channel {channel}")


def _exit_code(status: dict) -> int:
    """Read the exit code from the ``metav1.Status`` that ends the exec."""
    if status.get("status") == "Success":
        return 0
    for cause in status.get("details", {}).get("causes", []):
        if cause.get("reason") == "ExitCode":
            return int(cause["message"])
    raise ExecProtocolError(f"exec failed without an exit code: {status.get('message', status)}")
