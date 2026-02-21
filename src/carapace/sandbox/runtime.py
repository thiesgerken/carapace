from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class Mount:
    source: str
    target: str
    read_only: bool = False


@dataclass
class ContainerConfig:
    image: str
    name: str
    labels: dict[str, str] = field(default_factory=dict)
    mounts: list[Mount] = field(default_factory=list)
    network: str = ""
    command: str | list[str] | None = None
    environment: dict[str, str] = field(default_factory=dict)


@dataclass
class ExecResult:
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
