"""Start-up egress self-test: a sandbox that reaches the network past its proxy stops the server."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from carapace.sandbox.egress_check import (
    PROBE_SCRIPT,
    EgressCheckError,
    EgressProbeError,
    probe_env,
    raise_for_leaks,
)
from carapace.sandbox.manager import SandboxManager
from carapace.sandbox.runtime import ExecResult
from tests.runtime_mocks import make_runtime_mock

_PROXY = "10.0.0.2/3128"


_PROXY_ANSWERS = "HTTP/1.1 407 Proxy Authentication Required"


def _run_probe(bin_dir: Path, proxy_host: str, proxy_port: int) -> ExecResult:
    bash = shutil.which("bash")
    assert bash is not None
    done = subprocess.run(
        [bash, "-c", PROBE_SCRIPT],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{Path(bash).parent}",
            **probe_env(proxy_host, proxy_port, "search svc.cluster.local\nnameserver 10.96.0.10\n"),
        },
        check=False,
    )
    return ExecResult(exit_code=done.returncode, output=done.stdout + done.stderr, stdout=done.stdout)


def _write_tools(bin_dir: Path, scripts: dict[str, str]) -> None:
    bin_dir.mkdir()
    for tool, script in scripts.items():
        stub = bin_dir / tool
        stub.write_text(f"#!/bin/sh\n{script}\n")
        stub.chmod(0o755)


def _probe(
    tmp_path: Path,
    *,
    network_open: bool,
    proxy_answer: str = _PROXY_ANSWERS,
    tools: tuple[str, ...] = ("timeout", "getent", "head"),
) -> ExecResult:
    """Run the probe script against stub tools: `timeout` decides whether a connection gets out, and
    prints what the proxy answers."""
    open_code = 0 if network_open else 1
    stubs = {
        "timeout": f'case "$*" in *{_PROXY}*) printf "%s\\n" "{proxy_answer}"; exit 0;; esac\nexit {open_code}',
        "getent": f"exit {open_code}",
        "head": "exit 0",
    }
    _write_tools(tmp_path / "bin", {tool: stubs[tool] for tool in tools})
    return _run_probe(tmp_path / "bin", "10.0.0.2", 3128)


@pytest.fixture
def listener() -> Iterator[tuple[socket.socket, list[bytes]]]:
    """A local TCP listener that sends each connection the queued reply, then closes it."""
    server = socket.create_server(("127.0.0.1", 0))
    replies: list[bytes] = []

    def serve() -> None:
        while True:
            try:
                conn, _ = server.accept()
            except OSError:
                return
            with conn:
                # The whole request before answering: bash's stdout is line-buffered, so the probe's printf
                # arrives in one write per line, and closing with a line unread resets the connection, which
                # can discard the reply before the probe reads it.
                request = b""
                while b"\r\n\r\n" not in request and (chunk := conn.recv(4096)):
                    request += chunk
                conn.sendall(replies[0] if replies else b"")

    threading.Thread(target=serve, daemon=True).start()
    yield server, replies
    server.close()


def test_a_sealed_sandbox_reports_nothing(tmp_path: Path) -> None:
    result = _probe(tmp_path, network_open=False)

    assert (result.exit_code, result.stdout) == (0, "")


def test_an_open_sandbox_reports_every_leak(tmp_path: Path) -> None:
    result = _probe(tmp_path, network_open=True)

    assert result.stdout.splitlines() == [
        "direct TCP connection to 1.1.1.1:443 succeeded",
        "direct TCP connection to 8.8.8.8:53 succeeded",
        "direct TCP connection to 9.9.9.9:443 succeeded",
        "direct TCP connection to 10.96.0.10:53 succeeded",
        "DNS lookup of example.com succeeded",
    ]


def test_a_probe_that_cannot_reach_the_proxy_does_not_pass(tmp_path: Path) -> None:
    result = _probe(tmp_path, network_open=False, proxy_answer="")

    assert result.exit_code == 1
    assert "positive control failed: the session proxy at 10.0.0.2:3128 did not answer" in result.output
    with pytest.raises(EgressProbeError, match="could not run"):
        raise_for_leaks(result)


@pytest.mark.parametrize(
    ("reply", "answered"),
    [
        (b"HTTP/1.1 407 Proxy Authentication Required\r\nProxy-Authenticate: Basic\r\n\r\n", True),
        # A relay that accepts the connection but cannot reach the server.
        (b"", False),
        (b"HTTP/1.1 200 OK\r\n\r\n", False),
    ],
)
def test_only_the_proxys_own_answer_passes_the_positive_control(
    tmp_path: Path, listener: tuple[socket.socket, list[bytes]], reply: bytes, answered: bool
) -> None:
    server, replies = listener
    replies.append(reply)
    real_head = shutil.which("head")
    assert real_head is not None
    # The real control: bash's /dev/tcp and head against a socket. `timeout` only drops its duration, and
    # every other connect fails, so an answered control reports nothing.
    _write_tools(
        tmp_path / "bin",
        {
            "timeout": f'shift\ncase "$*" in *{server.getsockname()[1]}*) exec "$@";; esac\nexit 1',
            "getent": "exit 1",
            "head": f'exec {real_head} "$@"',
        },
    )

    result = _run_probe(tmp_path / "bin", "127.0.0.1", server.getsockname()[1])

    assert (result.exit_code == 0) is answered, result.output
    assert ("positive control failed" in result.output) is not answered


def test_the_cluster_resolver_is_probed_and_loopback_resolvers_are_not() -> None:
    env = probe_env("10.0.0.2", 3128, "nameserver 127.0.0.11\nnameserver 10.96.0.10\nnameserver ::1\noptions ndots:5\n")

    assert env == {"PROXY_TARGET": "10.0.0.2/3128", "DNS_TARGETS": "10.96.0.10/53"}


def test_a_missing_tool_fails_the_probe_instead_of_passing_it(tmp_path: Path) -> None:
    result = _probe(tmp_path, network_open=False, tools=("timeout",))

    assert result.exit_code == 1
    assert "missing getent" in result.output


def _manager(tmp_path: Path, db_factory: Any, runtime: MagicMock) -> SandboxManager:
    return SandboxManager(
        runtime=runtime,
        server_host="172.18.0.1",
        network_name="carapace-sandbox-default",
        data_dir=tmp_path,
        knowledge_repo_for_session=MagicMock(),
        session_factory=db_factory,
    )


def _resolv_conf(tmp_path: Path) -> Path:
    path = tmp_path / "resolv.conf"
    path.write_text("nameserver 10.96.0.10\n")
    return path


def _ready(runtime: MagicMock) -> None:
    runtime.logs = AsyncMock(return_value="carapace sandbox ready\n")


@pytest.mark.anyio
async def test_the_check_runs_in_a_throwaway_sandbox_without_proxy(tmp_path: Path, db_factory: Any) -> None:
    runtime = make_runtime_mock()
    _ready(runtime)
    runtime.list_egress_probes = AsyncMock(return_value={"egress-check-stale": "stale-probe"})
    runtime.exec = AsyncMock(return_value=ExecResult(exit_code=0, output="", stdout=""))

    await _manager(tmp_path, db_factory, runtime).verify_no_direct_egress(_resolv_conf(tmp_path))

    assert runtime.exec.await_args.kwargs["env"] == {"PROXY_TARGET": "172.18.0.1/3128", "DNS_TARGETS": "10.96.0.10/53"}
    config = runtime.create_sandbox.await_args.args[0]
    probe_id = config.sandbox_id
    assert probe_id.startswith("egress-check-")
    assert (config.name, config.environment) == (f"carapace-sandbox-{probe_id}", {})
    assert config.labels["carapace.egress-check"] == "true"
    assert "carapace.session" not in config.labels
    assert "setup-proxy.sh" not in config.command[-1]
    assert [call.args for call in runtime.destroy_sandbox.await_args_list] == [
        ("egress-check-stale", "carapace-sandbox-egress-check-stale", "stale-probe"),
        (probe_id, f"carapace-sandbox-{probe_id}", "container-1"),
    ]


@pytest.mark.anyio
async def test_a_restart_does_not_wait_for_the_previous_probe_to_be_deleted(tmp_path: Path, db_factory: Any) -> None:
    """Kubernetes deletes a StatefulSet asynchronously: its name is taken until the deletion finished."""
    runtime = make_runtime_mock()
    _ready(runtime)
    runtime.exec = AsyncMock(return_value=ExecResult(exit_code=0, output="", stdout=""))
    being_deleted: set[str] = set()

    async def create(config: Any) -> str:
        if config.name in being_deleted:
            raise RuntimeError(f"object is being deleted: {config.name} already exists")
        return "container-1"

    async def destroy(_sandbox_id: str, name: str, _container_id: str | None) -> None:
        being_deleted.add(name)

    runtime.create_sandbox = AsyncMock(side_effect=create)
    runtime.destroy_sandbox = AsyncMock(side_effect=destroy)
    manager = _manager(tmp_path, db_factory, runtime)

    await manager.verify_no_direct_egress(_resolv_conf(tmp_path))
    await manager.verify_no_direct_egress(_resolv_conf(tmp_path))

    first, second = (call.args[0].name for call in runtime.create_sandbox.await_args_list)
    assert first != second


@pytest.mark.anyio
async def test_a_leak_raises_and_the_probe_is_removed(tmp_path: Path, db_factory: Any) -> None:
    runtime = make_runtime_mock()
    _ready(runtime)
    leak = "direct TCP connection to 1.1.1.1:443 succeeded\n"
    runtime.exec = AsyncMock(return_value=ExecResult(exit_code=0, output=leak, stdout=leak))

    with pytest.raises(EgressCheckError) as exc_info:
        await _manager(tmp_path, db_factory, runtime).verify_no_direct_egress(_resolv_conf(tmp_path))

    assert exc_info.value.leaks == ["direct TCP connection to 1.1.1.1:443 succeeded"]
    probe_id = runtime.create_sandbox.await_args.args[0].sandbox_id
    runtime.destroy_sandbox.assert_awaited_with(probe_id, f"carapace-sandbox-{probe_id}", "container-1")
