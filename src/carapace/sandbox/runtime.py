from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel

EGRESS_PROBE_LABEL = "carapace.egress-check"
INSTANCE_LABEL = "carapace.instance"


class ContainerGoneError(Exception):
    """Raised when a container no longer exists."""


class DuplicateSandboxError(RuntimeError):
    """Raised when more than one live sandbox claims the same session."""


class Mount(BaseModel):
    source: str
    target: str
    read_only: bool = False


class ContainerConfig(BaseModel):
    image: str
    name: str
    labels: dict[str, str] = {}
    mounts: list[Mount] = []
    network: str | None
    command: str | list[str] | None = None
    environment: dict[str, str] = {}


class SandboxConfig(BaseModel):
    """Runtime-agnostic sandbox creation parameters.

    The manager builds this; each runtime translates it into Docker
    containers, K8s StatefulSets, etc.
    """

    name: str
    sandbox_id: str
    session_id: str
    image: str
    labels: dict[str, str] = {}
    environment: dict[str, str] = {}
    command: str | list[str] | None = None


class ExecResult(BaseModel):
    exit_code: int
    output: str
    stdout: str
    # Set by the exec flow, which kills processes left over from earlier calls first.
    leftover_processes_killed: int = 0


SandboxRuntimeKind = Literal["docker", "kubernetes"]
SandboxStatus = Literal["running", "scaled_down", "stopped", "missing", "pending", "error"]


class SandboxInspection(BaseModel):
    exists: bool
    status: SandboxStatus
    resource_id: str | None = None
    resource_kind: str | None = None
    storage_present: bool = False
    provisioned_bytes: int | None = None


class PoolSandbox(BaseModel):
    """An unattached warm-pool sandbox and the image its pods run."""

    container_id: str
    image: str


class ContainerRuntime(Protocol):
    runtime_kind: SandboxRuntimeKind

    # -- Sandbox lifecycle (runtime decides Docker vs K8s details) --
    async def create_sandbox(self, config: SandboxConfig) -> str: ...
    async def resume_sandbox(self, name: str, image: str) -> None:
        """Start a suspended sandbox again.

        *image* is the configured base image. Where resuming starts a fresh container
        anyway, the runtime switches the sandbox to it; a live container is never replaced.
        """
        ...

    async def suspend_sandbox(self, name: str, container_id: str) -> None: ...
    async def destroy_sandbox(self, session_id: str, name: str, container_id: str | None) -> None:
        """Remove the sandbox and its storage. *container_id* is None when no container is left."""
        ...

    async def sandbox_exists(self, name: str) -> str | None:
        """Return the container/pod ID if the sandbox resource exists, else None."""
        ...

    async def list_sandboxes(self) -> dict[str, list[str]]:
        """Return ``{session_id: [container_or_pod_id, ...]}`` for all live managed sandboxes.

        A session normally owns one sandbox. All are returned so that callers can
        detect and handle a session with several instead of seeing an arbitrary one.
        """
        ...

    async def retained_sandbox_session_ids(self) -> set[str]:
        """Return the sessions that hold a sandbox, running or suspended. Warm-pool members are excluded.

        Unlike ``list_sandboxes``, this includes sandboxes that keep only their storage
        while suspended, so resuming one does not count as creating a new sandbox.
        """
        ...

    async def list_pool_sandboxes(self) -> dict[str, PoolSandbox]:
        """Return ``{sandbox_id: PoolSandbox}`` for unattached warm-pool sandboxes."""
        ...

    async def list_egress_probes(self) -> dict[str, str]:
        """Return ``{sandbox_id: container_or_pod_id}`` for this server's live egress-check probes.

        A server killed during its start-up self-test leaves its probe behind, and the next start removes it.
        """
        ...

    async def claim_warm_sandbox(self, name: str, session_id: str) -> bool:
        """Mark a warm sandbox as claimed for *session_id* if the runtime supports it."""
        ...

    async def inspect_sandbox(
        self,
        session_id: str,
        name: str,
        container_id: str | None = None,
    ) -> SandboxInspection: ...

    async def measure_workspace_usage(self, session_id: str, container_id: str | None = None) -> int | None: ...

    # -- Low-level operations --
    async def exec(
        self,
        container_id: str,
        command: str | list[str],
        timeout: int = 30,
        env: dict[str, str] | None = None,
        workdir: str | None = None,
        stdin: bytes | None = None,
    ) -> ExecResult:
        """Run *command*; *stdin*, when given, is written to its stdin, which is then closed."""
        ...

    async def is_running(self, container_id: str) -> bool: ...
    async def get_ip(self, container_id: str, network: str) -> str | None: ...
    async def resolve_self_network_name(self, logical_name: str) -> str: ...
    async def get_host_ip(self, network: str) -> str | None: ...
    def image_exists(self, tag: str) -> bool: ...
    async def ensure_network(self, name: str, *, internal: bool = False) -> None: ...
    async def get_self_network_info(self) -> dict[str, str]: ...
    async def logs(self, container_id: str, tail: int = 40) -> str: ...
    async def write_stdout_log(self, container_id: str, message: str) -> None: ...
