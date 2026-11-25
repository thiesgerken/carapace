"""The builder's HTTP API: a skill directory archive in, store paths and metadata out."""

from __future__ import annotations

import asyncio
import io
import os
import secrets
import tarfile
import tempfile
from datetime import timedelta
from pathlib import Path
from typing import Annotated

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from loguru import logger
from pydantic import TypeAdapter

from . import nix
from .cache import create_cache_app
from .models import BuilderInfo, BuildResult, GcResult, Roots, TreeHash, UpstreamCache
from .store import SkillStore

PORT = 8330
CACHE_PORT = 8331
# Written by the root start script; readable here, the secret half is not.
CACHE_PUBLIC_KEY = Path("/nix/var/carapace-builder-key/public")
# Skill directories are text and small lock files; anything near this is a mistake.
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
# Lives on the same volume as the store, so results and the paths they name come and go together.
STATE_DIR = Path("/nix/var/carapace-builder")
# Module level: FastAPI resolves the postponed annotations below in this module's globals.
_bearer = HTTPBearer()


def _extract(archive: bytes, destination: Path) -> None:
    try:
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:*") as tar:
            # The "data" filter refuses absolute paths, links out of the directory and device files.
            tar.extractall(destination, filter="data")
    except (tarfile.TarError, OSError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Invalid skill archive: {exc}") from exc


def create_app(token: str, store: SkillStore, system: str, cache_public_keys: list[str]) -> FastAPI:
    def authorize(credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer)]) -> None:
        if not secrets.compare_digest(credentials.credentials.encode(), token.encode()):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid builder token")

    app = FastAPI(title="Carapace skill builder")
    authorized = [Depends(authorize)]

    @app.get("/healthz")
    async def healthz() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/info", dependencies=authorized)
    async def info() -> BuilderInfo:
        return BuilderInfo(system=system, cache_public_keys=cache_public_keys)

    @app.get("/builds/{tree}", dependencies=authorized)
    async def get_build(tree: TreeHash) -> BuildResult:
        result = store.result(tree)
        if result is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"No build for tree {tree}")
        return result

    @app.put("/builds/{tree}", dependencies=authorized)
    async def build(tree: TreeHash, request: Request, retry: bool = False) -> BuildResult:
        """Build the skill directory archive in the body (tar, optionally compressed).

        Blocks until the build finished. A tree that has a result is answered from it without
        building, unless the result is a failure and *retry* is set.
        """
        # A second request for the same tree waits for the first and gets its result.
        async with store.locked(tree):
            if (result := store.result(tree)) is not None and not (retry and result.state == "failed"):
                return result
            archive = await request.body()
            if len(archive) > MAX_ARCHIVE_BYTES:
                raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "Skill archive too large")
            with tempfile.TemporaryDirectory(dir=store.work) as source:
                _extract(archive, Path(source))
                logger.info(f"Building skill tree {tree}")
                result = await nix.build_skill(Path(source), tree, system, store.roots)
            logger.info(f"Skill tree {tree}: {result.state}")
            store.save(result)
            return result

    @app.put("/roots", status_code=status.HTTP_204_NO_CONTENT, dependencies=authorized)
    async def put_roots(roots: Roots) -> None:
        store.referenced(roots.trees)

    @app.post("/gc", dependencies=authorized)
    async def gc() -> GcResult:
        return await store.collect_garbage()

    return app


async def _start_checks() -> str:
    system = await nix.current_system()
    await nix.verify_sandbox(system)
    logger.info(f"Nix build sandbox is effective, building for {system}")
    return system


async def _serve(token: str, upstreams: list[UpstreamCache], gc_grace: timedelta, gc_interval: timedelta) -> None:
    system = await _start_checks()
    keys = [CACHE_PUBLIC_KEY.read_text().strip(), *(upstream.public_key for upstream in upstreams)]
    store = SkillStore(STATE_DIR, gc_grace)
    # The build API and the cache are separate listeners: the session proxy forwards to the cache only.
    api = uvicorn.Server(uvicorn.Config(create_app(token, store, system, keys), host="0.0.0.0", port=PORT))
    cache = uvicorn.Server(uvicorn.Config(create_cache_app(upstreams), host="0.0.0.0", port=CACHE_PORT))
    # A failed GC run stops the builder rather than letting the store grow unnoticed.
    await asyncio.gather(api.serve(), cache.serve(), store.collect_garbage_every(gc_interval))


def _hours(name: str, default: float) -> timedelta:
    return timedelta(hours=float(os.environ.get(name, default)))


def main() -> None:
    """Entry point for `carapace-builder`."""
    token = os.environ.get("CARAPACE_BUILDER_TOKEN", "")
    if not token:
        raise SystemExit("CARAPACE_BUILDER_TOKEN must be set")
    upstreams = TypeAdapter(list[UpstreamCache]).validate_json(os.environ["CARAPACE_BUILDER_UPSTREAM_CACHES"])
    grace = _hours("CARAPACE_BUILDER_GC_GRACE_HOURS", 24)
    interval = _hours("CARAPACE_BUILDER_GC_INTERVAL_HOURS", 24)
    asyncio.run(_serve(token, upstreams, grace, interval))
