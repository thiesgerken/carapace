from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from docker.errors import NotFound

from carapace.sandbox.docker import DockerRuntime
from carapace.sandbox.runtime import SandboxConfig


def _make_runtime(data_dir: Path | None) -> DockerRuntime:
    with patch.object(DockerRuntime, "__init__", lambda self, **_kw: None):
        runtime = DockerRuntime.__new__(DockerRuntime)
    runtime._client = MagicMock()
    runtime._data_dir = data_dir
    runtime._host_data_dir = None
    runtime._instance = "default"
    runtime._network_name = "carapace-sandbox-default"
    runtime._network_name_cache = {}
    return runtime


@pytest.mark.asyncio
async def test_inspect_sandbox_missing_without_workspace_returns_missing(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path)
    runtime._client.containers.get.side_effect = NotFound("missing")

    inspection = await runtime.inspect_sandbox("sess-1", "carapace-sandbox-sess-1")

    assert inspection.exists is False
    assert inspection.status == "missing"
    assert inspection.storage_present is False


@pytest.mark.asyncio
async def test_inspect_sandbox_missing_with_workspace_returns_scaled_down(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path)
    runtime._client.containers.get.side_effect = NotFound("missing")
    (tmp_path / "sessions" / "sess-1" / "workspace").mkdir(parents=True)

    inspection = await runtime.inspect_sandbox("sess-1", "carapace-sandbox-sess-1")

    assert inspection.exists is False
    assert inspection.status == "scaled_down"
    assert inspection.storage_present is True


@pytest.mark.asyncio
async def test_list_sandboxes_returns_all_managed_containers(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path)
    session_container = MagicMock()
    session_container.id = "container-1"
    session_container.labels = {"carapace.session": "sess-1", "carapace.managed": "true"}
    stale_container = MagicMock()
    stale_container.id = "container-3"
    stale_container.labels = {"carapace.session": "sess-1", "carapace.managed": "true"}
    pool_container = MagicMock()
    pool_container.id = "container-2"
    pool_container.labels = {
        "carapace.session": "warm-1",
        "carapace.managed": "true",
        "carapace.pool": "true",
    }
    runtime._client.containers.list.return_value = [session_container, pool_container, stale_container]

    sandboxes = await runtime.list_sandboxes()

    assert sandboxes == {"sess-1": ["container-1", "container-3"], "warm-1": ["container-2"]}
    labels = runtime._client.containers.list.call_args.kwargs["filters"]["label"]
    assert labels == ["carapace.managed=true", "carapace.instance=default"]


@pytest.mark.asyncio
async def test_list_egress_probes_sees_only_this_instance(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path)
    runtime._client.containers.list.return_value = []

    await runtime.list_egress_probes()

    labels = runtime._client.containers.list.call_args.kwargs["filters"]["label"]
    assert labels == ["carapace.egress-check=true", "carapace.instance=default"]


@pytest.mark.asyncio
async def test_create_sandbox_labels_the_container_with_its_instance(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path)
    runtime.create = AsyncMock(return_value="container-1")

    await runtime.create_sandbox(
        SandboxConfig(name="carapace-sandbox-s", sandbox_id="s", session_id="s", image="i", labels={"a": "b"})
    )

    container = runtime.create.await_args.args[0]
    assert container.labels == {"a": "b", "carapace.instance": "default"}
    assert container.network == "carapace-sandbox-default"


@pytest.mark.asyncio
async def test_get_host_ip_outside_a_container_has_no_address(tmp_path: Path, monkeypatch) -> None:
    runtime = _make_runtime(tmp_path)
    monkeypatch.setenv("HOSTNAME", "my-laptop")
    runtime._client.containers.get.side_effect = NotFound("not a container")

    assert await runtime.get_host_ip("carapace-sandbox-default") is None
    runtime._client.networks.list.assert_not_called()


@pytest.mark.asyncio
async def test_get_host_ip_in_a_container_is_its_address_on_the_network(tmp_path: Path, monkeypatch) -> None:
    runtime = _make_runtime(tmp_path)
    monkeypatch.setenv("HOSTNAME", "abc123")
    container = runtime._client.containers.get.return_value
    container.attrs = {"NetworkSettings": {"Networks": {"carapace-sandbox-default": {"IPAddress": "172.18.0.5"}}}}

    assert await runtime.get_host_ip("carapace-sandbox-default") == "172.18.0.5"


@pytest.mark.asyncio
async def test_exec_keeps_protocol_stdout_separate_from_diagnostics(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path)
    container = runtime._client.containers.get.return_value
    container.exec_run.return_value = MagicMock(exit_code=0, output=(b"protocol\n", b"diagnostics\n"))

    result = await runtime.exec("container-1", "activate")

    assert result.stdout == "protocol\n"
    assert result.output == "protocol\n\n[stderr] diagnostics\n"


@pytest.mark.asyncio
async def test_list_pool_sandboxes_returns_empty_for_docker(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path)

    sandboxes = await runtime.list_pool_sandboxes()

    assert sandboxes == {}
    runtime._client.containers.list.assert_not_called()


@pytest.mark.asyncio
async def test_retained_sandbox_session_ids_includes_suspended_workspaces(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path)
    running = MagicMock()
    running.id = "container-1"
    running.labels = {"carapace.session": "sess-running", "carapace.managed": "true"}
    runtime._client.containers.list.return_value = [running]
    (tmp_path / "sessions" / "sess-suspended" / "workspace").mkdir(parents=True)
    (tmp_path / "sessions" / "sess-without-sandbox").mkdir(parents=True)

    retained = await runtime.retained_sandbox_session_ids()

    assert retained == {"sess-running", "sess-suspended"}


@pytest.mark.asyncio
async def test_destroy_sandbox_without_container_clears_workspace(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path)
    workspace = tmp_path / "sessions" / "sess-1" / "workspace"
    workspace.mkdir(parents=True)

    await runtime.destroy_sandbox("sess-1", "carapace-sandbox-sess-1", None)

    assert not workspace.exists()
    runtime._client.containers.get.assert_not_called()
