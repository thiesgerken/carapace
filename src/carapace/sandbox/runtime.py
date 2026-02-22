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


class ExecResult(BaseModel):
    exit_code: int
    output: str


class ContainerRuntime(Protocol):
    async def create(self, config: ContainerConfig) -> str: ...
    async def exec(
        self,
        container_id: str,
        command: str | list[str],
        timeout: int = 30,
        env: dict[str, str] | None = None,
    ) -> ExecResult: ...
    async def remove(self, container_id: str) -> None: ...
    async def is_running(self, container_id: str) -> bool: ...
    async def get_ip(self, container_id: str, network: str) -> str | None: ...
    async def resolve_self_network_name(self, logical_name: str) -> str: ...
    async def get_host_ip(self, network: str) -> str | None: ...
