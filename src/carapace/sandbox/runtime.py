from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel


class ContainerGoneError(Exception):
    """Raised when a container no longer exists."""


class SkillVenvError(Exception):
    """Raised when building a skill's virtualenv fails."""


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
    session_id: str
    image: str
    labels: dict[str, str] = {}
    environment: dict[str, str] = {}
    command: str | list[str] | None = None


class ExecResult(BaseModel):
    exit_code: int
    output: str


class ContainerRuntime(Protocol):
    # -- Sandbox lifecycle (runtime decides Docker vs K8s details) --
    async def create_sandbox(self, config: SandboxConfig) -> str: ...
    async def resume_sandbox(self, name: str) -> None: ...
    async def suspend_sandbox(self, name: str, container_id: str) -> None: ...
    async def destroy_sandbox(self, name: str, container_id: str) -> None: ...
    async def sandbox_exists(self, name: str) -> str | None:
        """Return the container/pod ID if the sandbox resource exists, else None."""
        ...

    async def list_sandboxes(self) -> dict[str, str]:
        """Return ``{session_id: container_or_pod_id}`` for all managed sandboxes."""
        ...

    # -- Low-level operations --
    async def exec(
        self,
        container_id: str,
        command: str | list[str],
        timeout: int = 30,
        env: dict[str, str] | None = None,
        workdir: str | None = None,
    ) -> ExecResult: ...
    async def is_running(self, container_id: str) -> bool: ...
    async def get_ip(self, container_id: str, network: str) -> str | None: ...
    async def resolve_self_network_name(self, logical_name: str) -> str: ...
    async def get_host_ip(self, network: str) -> str | None: ...
    def image_exists(self, tag: str) -> bool: ...
    async def ensure_network(self, name: str, *, internal: bool = False) -> None: ...
    async def get_self_network_info(self) -> dict[str, str]: ...
    async def logs(self, container_id: str, tail: int = 40) -> str: ...
