from __future__ import annotations

from typing import Annotated, Protocol

from pydantic import BaseModel, Field


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
    labels: Annotated[dict[str, str], Field(default_factory=dict)]
    mounts: Annotated[list[Mount], Field(default_factory=list)]
    network: str = ""
    command: str | list[str] | None = None
    environment: Annotated[dict[str, str], Field(default_factory=dict)]


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
