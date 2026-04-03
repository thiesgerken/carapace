from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path
from typing import Protocol

import httpx
from loguru import logger

from carapace.models import CredentialBackendConfig, CredentialMetadata, CredentialsConfig


class VaultBackend(Protocol):
    """Abstract interface for credential storage backends.

    Implementations fetch secrets from a password manager (file, Bitwarden, …)
    and return metadata for listing/searching.
    """

    async def fetch(self, identifier: str) -> str:
        """Return the raw secret value for *identifier*.

        Raises ``KeyError`` if the identifier does not exist.
        """
        ...

    async def fetch_metadata(self, identifier: str) -> CredentialMetadata:
        """Return metadata (vault_path, name, description) for *identifier*.

        Raises ``KeyError`` if the identifier does not exist.
        """
        ...

    async def list(self, query: str = "") -> list[CredentialMetadata]:
        """Return metadata for all credentials matching *query*.

        An empty *query* returns everything the backend exposes.
        """
        ...


# ---------------------------------------------------------------------------
# Exposure filter
# ---------------------------------------------------------------------------


def is_exposed(identifier: str, cfg: CredentialBackendConfig) -> bool:
    """Check whether *identifier* passes the backend's exposure rules.

    Returns ``True`` when the credential should be visible; ``False`` otherwise.
    """
    if cfg.expose:
        return identifier in cfg.expose
    if cfg.hide:
        return identifier not in cfg.hide
    return True


# ---------------------------------------------------------------------------
# File backend
# ---------------------------------------------------------------------------


class FileVaultBackend:
    """Reads credentials from a ``.env``-format file (``key=value`` per line).

    The file is read once on construction and cached in memory.
    Lines starting with ``#`` and blank lines are ignored.
    """

    def __init__(self, *, name: str, path: Path, cfg: CredentialBackendConfig) -> None:
        self._name = name
        self._cfg = cfg
        self._secrets: dict[str, str] = {}
        self._load(path)

    def _load(self, path: Path) -> None:
        if not path.exists():
            logger.warning(f"Credential file {path} does not exist — backend '{self._name}' has no secrets")
            return
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, sep, value = line.partition("=")
            key = key.strip()
            if not sep:
                logger.warning(f"File backend '{self._name}': ignoring invalid line (no '='): {line!r}")
                continue
            if key:
                self._secrets[key] = value
        logger.info(f"File credential backend '{self._name}': loaded {len(self._secrets)} key(s) from {path}")

    def _vault_path(self, key: str) -> str:
        return f"{self._name}/{key}"

    async def fetch(self, identifier: str) -> str:
        if identifier not in self._secrets:
            raise KeyError(f"Credential '{identifier}' not found in backend '{self._name}'")
        if not is_exposed(identifier, self._cfg):
            raise KeyError(f"Credential '{identifier}' not found in backend '{self._name}'")
        return self._secrets[identifier]

    async def fetch_metadata(self, identifier: str) -> CredentialMetadata:
        if identifier not in self._secrets:
            raise KeyError(f"Credential '{identifier}' not found in backend '{self._name}'")
        if not is_exposed(identifier, self._cfg):
            raise KeyError(f"Credential '{identifier}' not found in backend '{self._name}'")
        return CredentialMetadata(vault_path=self._vault_path(identifier), name=identifier)

    async def list(self, query: str = "") -> list[CredentialMetadata]:
        results: list[CredentialMetadata] = []
        for key in sorted(self._secrets):
            if not is_exposed(key, self._cfg):
                continue
            if query and query.lower() not in key.lower():
                continue
            results.append(CredentialMetadata(vault_path=self._vault_path(key), name=key))
        return results


# ---------------------------------------------------------------------------
# bw serve process manager
# ---------------------------------------------------------------------------


class BwServeManager:
    """Manages a ``bw serve`` child process for the Vaultwarden backend.

    Handles login, unlock, process start/restart, and periodic vault sync.
    The ``bw`` CLI binary must be on ``$PATH`` (or at *bw_path*).
    """

    def __init__(
        self,
        *,
        server_url: str,
        port: int = 8087,
        bw_path: str = "bw",
        sync_interval: float = 300.0,
    ) -> None:
        self._server_url = server_url
        self._port = port
        self._bw = bw_path
        self._sync_interval = sync_interval
        self._process: asyncio.subprocess.Process | None = None
        self._session_key: str | None = None
        self._sync_task: asyncio.Task[None] | None = None

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self._port}"

    async def _run_bw(self, *args: str, env_extra: dict[str, str] | None = None) -> str:
        env = {**os.environ, **(env_extra or {})}
        proc = await asyncio.create_subprocess_exec(
            self._bw,
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"bw {' '.join(args)} failed (exit {proc.returncode}): {stderr.decode().strip()}")
        return stdout.decode().strip()

    async def start(self) -> None:
        """Login, unlock, and start ``bw serve``."""
        bw = shutil.which(self._bw) or self._bw

        if self._server_url:
            await self._run_bw("config", "server", self._server_url)
            logger.info(f"bw config server set to {self._server_url}")

        await self._run_bw("login", "--apikey")
        logger.info("bw login successful")

        raw = await self._run_bw("unlock", "--passwordenv", "CARAPACE_VAULT_PASSWORD", "--raw")
        self._session_key = raw
        logger.info("bw unlock successful")

        env = {**os.environ, "BW_SESSION": self._session_key}
        self._process = await asyncio.create_subprocess_exec(
            bw,
            "serve",
            "--port",
            str(self._port),
            "--hostname",
            "127.0.0.1",
            env=env,
        )
        logger.info(f"bw serve started on 127.0.0.1:{self._port} (pid={self._process.pid})")

        await self._wait_ready()

        self._sync_task = asyncio.create_task(self._periodic_sync())

    async def _wait_ready(self, timeout: float = 30.0) -> None:
        """Poll until bw serve responds."""
        deadline = asyncio.get_event_loop().time() + timeout
        async with httpx.AsyncClient() as client:
            while asyncio.get_event_loop().time() < deadline:
                try:
                    resp = await client.get(f"{self.base_url}/status", timeout=2.0)
                    if resp.status_code == 200:
                        logger.info("bw serve is ready")
                        return
                except httpx.ConnectError:
                    pass
                await asyncio.sleep(0.5)
        raise RuntimeError(f"bw serve did not become ready within {timeout}s")

    async def _periodic_sync(self) -> None:
        """Periodically sync the vault from the server."""
        while True:
            await asyncio.sleep(self._sync_interval)
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.post(f"{self.base_url}/sync", timeout=30.0)
                    if resp.status_code == 200:
                        logger.debug("bw vault synced")
                    else:
                        logger.warning(f"bw sync returned {resp.status_code}: {resp.text}")
            except Exception as exc:
                logger.warning(f"bw sync failed: {exc}")

    async def stop(self) -> None:
        if self._sync_task:
            self._sync_task.cancel()
            self._sync_task = None
        if self._process and self._process.returncode is None:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except TimeoutError:
                self._process.kill()
            logger.info("bw serve stopped")
        self._process = None

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.returncode is None


# ---------------------------------------------------------------------------
# Vaultwarden backend
# ---------------------------------------------------------------------------


class VaultwardenBackend:
    """Talks to a local ``bw serve`` instance for credential access."""

    def __init__(
        self,
        *,
        name: str,
        bw_serve: BwServeManager,
        cfg: CredentialBackendConfig,
    ) -> None:
        self._name = name
        self._bw_serve = bw_serve
        self._cfg = cfg
        self._client = httpx.AsyncClient(base_url=bw_serve.base_url, timeout=30.0)

    def _vault_path(self, uuid: str) -> str:
        return f"{self._name}/{uuid}"

    async def fetch(self, identifier: str) -> str:
        """Fetch the password for a Bitwarden item by UUID."""
        if not is_exposed(identifier, self._cfg):
            raise KeyError(f"Credential '{identifier}' not found in backend '{self._name}'")
        resp = await self._client.get(f"/object/password/{identifier}")
        if resp.status_code == 404:
            raise KeyError(f"Credential '{identifier}' not found in backend '{self._name}'")
        resp.raise_for_status()
        data = resp.json()
        return data.get("data", {}).get("data", "")

    async def fetch_metadata(self, identifier: str) -> CredentialMetadata:
        """Fetch item metadata by UUID."""
        if not is_exposed(identifier, self._cfg):
            raise KeyError(f"Credential '{identifier}' not found in backend '{self._name}'")
        resp = await self._client.get(f"/object/item/{identifier}")
        if resp.status_code == 404:
            raise KeyError(f"Credential '{identifier}' not found in backend '{self._name}'")
        resp.raise_for_status()
        item = resp.json().get("data", {})
        return CredentialMetadata(
            vault_path=self._vault_path(identifier),
            name=item.get("name", identifier),
        )

    async def list(self, query: str = "") -> list[CredentialMetadata]:
        """List items, optionally filtered by search query."""
        params: dict[str, str] = {}
        if query:
            params["search"] = query
        resp = await self._client.get("/list/object/items", params=params)
        resp.raise_for_status()
        items = resp.json().get("data", {}).get("data", [])
        results: list[CredentialMetadata] = []
        for item in items:
            item_id = item.get("id", "")
            if not is_exposed(item_id, self._cfg):
                continue
            results.append(
                CredentialMetadata(
                    vault_path=self._vault_path(item_id),
                    name=item.get("name", item_id),
                )
            )
        return results

    async def close(self) -> None:
        await self._client.aclose()


# ---------------------------------------------------------------------------
# Registry — dispatches vault_path prefixes to backend instances
# ---------------------------------------------------------------------------


class CredentialRegistry:
    """Routes ``<backend-name>/<identifier>`` vault paths to the correct backend."""

    def __init__(self) -> None:
        self._backends: dict[str, VaultBackend] = {}

    def register(self, name: str, backend: VaultBackend) -> None:
        self._backends[name] = backend

    def _resolve(self, vault_path: str) -> tuple[VaultBackend, str]:
        """Split *vault_path* into backend + identifier and return both.

        Raises ``KeyError`` if the backend prefix is unknown.
        """
        prefix, _, identifier = vault_path.partition("/")
        if not identifier:
            raise KeyError(f"Invalid vault_path (missing backend prefix): {vault_path!r}")
        backend = self._backends.get(prefix)
        if backend is None:
            raise KeyError(f"Unknown credential backend: {prefix!r}")
        return backend, identifier

    async def fetch(self, vault_path: str) -> str:
        backend, identifier = self._resolve(vault_path)
        return await backend.fetch(identifier)

    async def fetch_metadata(self, vault_path: str) -> CredentialMetadata:
        backend, identifier = self._resolve(vault_path)
        return await backend.fetch_metadata(identifier)

    async def list(self, query: str = "") -> list[CredentialMetadata]:
        results: list[CredentialMetadata] = []
        for backend in self._backends.values():
            results.extend(await backend.list(query))
        return results

    @property
    def backend_names(self) -> list[str]:
        return list(self._backends)


async def build_credential_registry(config: CredentialsConfig, data_dir: Path) -> CredentialRegistry:
    """Create a :class:`CredentialRegistry` from the ``credentials`` config block."""
    registry = CredentialRegistry()
    for name, cfg in config.backends.items():
        if cfg.type == "file":
            path = Path(cfg.path) if cfg.path else data_dir / "secrets.env"
            backend = FileVaultBackend(name=name, path=path, cfg=cfg)
            registry.register(name, backend)
        elif cfg.type == "vaultwarden":
            bw_serve = BwServeManager(
                server_url=cfg.url,
                port=cfg.bw_serve_port,
            )
            try:
                await bw_serve.start()
            except Exception as exc:
                logger.error(f"Failed to start bw serve for backend '{name}': {exc}")
                continue
            backend = VaultwardenBackend(name=name, bw_serve=bw_serve, cfg=cfg)
            registry.register(name, backend)
        else:
            logger.warning(f"Unknown credential backend type '{cfg.type}' for '{name}' — skipping")
    return registry


async def shutdown_credential_registry(registry: CredentialRegistry) -> None:
    """Shut down all managed backends (stop bw serve processes, close clients)."""
    for name in registry.backend_names:
        backend = registry._backends.get(name)
        if isinstance(backend, VaultwardenBackend):
            await backend.close()
            await backend._bw_serve.stop()
