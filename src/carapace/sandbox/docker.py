from __future__ import annotations

import asyncio
import logging

import docker
from docker.errors import NotFound
from docker.types import Mount as DockerMount

from carapace.sandbox.runtime import ContainerConfig, ExecResult

logger = logging.getLogger(__name__)


class DockerRuntime:
    def __init__(self) -> None:
        self._client: docker.DockerClient = docker.from_env()
        self._client.ping()

    async def create(self, config: ContainerConfig) -> str:
        def _create() -> str:
            # Remove stale container with same name if it exists
            try:
                stale = self._client.containers.get(config.name)
                stale.remove(force=True)
                logger.debug("Removed stale container %s", config.name)
            except NotFound:
                pass

            mounts = [
                DockerMount(
                    target=m.target,
                    source=m.source,
                    type="bind",
                    read_only=m.read_only,
                )
                for m in config.mounts
            ]

            container = self._client.containers.create(
                image=config.image,
                name=config.name,
                command=config.command or ["sleep", "infinity"],
                labels=config.labels,
                mounts=mounts,
                network=config.network or None,
                environment=config.environment or None,
                detach=True,
            )
            container.start()

            assert container.id is not None
            return container.id

        return await asyncio.to_thread(_create)

    async def exec(
        self,
        container_id: str,
        command: str | list[str],
        timeout: int = 30,
        env: dict[str, str] | None = None,
    ) -> ExecResult:
        def _exec() -> ExecResult:
            container = self._client.containers.get(container_id)
            cmd = ["sh", "-c", command] if isinstance(command, str) else command

            result = container.exec_run(cmd, environment=env, demux=True)
            exit_code = result.exit_code if result.exit_code is not None else -1

            stdout = result.output[0].decode() if result.output[0] else ""
            stderr = result.output[1].decode() if result.output[1] else ""
            output = stdout
            if stderr:
                output += f"\n[stderr] {stderr}"

            return ExecResult(exit_code=exit_code, output=output)

        try:
            return await asyncio.wait_for(asyncio.to_thread(_exec), timeout=timeout)
        except TimeoutError:
            return ExecResult(exit_code=-1, output=f"Error: command timed out ({timeout}s)")

    async def remove(self, container_id: str) -> None:
        def _remove() -> None:
            try:
                container = self._client.containers.get(container_id)
                container.remove(force=True)
            except NotFound:
                pass

        await asyncio.to_thread(_remove)

    async def is_running(self, container_id: str) -> bool:
        def _check() -> bool:
            try:
                container = self._client.containers.get(container_id)
                return container.status == "running"
            except NotFound:
                return False

        return await asyncio.to_thread(_check)

    async def get_ip(self, container_id: str, network: str) -> str | None:
        def _get_ip() -> str | None:
            try:
                container = self._client.containers.get(container_id)
                container.reload()
                networks = container.attrs.get("NetworkSettings", {}).get("Networks", {})
                net_info = networks.get(network)
                return net_info.get("IPAddress") if net_info else None
            except NotFound:
                return None

        return await asyncio.to_thread(_get_ip)
