"""The Carapace server's side of the builder API."""

from __future__ import annotations

import platform

import httpx

from .models import CACHE_HOST, BuilderInfo, BuildResult


class BuilderSystemMismatchError(RuntimeError):
    pass


def sandbox_system() -> str:
    """The Nix system of this host's sandboxes: always Linux, on the server's CPU architecture.

    Builder and sandboxes must share one architecture (#548). The server cannot see a pod's node
    up front, so its own CPU stands in, which also holds for Docker Desktop on a Mac.
    """
    machine = platform.machine().lower()
    cpu = {"amd64": "x86_64", "arm64": "aarch64"}.get(machine, machine)
    return f"{cpu}-linux"


class BuilderClient:
    def __init__(self, url: str, token: str, timeout_seconds: float) -> None:
        self._client = httpx.AsyncClient(
            base_url=url, headers={"Authorization": f"Bearer {token}"}, timeout=timeout_seconds
        )
        self._info: BuilderInfo | None = None

    async def check_system(self) -> None:
        """Raise if the builder builds for another system than the sandboxes run on."""
        response = await self._client.get("/info")
        response.raise_for_status()
        info = BuilderInfo.model_validate(response.json())
        expected = sandbox_system()
        if info.system != expected:
            raise BuilderSystemMismatchError(f"The builder builds for {info.system}, but sandboxes run on {expected}")
        self._info = info

    async def _ensure_system(self) -> None:
        if self._info is None:
            await self.check_system()

    def sandbox_nix_config(self) -> str | None:
        """`NIX_CONFIG` for sandboxes: the builder's cache as the only substituter.

        None until the builder has answered once; sandboxes then keep the image's defaults.
        """
        if self._info is None:
            return None
        return "\n".join(
            [
                f"substituters = http://{CACHE_HOST}",
                f"trusted-public-keys = {' '.join(self._info.cache_public_keys)}",
                # Fastest and smallest on a sandbox's single CPU (#548).
                "max-substitution-jobs = 1",
                # Nix otherwise remembers a missing path for an hour, past the build that adds it.
                "narinfo-cache-negative-ttl = 30",
            ]
        )

    async def get(self, tree: str) -> BuildResult | None:
        await self._ensure_system()
        response = await self._client.get(f"/builds/{tree}")
        if response.status_code == httpx.codes.NOT_FOUND:
            return None
        response.raise_for_status()
        return BuildResult.model_validate(response.json())

    async def build(self, tree: str, archive: bytes) -> BuildResult:
        """Build a skill directory archive (`git archive` of its tree). Blocks until the build ends.

        Builds can take minutes; callers must not hold up a push or a session on this.
        """
        await self._ensure_system()
        response = await self._client.put(f"/builds/{tree}", content=archive)
        response.raise_for_status()
        return BuildResult.model_validate(response.json())

    async def aclose(self) -> None:
        await self._client.aclose()
