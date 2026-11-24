"""Tunnels from `cgate request --tunnel`: opened for the running exec, closed when it ends."""

from __future__ import annotations

import asyncio
import os
import shutil
import socket
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from carapace.sandbox import tunnels
from carapace.sandbox.exec_flow import EXEC_ENDED_REJECTION, SandboxExecCoordinator, SandboxExecState
from carapace.sandbox.exec_scope import RunningExec
from carapace.sandbox.runtime import ExecResult
from carapace.sandbox.session_lifecycle import SessionContainer
from carapace.sandbox.skill_profile import SkillProfileSync
from carapace.sandbox.tunnels import Tunnel, listen_addresses, parse_tunnel
from tests.runtime_mocks import NO_LEFTOVER_PROCESSES, make_runtime_mock

FORWARDER = Path(__file__).parents[1] / "sandbox" / "carapace-tunnel"
BASH = shutil.which("bash")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("imap.example.com:993", Tunnel("imap.example.com", 993)),
        (" IMAP.Example.com:993 ", Tunnel("imap.example.com", 993)),
        ("db:5432", Tunnel("db", 5432)),
        ("imap.example.com", None),
        ("*.example.com:993", None),
        ("imap.example.com:0", None),
        ("imap.example.com:65536", None),
        ("imap.example.com:993; rm -rf /", None),
        ("[::1]:993", None),
    ],
)
def test_a_tunnel_is_an_exact_host_and_a_port(raw: str, expected: Tunnel | None) -> None:
    assert parse_tunnel(raw) == expected


def test_each_host_gets_its_own_loopback_address_so_ports_can_repeat() -> None:
    opened = {Tunnel("imap.a.example", 993): "127.0.0.2"}

    new = listen_addresses(opened, [Tunnel("imap.b.example", 993), Tunnel("imap.a.example", 465)])

    assert new == {Tunnel("imap.b.example", 993): "127.0.0.3", Tunnel("imap.a.example", 465): "127.0.0.2"}


class _FakeProxy:
    """Answers CONNECT like the session proxy: 200 and then an upper-casing echo, or a denial."""

    def __init__(self, *, deny: str = "") -> None:
        self.deny = deny
        self.connects: list[str] = []

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        head = await reader.readuntil(b"\r\n\r\n")
        self.connects.append(head.split(b"\r\n", 1)[0].decode())
        if self.deny:
            writer.write(f"HTTP/1.1 403 Forbidden\r\nContent-Length: {len(self.deny)}\r\n\r\n{self.deny}".encode())
            await writer.drain()
            writer.close()
            return
        writer.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
        while data := await reader.read(1024):
            writer.write(data.upper())
            await writer.drain()
        writer.close()


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _local(script: str, tmp_path: Path) -> str:
    """The script with its sandbox paths moved under *tmp_path*, and this interpreter for the forwarder."""
    return (
        script.replace(tunnels.TUNNEL_DIR, str(tmp_path / "tunnels"))
        .replace("/etc/hosts", str(tmp_path / "hosts"))
        .replace("/bin/carapace-tunnel", f"{sys.executable} {FORWARDER}")
    )


async def _bash(script: str, proxy_port: int) -> tuple[int, str]:
    env = {**os.environ, "HTTP_PROXY": f"http://sess-1:token@127.0.0.1:{proxy_port}"}
    process = await asyncio.create_subprocess_exec(
        str(BASH), "-c", script, env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
    )
    output, _ = await process.communicate()
    return process.returncode or 0, output.decode()


async def _round_trip(port: int, payload: bytes) -> bytes:
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(payload)
    await writer.drain()
    writer.write_eof()
    answer = await asyncio.wait_for(reader.read(), timeout=5)
    writer.close()
    return answer


@pytest.mark.skipif(BASH is None, reason="bash not on PATH")
@pytest.mark.anyio
async def test_the_scripts_shadow_the_host_forward_through_the_proxy_and_clean_up(tmp_path: Path) -> None:
    proxy = _FakeProxy()
    server = await asyncio.start_server(proxy.handle, "127.0.0.1", 0)
    proxy_port = server.sockets[0].getsockname()[1]
    (tmp_path / "hosts").write_text("127.0.0.1 localhost\n")
    tunnel = Tunnel("imap.example.com", _free_port())

    async with server:
        code, output = await _bash(_local(tunnels.open_script({tunnel: "127.0.0.1"}, {}), tmp_path), proxy_port)
        assert code == 0, output
        assert (tmp_path / "hosts").read_text() == "127.0.0.1 localhost\n127.0.0.1 imap.example.com\n"

        assert await _round_trip(tunnel.port, b"a001 capability\r\n") == b"A001 CAPABILITY\r\n"
        assert proxy.connects == [f"CONNECT imap.example.com:{tunnel.port} HTTP/1.1"]

        code, output = await _bash(_local(tunnels.close_script(), tmp_path), proxy_port)
        assert code == 0, output

    assert (tmp_path / "hosts").read_text() == "127.0.0.1 localhost\n"
    assert not (tmp_path / "tunnels").exists()
    with pytest.raises(OSError):
        await asyncio.open_connection("127.0.0.1", tunnel.port)


@pytest.mark.skipif(BASH is None, reason="bash not on PATH")
@pytest.mark.anyio
async def test_a_denied_connect_closes_the_client_and_logs_the_reason(tmp_path: Path) -> None:
    proxy = _FakeProxy(deny="Sentinel denied this operation. Not for this task.")
    server = await asyncio.start_server(proxy.handle, "127.0.0.1", 0)
    proxy_port = server.sockets[0].getsockname()[1]
    (tmp_path / "hosts").write_text("")
    tunnel = Tunnel("imap.example.com", _free_port())

    async with server:
        code, output = await _bash(_local(tunnels.open_script({tunnel: "127.0.0.1"}, {}), tmp_path), proxy_port)
        assert code == 0, output
        try:
            assert await _round_trip(tunnel.port, b"hello") == b""
            log = (tmp_path / "tunnels" / "0.log").read_text()
        finally:
            await _bash(_local(tunnels.close_script(), tmp_path), proxy_port)

    assert f"the proxy refused imap.example.com:{tunnel.port}: HTTP/1.1 403 Forbidden" in log
    assert "Sentinel denied this operation. Not for this task." in log


def _coordinator() -> tuple[SandboxExecCoordinator, SandboxExecState, list[str]]:
    scripts: list[str] = []

    async def exec_(_container_id: str, command: Any, *_args: object, **_kwargs: object) -> ExecResult:
        if isinstance(command, list) and command[:2] == ["/bin/bash", "-c"] and tunnels.TUNNEL_DIR in command[2]:
            scripts.append(command[2])
            return ExecResult(stdout="", exit_code=0, output="")
        return NO_LEFTOVER_PROCESSES

    runtime = make_runtime_mock()
    runtime.exec.side_effect = exec_
    sc = SessionContainer(container_id="container-1", session_id="s1", created_at=0, last_used=0)
    state = SandboxExecState(
        sessions={"s1": sc},
        allowed_domains={},
        exec_temp_domains={},
        session_current_command={},
        domain_approval_cbs={},
        domain_notify_cbs={},
        exec_locks={},
        exec_notified_domains={},
        exec_notified_credentials={},
        running_execs={},
    )
    return SandboxExecCoordinator(runtime=runtime, state=state, profile_sync=SkillProfileSync(runtime)), state, scripts


async def _exec_that(coordinator: SandboxExecCoordinator, during: Any) -> None:
    sc = coordinator._state.sessions["s1"]

    async def exec_in_container(*_args: object, **_kwargs: object) -> ExecResult:
        await during()
        return ExecResult(stdout="", exit_code=0, output="")

    await coordinator.exec(
        "s1",
        "fetch-mail",
        ensure_session=AsyncMock(return_value=sc),
        recreate_session=AsyncMock(),
        log_container_tail=AsyncMock(),
        exec_in_container=exec_in_container,
    )


@pytest.mark.anyio
async def test_tunnels_opened_during_an_exec_close_when_it_ends() -> None:
    coordinator, state, scripts = _coordinator()
    opened: list[RunningExec] = []

    async def open_two() -> None:
        running = state.running_execs["s1"]
        opened.append(running)
        assert await coordinator.open_tunnels(running, [Tunnel("imap.a.example", 993)]) is None
        assert (
            await coordinator.open_tunnels(running, [Tunnel("imap.a.example", 993), Tunnel("smtp.a.example", 465)])
            is None
        )

    await _exec_that(coordinator, open_two)

    [running] = opened
    assert running.tunnels == {Tunnel("imap.a.example", 993): "127.0.0.2", Tunnel("smtp.a.example", 465): "127.0.0.3"}
    first, second, close = scripts
    assert "127.0.0.2 imap.a.example" in first and "imap.a.example:993" in first
    # An open tunnel is not started twice.
    assert "imap.a.example:993" not in second and "127.0.0.3 smtp.a.example" in second
    assert close == tunnels.close_script()


@pytest.mark.anyio
async def test_an_exec_without_tunnels_closes_nothing() -> None:
    coordinator, _state, scripts = _coordinator()

    await _exec_that(coordinator, AsyncMock())

    assert scripts == []


@pytest.mark.anyio
async def test_a_tunnel_for_an_exec_that_ended_is_not_opened() -> None:
    coordinator, state, scripts = _coordinator()
    ended: list[RunningExec] = []

    async def remember() -> None:
        ended.append(state.running_execs["s1"])

    await _exec_that(coordinator, remember)

    assert await coordinator.open_tunnels(ended[0], [Tunnel("imap.a.example", 993)]) == EXEC_ENDED_REJECTION
    assert scripts == []


@pytest.mark.anyio
async def test_a_tunnel_that_does_not_come_up_is_reported_and_still_cleaned_up() -> None:
    coordinator, state, scripts = _coordinator()
    failures: list[str | None] = []
    runtime_exec = coordinator._runtime.exec.side_effect

    async def failing_open(container_id: str, command: Any, *args: object, **kwargs: object) -> ExecResult:
        result = await runtime_exec(container_id, command, *args, **kwargs)
        if isinstance(command, list) and "nohup" in command[2]:
            return ExecResult(stdout="", exit_code=1, output="imap.a.example:993 did not start:\nAddress in use\n")
        return result

    coordinator._runtime.exec.side_effect = failing_open

    async def open_one() -> None:
        failures.append(await coordinator.open_tunnels(state.running_execs["s1"], [Tunnel("imap.a.example", 993)]))

    await _exec_that(coordinator, open_one)

    assert failures == ["The tunnels could not be opened: imap.a.example:993 did not start:\nAddress in use"]
    assert scripts[-1] == tunnels.close_script()
