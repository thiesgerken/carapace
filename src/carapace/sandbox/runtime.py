from __future__ import annotations

import ipaddress
from typing import ClassVar, Protocol

from pydantic import BaseModel, Field, field_validator


class ContainerGoneError(Exception):
    """Raised when a container no longer exists."""


class SkillActivationError(Exception):
    """Raised when automatic skill activation/setup fails."""


class SkillFileCredential(BaseModel):
    path: str
    value: str


class SkillActivationInputs(BaseModel):
    environment: dict[str, str] = {}
    file_credentials: list[SkillFileCredential] = []


class NetworkTunnel(BaseModel):
    host: str
    remote_port: int = Field(ge=1, le=65535)
    local_port: int = Field(ge=1024, le=65535)
    description: str = ""

    _BLOCKED_HOSTS: ClassVar[set[str]] = {
        "localhost",
        "host.docker.internal",
        "gateway.docker.internal",
        "kubernetes.default.svc",
        "kubernetes.default.svc.cluster.local",
    }
    _BLOCKED_SUFFIXES: ClassVar[tuple[str, ...]] = (
        ".localhost",
        ".local",
        ".internal",
        ".home.arpa",
        ".localdomain",
        ".svc",
        ".cluster.local",
    )

    @field_validator("host")
    @classmethod
    def _validate_host(cls, value: str) -> str:
        host = value.strip().lower()
        if not host:
            raise ValueError("network tunnel host must not be empty")
        if "*" in host:
            raise ValueError("network tunnel host must be exact; wildcards are not allowed")
        if any(ch in host for ch in ("/", ":", " ", "\t", "\n", "\r")):
            raise ValueError("network tunnel host must be a plain hostname")
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise ValueError("network tunnel host must not be an IP literal")
        if host in cls._BLOCKED_HOSTS or host in {"127.0.0.1", "::1", "0.0.0.0"}:
            raise ValueError("network tunnel host must not target loopback or wildcard addresses")
        if any(host.endswith(suffix) for suffix in cls._BLOCKED_SUFFIXES):
            raise ValueError("network tunnel host must not target internal-only service names")
        return host

    @property
    def endpoint(self) -> str:
        return f"{self.host}:{self.remote_port}"

    @property
    def display(self) -> str:
        return f"{self.host}:{self.remote_port} via :{self.local_port}"


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
