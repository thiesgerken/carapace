from __future__ import annotations

import asyncio
import io
from pathlib import Path

import docker
import docker.models.containers
from docker.errors import APIError, DockerException, ImageNotFound, NotFound
from docker.types import Mount as DockerMount
from loguru import logger

from carapace.sandbox.runtime import ContainerConfig, ContainerGoneError, ExecResult

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
        # Maps logical network name → actual Docker network name.
        # Docker Compose prefixes networks with the project name, so
        # "carapace-sandbox" becomes "carapace_carapace-sandbox".  We resolve
        # this once and reuse the actual name for all container operations.
        self._network_name_cache: dict[str, str] = {}
        logger.info("Docker runtime connected")

    def build_image(self, dockerfile_content: str, tag: str) -> None:
        """Build a Docker image from Dockerfile content and tag it."""
        logger.info(f"Building sandbox image '{tag}' from bundled Dockerfile…")
        fileobj = io.BytesIO(dockerfile_content.encode())
        _, logs = self._client.images.build(fileobj=fileobj, tag=tag, rm=True)
        for chunk in logs:  # type: ignore[union-attr]
            msg = chunk.get("stream", "") if isinstance(chunk, dict) else ""
            if line := str(msg).strip():
                logger.debug(f"[docker build] {line}")
        logger.info(f"Sandbox image '{tag}' built successfully")

    def _ensure_network(self, name: str, *, internal: bool = False) -> str:
        """Ensure the network exists and return its actual Docker name.

        Docker Compose adds a project-name prefix (e.g. ``carapace_carapace-sandbox``).
        We resolve that here so containers are always connected to the right network.
        """
        if name in self._network_name_cache:
            return self._network_name_cache[name]

        existing = self._client.networks.list(names=[name])
        if existing:
            # Pick the network whose name matches exactly or ends with _{name}.
            # n.name is str | None in the SDK stubs, so guard against None.
            actual: str = next(
                (n.name for n in existing if n.name and (n.name == name or n.name.endswith(f"_{name}"))),
                existing[0].name or name,
            )
            if actual != name:
                logger.debug(f"Resolved network '{name}' → '{actual}' (docker-compose prefix)")
        else:
            self._client.networks.create(name, driver="bridge", internal=internal)
            logger.info(f"Created Docker network '{name}' (internal={internal})")
            actual = name

        self._network_name_cache[name] = actual
        return actual

    async def ensure_network(self, name: str, *, internal: bool = False) -> None:
        """Public async wrapper — ensures the Docker network exists."""
        await asyncio.to_thread(self._ensure_network, name, internal=internal)

    async def create(self, config: ContainerConfig) -> str:
        def _create() -> str:
            actual_network = ""
            if config.network:
                actual_network = self._ensure_network(config.network, internal=True)
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

            # Use the resolved (possibly prefixed) network name so the container
            # joins the correct network rather than having Docker create a new one.
            effective_config = config.model_copy(update={"network": actual_network}) if actual_network else config
            container = self._create_container(effective_config, mounts)
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
            network=config.network,
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
            try:
                container = self._client.containers.get(container_id)
            except NotFound as err:
                raise ContainerGoneError(f"Container {container_id[:12]} no longer exists") from err
            cmd = ["bash", "-c", command] if isinstance(command, str) else command

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
        except ContainerGoneError:
            raise
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

    async def get_self_network_info(self) -> dict[str, str]:
        """Return all network names → IP addresses visible to this process.

        When running inside Docker (``HOSTNAME`` resolves to a container),
        reads the container's ``NetworkSettings`` so every attached network is
        reported with its logical name.  Outside Docker falls back to
        enumerating local interfaces via the OS.
        """
        import os
        import socket

        hostname = os.environ.get("HOSTNAME", "")

        if hostname:

            def _from_docker() -> dict[str, str] | None:
                try:
                    container = self._client.containers.get(hostname)
                    container.reload()
                    nets = container.attrs.get("NetworkSettings", {}).get("Networks", {})
                    return {name: info.get("IPAddress", "") for name, info in nets.items() if info.get("IPAddress")}
                except NotFound:
                    return None

            result = await asyncio.to_thread(_from_docker)
            if result is not None:
                return result

        # Host / fallback: use SIOCGIFADDR ioctl on Linux, getaddrinfo elsewhere
        def _from_os() -> dict[str, str]:
            try:
                import fcntl
                import struct

                siocgifaddr = 0x8915
                addrs: dict[str, str] = {}
                for _, iface in socket.if_nameindex():
                    try:
                        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                            ip = socket.inet_ntoa(
                                fcntl.ioctl(s.fileno(), siocgifaddr, struct.pack("256s", iface[:15].encode()))[20:24]
                            )
                        addrs[iface] = ip
                    except OSError:
                        pass
                return addrs
            except Exception:
                # Final fallback: just resolve our own hostname
                try:
                    return {"hostname": socket.gethostbyname(socket.gethostname())}
                except Exception:
                    return {}

        return await asyncio.to_thread(_from_os)

    async def resolve_self_network_name(self, logical_name: str) -> str:
        """Return the actual Docker network name this container is attached to.

        Docker Compose prefixes network names with the project name, so the
        logical name ``carapace-sandbox`` becomes ``carapace_carapace-sandbox``.
        This method inspects the current container's ``NetworkSettings`` to find
        the real name, falling back to ``logical_name`` when not running inside
        Docker or no match is found.
        """
        import os

        hostname = os.environ.get("HOSTNAME", "")
        if not hostname:
            return logical_name

        def _resolve() -> str:
            try:
                container = self._client.containers.get(hostname)
                container.reload()
                nets: dict[str, object] = container.attrs.get("NetworkSettings", {}).get("Networks", {})
                if logical_name in nets:
                    return logical_name
                for key in nets:
                    if key.endswith(f"_{logical_name}"):
                        return key
                return logical_name
            except NotFound:
                return logical_name

        return await asyncio.to_thread(_resolve)

    async def get_host_ip(self, network: str) -> str | None:
        """Get the IP of the current host container on *network*.

        ``network`` should be the actual Docker network name (as returned by
        ``resolve_self_network_name``).  Returns ``None`` when not running
        inside Docker or the network isn't found.
        """
        import os

        hostname = os.environ.get("HOSTNAME", "")
        if not hostname:
            return None

        def _resolve() -> str | None:
            try:
                container = self._client.containers.get(hostname)
                container.reload()
                nets = container.attrs.get("NetworkSettings", {}).get("Networks", {})
                info = nets.get(network)
                return info.get("IPAddress") if info else None
            except NotFound:
                return None

        return await asyncio.to_thread(_resolve)

    async def get_network_gateway(self, network: str) -> str | None:
        """Return the gateway IP of a Docker bridge *network*.

        This is the host's IP as seen from containers on that network.
        Useful when the server runs on the host (not inside Docker).
        """

        def _resolve() -> str | None:
            nets = self._client.networks.list(names=[network])
            if not nets:
                return None
            net = nets[0]
            net.reload()
            ipam_configs = net.attrs.get("IPAM", {}).get("Config", [])
            for cfg in ipam_configs:
                gw = cfg.get("Gateway")
                if gw:
                    return gw
            return None

        return await asyncio.to_thread(_resolve)

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
