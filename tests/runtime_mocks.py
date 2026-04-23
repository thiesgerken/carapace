from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from carapace.sandbox.runtime import ContainerRuntime, ExecResult, SandboxInspection


def make_runtime_mock() -> MagicMock:
    runtime = MagicMock(spec=ContainerRuntime)
    runtime.runtime_kind = "docker"
    runtime.create_sandbox = AsyncMock(return_value="container-1")
    runtime.resume_sandbox = AsyncMock()
    runtime.suspend_sandbox = AsyncMock()
    runtime.destroy_sandbox = AsyncMock()
    runtime.sandbox_exists = AsyncMock(return_value=None)
    runtime.list_sandboxes = AsyncMock(return_value={})
    runtime.inspect_sandbox = AsyncMock(
        side_effect=lambda _session_id, _name, container_id=None: SandboxInspection(
            exists=container_id is not None,
            status="running" if container_id is not None else "missing",
            resource_id=container_id,
        )
    )
    runtime.measure_workspace_usage = AsyncMock(return_value=None)
    runtime.exec = AsyncMock(return_value=ExecResult(exit_code=0, output="ok"))
    runtime.is_running = AsyncMock(return_value=True)
    runtime.get_ip = AsyncMock(return_value="172.18.0.22")
    runtime.resolve_self_network_name = AsyncMock(return_value="bridge")
    runtime.get_host_ip = AsyncMock(return_value="172.18.0.1")
    runtime.image_exists = MagicMock(return_value=True)
    runtime.ensure_network = AsyncMock()
    runtime.get_self_network_info = AsyncMock(return_value={"network": "bridge"})
    runtime.logs = AsyncMock(return_value="")
    return runtime
