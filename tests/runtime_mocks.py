from __future__ import annotations

import asyncio
import socket
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from carapace.sandbox.exec_flow import KILL_LEFTOVER_PROCESSES_COMMAND
from carapace.sandbox.runtime import ContainerRuntime, ExecResult, SandboxInspection

NO_LEFTOVER_PROCESSES = ExecResult(stdout="0\n", exit_code=0, output="0\n")


async def _exec_ok(_container_id: str, command: str | list[str], *_args: object, **_kwargs: object) -> ExecResult:
    if command == KILL_LEFTOVER_PROCESSES_COMMAND:
        return NO_LEFTOVER_PROCESSES
    return ExecResult(stdout="ok", exit_code=0, output="ok")


def make_runtime_mock() -> MagicMock:
    runtime = MagicMock(spec=ContainerRuntime)
    runtime.runtime_kind = "docker"
    runtime.create_sandbox = AsyncMock(return_value="container-1")
    runtime.resume_sandbox = AsyncMock()
    runtime.suspend_sandbox = AsyncMock()
    runtime.destroy_sandbox = AsyncMock()
    runtime.sandbox_exists = AsyncMock(return_value=None)
    runtime.list_sandboxes = AsyncMock(return_value={})
    runtime.retained_sandbox_session_ids = AsyncMock(return_value=set())
    runtime.list_pool_sandboxes = AsyncMock(return_value={})
    runtime.list_egress_probes = AsyncMock(return_value={})
    runtime.claim_warm_sandbox = AsyncMock(return_value=False)
    runtime.inspect_sandbox = AsyncMock(
        side_effect=lambda _session_id, _name, container_id=None: SandboxInspection(
            exists=container_id is not None,
            status="running" if container_id is not None else "missing",
            resource_id=container_id,
        )
    )
    runtime.measure_workspace_usage = AsyncMock(return_value=None)
    runtime.exec = AsyncMock(side_effect=_exec_ok)
    runtime.is_running = AsyncMock(return_value=True)
    runtime.get_ip = AsyncMock(return_value="172.18.0.22")
    runtime.resolve_self_network_name = AsyncMock(return_value="bridge")
    runtime.get_host_ip = AsyncMock(return_value="172.18.0.1")
    runtime.image_exists = MagicMock(return_value=True)
    runtime.ensure_network = AsyncMock()
    runtime.get_self_network_info = AsyncMock(return_value={"network": "bridge"})
    runtime.logs = AsyncMock(return_value="")
    runtime.write_stdout_log = AsyncMock()
    return runtime


def fake_dns(monkeypatch: pytest.MonkeyPatch, answers: dict[str, list[str]]) -> list[str]:
    """Answer getaddrinfo from *answers*; IP literals resolve to themselves, other names fail.

    Returns the list of looked-up hosts, to assert which names went out to DNS.
    """
    names = {name.lower(): addresses for name, addresses in answers.items()}
    lookups: list[str] = []

    async def getaddrinfo(_loop: Any, host: str, port: int, **_kwargs: Any) -> list[tuple[Any, ...]]:
        lookups.append(host)
        if host.lower() not in names:
            try:
                socket.inet_pton(socket.AF_INET6 if ":" in host else socket.AF_INET, host)
            except OSError as exc:
                raise socket.gaierror(socket.EAI_NONAME, f"unknown host {host}") from exc
        addresses = names.get(host.lower(), [host])
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port)) for address in addresses]

    monkeypatch.setattr(asyncio.BaseEventLoop, "getaddrinfo", getaddrinfo)
    return lookups
