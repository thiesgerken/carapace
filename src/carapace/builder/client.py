"""The Carapace server's side of the builder API."""

from __future__ import annotations

import platform

import httpx

from .models import CACHE_HOST, BuilderInfo, BuildResult, Roots, UpdateCheck


class BuilderSystemMismatchError(RuntimeError):
    pass


class BuilderUnavailableError(RuntimeError):
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

    async def check_system(self) -> BuilderInfo:
        """Fetch `/info`; raise if the builder builds for another system than the sandboxes run on."""
        response = await self._client.get("/info")
        response.raise_for_status()
        info = BuilderInfo.model_validate(response.json())
        expected = sandbox_system()
        if info.system != expected:
            raise BuilderSystemMismatchError(f"The builder builds for {info.system}, but sandboxes run on {expected}")
        self._info = info
        return info

    async def _ensure_system(self) -> None:
        if self._info is None:
            await self.check_system()

    async def sandbox_nix_config(self) -> str:
        """`NIX_CONFIG` for a new sandbox: the builder's cache as the only substituter.

        Fetches the keys on every call, so a builder with a new key (a wiped volume) is picked up.
        A builder that does not answer fails the sandbox start: falling back to another substituter
        would quietly put every download behind the domain gate.
        """
        try:
            info = await self.check_system()
        except httpx.HTTPError as exc:
            raise BuilderUnavailableError(
                f"The skill builder is configured but unreachable ({exc}); sandboxes need its cache keys"
            ) from exc
        return "\n".join(
            [
                f"substituters = http://{CACHE_HOST}",
                f"trusted-public-keys = {' '.join(info.cache_public_keys)}",
                # Fastest and smallest on a sandbox's single CPU (#548).
                "max-substitution-jobs = 1",
                # Nix otherwise remembers a missing path for an hour, past the build that adds it.
                "narinfo-cache-negative-ttl = 30",
            ]
        )

    async def get(self, key: str) -> BuildResult | None:
        await self._ensure_system()
        response = await self._client.get(f"/builds/{key}")
        if response.status_code == httpx.codes.NOT_FOUND:
            return None
        response.raise_for_status()
        return BuildResult.model_validate(response.json())

    async def build(self, key: str, skill: str, archive: bytes, *, retry: bool = False) -> BuildResult:
        """Build *skill* of a skills directory archive (`git archive` of its tree). Blocks until the build ends.

        A stored result is returned as it is, unless it is a failure and *retry* is set. Builds can
        take minutes; callers must not hold up a push or a session on this.
        """
        await self._ensure_system()
        response = await self._client.put(f"/builds/{key}", content=archive, params={"skill": skill, "retry": retry})
        response.raise_for_status()
        return BuildResult.model_validate(response.json())

    async def check_updates(self, archive: bytes, inputs: list[str]) -> UpdateCheck:
        """The lock each input of a skills directory archive would get from `nix flake update <input>`.

        Fetches from every upstream, so it takes as long as they do; callers run it in the background.
        """
        await self._ensure_system()
        response = await self._client.post("/updates", content=archive, params={"input": inputs})
        response.raise_for_status()
        return UpdateCheck.model_validate(response.json())

    async def put_roots(self, keys: list[str]) -> None:
        """Tell the builder which build keys the current heads reference; the rest may be collected."""
        response = await self._client.put("/roots", json=Roots(keys=keys).model_dump())
        response.raise_for_status()

    async def aclose(self) -> None:
        await self._client.aclose()
