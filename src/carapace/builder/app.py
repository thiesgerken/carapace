"""The builder's HTTP API: the skills directory as an archive in; builds, and which inputs have updates, out."""

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
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from loguru import logger
from pydantic import TypeAdapter

from . import nix
from .cache import create_cache_app
from .models import BuilderInfo, BuildKey, BuildResult, GcResult, Roots, SkillName, UpdateCheck, UpstreamCache
from .skill_dir import SkillFileError, read_file
from .store import SkillStore

PORT = 8330
CACHE_PORT = 8331
# Written by the root start script; readable here, the secret half is not.
CACHE_PUBLIC_KEY = Path("/nix/var/carapace-builder-key/public")
# The skills directory is text and small lock files; anything near this is a mistake.
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

    @app.get("/builds/{key}", dependencies=authorized)
    async def get_build(key: BuildKey) -> BuildResult:
        result = store.result(key)
        if result is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"No build for key {key}")
        return result

    @app.get("/builds/{key}/files/{path:path}", dependencies=authorized)
    async def get_skill_file(key: BuildKey, path: str) -> Response:
        """A file of the skill directory of *key*'s build, as raw bytes."""
        result = store.result(key)
        if result is None or result.skill_dir is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"No skill directory for key {key}")
        try:
            content = read_file(result.skill_dir, path)
        except FileNotFoundError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"{path} is not in the skill directory") from exc
        except SkillFileError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
        return Response(content, media_type="application/octet-stream")

    @app.put("/builds/{key}", dependencies=authorized)
    async def build(key: BuildKey, skill: SkillName, request: Request, retry: bool = False) -> BuildResult:
        """Build *skill* of the skills directory archive in the body (tar, optionally compressed).

        Blocks until the build finished. A key that has a result is answered from it without
        building, unless the result is a failure and *retry* is set.
        """
        # A second request for the same key waits for the first and gets its result.
        async with store.locked(key):
            if (result := store.result(key)) is not None and not (retry and result.state == "failed"):
                return result
            archive = await request.body()
            if len(archive) > MAX_ARCHIVE_BYTES:
                raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "Skill archive too large")
            with tempfile.TemporaryDirectory(dir=store.work) as source:
                _extract(archive, Path(source))
                logger.info(f"Building skill {skill} ({key})")
                result = await nix.build_skill(Path(source), key, skill, system, store.roots)
            logger.info(f"Skill {skill} ({key}): {result.state}")
            store.save(result)
            return result

    @app.post("/updates", dependencies=authorized)
    async def check_updates(request: Request, inputs: Annotated[list[SkillName], Query(alias="input")]) -> UpdateCheck:
        """The lock each of *inputs* of the skills directory archive in the body would get from an update.

        Nothing is stored: upstreams move, so every call asks them again.
        """
        archive = await request.body()
        if len(archive) > MAX_ARCHIVE_BYTES:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "Skill archive too large")
        with tempfile.TemporaryDirectory(dir=store.work) as work:
            # Next to the lock files the updates write, never into the flake they read.
            source = Path(work) / "skills"
            source.mkdir()
            _extract(archive, source)
            logger.info(f"Checking skill inputs for updates: {', '.join(inputs)}")
            return UpdateCheck(
                inputs={name: await nix.update_input(source, name, Path(work) / f"{name}.lock") for name in inputs}
            )

    @app.put("/roots", status_code=status.HTTP_204_NO_CONTENT, dependencies=authorized)
    async def put_roots(roots: Roots) -> None:
        store.referenced(roots.keys)

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
