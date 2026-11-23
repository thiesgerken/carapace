"""Start-up egress self-test: a sandbox that reaches the network past its proxy stops the server."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from carapace.sandbox.egress_check import PROBE_SCRIPT, EgressCheckError
from carapace.sandbox.manager import SandboxManager
from carapace.sandbox.runtime import ExecResult
from tests.runtime_mocks import make_runtime_mock


def _probe(tmp_path: Path, *, network_open: bool, tools: tuple[str, ...] = ("timeout", "getent")) -> ExecResult:
    """Run the probe script against stub tools: `timeout` decides whether a connection gets out."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for tool in tools:
        stub = bin_dir / tool
        stub.write_text(f"#!/bin/sh\nexit {0 if network_open else 1}\n")
        stub.chmod(0o755)
    bash = shutil.which("bash")
    assert bash is not None
    done = subprocess.run(
        [bash, "-c", PROBE_SCRIPT],
        capture_output=True,
        text=True,
        env={**os.environ, "PATH": f"{bin_dir}:{Path(bash).parent}"},
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
        "DNS lookup of example.com succeeded",
    ]


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


def _ready(runtime: MagicMock) -> None:
    runtime.logs = AsyncMock(return_value="carapace sandbox ready\n")


@pytest.mark.anyio
async def test_the_check_runs_in_a_throwaway_sandbox_without_proxy(tmp_path: Path, db_factory: Any) -> None:
    runtime = make_runtime_mock()
    _ready(runtime)
    runtime.sandbox_exists = AsyncMock(return_value="stale-probe")
    runtime.exec = AsyncMock(return_value=ExecResult(exit_code=0, output="", stdout=""))

    await _manager(tmp_path, db_factory, runtime).verify_no_direct_egress()

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
        await _manager(tmp_path, db_factory, runtime).verify_no_direct_egress()

    assert exc_info.value.leaks == ["direct TCP connection to 1.1.1.1:443 succeeded"]
    runtime.destroy_sandbox.assert_awaited_with("egress-check", "carapace-sandbox-egress-check", "container-1")
