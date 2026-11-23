"""Start-up egress self-test: a sandbox that reaches the network past its proxy stops the server."""

from __future__ import annotations

import os
import shutil
import subprocess
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


def _probe(
    tmp_path: Path,
    *,
    network_open: bool,
    proxy_reachable: bool = True,
    tools: tuple[str, ...] = ("timeout", "getent"),
) -> ExecResult:
    """Run the probe script against stub tools: `timeout` decides whether a connection gets out."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    open_code, proxy_code = (0 if network_open else 1), (0 if proxy_reachable else 1)
    stubs = {
        "timeout": f'case "$*" in *{_PROXY}*) exit {proxy_code};; esac\nexit {open_code}',
        "getent": f"exit {open_code}",
    }
    for tool in tools:
        stub = bin_dir / tool
        stub.write_text(f"#!/bin/sh\n{stubs[tool]}\n")
        stub.chmod(0o755)
    bash = shutil.which("bash")
    assert bash is not None
    done = subprocess.run(
        [bash, "-c", PROBE_SCRIPT],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{Path(bash).parent}",
            **probe_env("10.0.0.2", 3128, "search svc.cluster.local\nnameserver 10.96.0.10\n"),
        },
        check=False,
    )
    return ExecResult(exit_code=done.returncode, output=done.stdout + done.stderr, stdout=done.stdout)


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
    result = _probe(tmp_path, network_open=False, proxy_reachable=False)

    assert result.exit_code == 1
    assert "positive control failed: cannot reach the session proxy at 10.0.0.2:3128" in result.output
    with pytest.raises(EgressProbeError, match="could not run"):
        raise_for_leaks(result)


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
    runtime.sandbox_exists = AsyncMock(return_value="stale-probe")
    runtime.exec = AsyncMock(return_value=ExecResult(exit_code=0, output="", stdout=""))

    await _manager(tmp_path, db_factory, runtime).verify_no_direct_egress(_resolv_conf(tmp_path))

    assert runtime.exec.await_args.kwargs["env"] == {"PROXY_TARGET": "172.18.0.1/3128", "DNS_TARGETS": "10.96.0.10/53"}
    config = runtime.create_sandbox.await_args.args[0]
    assert (config.name, config.environment) == ("carapace-sandbox-egress-check", {})
    assert "carapace.session" not in config.labels
    assert "setup-proxy.sh" not in config.command[-1]
    assert [call.args for call in runtime.destroy_sandbox.await_args_list] == [
        ("egress-check", "carapace-sandbox-egress-check", "stale-probe"),
        ("egress-check", "carapace-sandbox-egress-check", "container-1"),
    ]


@pytest.mark.anyio
async def test_a_leak_raises_and_the_probe_is_removed(tmp_path: Path, db_factory: Any) -> None:
    runtime = make_runtime_mock()
    _ready(runtime)
    leak = "direct TCP connection to 1.1.1.1:443 succeeded\n"
    runtime.exec = AsyncMock(return_value=ExecResult(exit_code=0, output=leak, stdout=leak))

    with pytest.raises(EgressCheckError) as exc_info:
        await _manager(tmp_path, db_factory, runtime).verify_no_direct_egress(_resolv_conf(tmp_path))

    assert exc_info.value.leaks == ["direct TCP connection to 1.1.1.1:443 succeeded"]
    runtime.destroy_sandbox.assert_awaited_with("egress-check", "carapace-sandbox-egress-check", "container-1")
