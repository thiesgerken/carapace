from __future__ import annotations

import asyncio
from pathlib import Path

import docker
import docker.models.containers
from docker.errors import APIError, DockerException, ImageNotFound, NotFound
from docker.types import Mount as DockerMount
from loguru import logger

from carapace.sandbox.runtime import ContainerConfig, ExecResult

_FALLBACK_SOCKETS = (Path.home() / ".docker/run/docker.sock",)


def _connect() -> docker.DockerClient:
    """Connect to Docker, trying DOCKER_HOST / default socket first, then
    well-known macOS socket paths."""
    try:
        client = docker.from_env()
        client.ping()
        return client
    except DockerException:
        pass

    for sock in _FALLBACK_SOCKETS:
        if sock.exists():
            try:
                client = docker.DockerClient(base_url=f"unix://{sock}")
                client.ping()
                logger.info(f"Connected to Docker via {sock}")
                return client
            except DockerException:
                continue

    raise DockerException("Cannot connect to Docker. Is Docker Desktop running?")


class DockerRuntime:
    def __init__(self) -> None:
        self._client = _connect()
        self._ensured_networks: set[str] = set()
        logger.info("Docker runtime connected")

    def _ensure_network(self, name: str) -> None:
        if name in self._ensured_networks:
            return
        existing = self._client.networks.list(names=[name])
        if not existing:
            self._client.networks.create(name, driver="bridge")
            logger.info(f"Created Docker network '{name}'")
        self._ensured_networks.add(name)

    async def create(self, config: ContainerConfig) -> str:
        def _create() -> str:
            if config.network:
                self._ensure_network(config.network)
            self._remove_stale(config.name)

            mounts = [
                DockerMount(
                    target=m.target,
                    source=m.source,
                    type="bind",
                    read_only=m.read_only,
                )
                for m in config.mounts
            ]

            container = self._create_container(config, mounts)
            container.start()

            assert container.id is not None
            logger.info(f"Created container {container.id[:12]} (image={config.image}, name={config.name})")
            return container.id

        return await asyncio.to_thread(_create)

    def _remove_stale(self, name: str) -> None:
        try:
            stale = self._client.containers.get(name)
            stale.remove(force=True)
            logger.debug(f"Removed stale container {name}")
        except NotFound:
            pass

    def _do_create(
        self,
        config: ContainerConfig,
        mounts: list[DockerMount],
    ) -> docker.models.containers.Container:
        return self._client.containers.create(
            image=config.image,
            name=config.name,
            command=config.command or ["sleep", "infinity"],
            labels=config.labels,
            mounts=mounts,
            network=config.network or None,
            environment=config.environment or None,
            detach=True,
        )

    def _create_container(
        self,
        config: ContainerConfig,
        mounts: list[DockerMount],
    ) -> docker.models.containers.Container:
        try:
            return self._do_create(config, mounts)
        except ImageNotFound:
            logger.info(f"Image {config.image} not found locally, pulling…")
            self._client.images.pull(config.image)
        except APIError as exc:
            if exc.status_code != 409:
                raise
            logger.warning(f"Name conflict for {config.name}, removing and retrying")
            self._remove_stale(config.name)

        return self._do_create(config, mounts)

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

        cmd_preview = command if isinstance(command, str) else " ".join(command)
        logger.debug(f"Exec in {container_id[:12]}: {cmd_preview} (timeout={timeout}s)")

        try:
            result = await asyncio.wait_for(asyncio.to_thread(_exec), timeout=timeout)
        except TimeoutError:
            logger.warning(f"Command timed out in {container_id[:12]} after {timeout}s: {cmd_preview}")
            return ExecResult(exit_code=-1, output=f"Error: command timed out ({timeout}s)")

        if result.exit_code != 0:
            logger.debug(f"Command exited {result.exit_code} in {container_id[:12]}: {cmd_preview}")
        return result

    async def remove(self, container_id: str) -> None:
        def _remove() -> None:
            try:
                container = self._client.containers.get(container_id)
                container.remove(force=True)
                logger.info(f"Removed container {container_id[:12]}")
            except NotFound:
                logger.debug(f"Container {container_id[:12]} already gone, skip remove")

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
