"""The builder's HTTP API: a skill directory archive in, store paths and metadata out."""

from __future__ import annotations

import asyncio
import io
import os
import secrets
import tarfile
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Annotated

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from loguru import logger

from . import nix
from .models import BuilderInfo, BuildResult, TreeHash

PORT = 8330
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


def create_app(token: str, state_dir: Path, system: str) -> FastAPI:
    builds_dir = state_dir / "builds"
    roots_dir = state_dir / "roots"
    work_dir = state_dir / "work"
    for directory in (builds_dir, roots_dir, work_dir):
        directory.mkdir(parents=True, exist_ok=True)
    # One build per tree at a time; a second request for the same tree waits and gets the result.
    locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    def authorize(credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer)]) -> None:
        if not secrets.compare_digest(credentials.credentials.encode(), token.encode()):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid builder token")

    def stored(tree: str) -> BuildResult | None:
        path = builds_dir / f"{tree}.json"
        return BuildResult.model_validate_json(path.read_text()) if path.exists() else None

    def store(result: BuildResult) -> None:
        path = builds_dir / f"{result.tree}.json"
        partial = path.with_suffix(".partial")
        partial.write_text(result.model_dump_json())
        partial.replace(path)

    app = FastAPI(title="Carapace skill builder")
    authorized = [Depends(authorize)]

    @app.get("/healthz")
    async def healthz() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/info", dependencies=authorized)
    async def info() -> BuilderInfo:
        return BuilderInfo(system=system)

    @app.get("/builds/{tree}", dependencies=authorized)
    async def get_build(tree: TreeHash) -> BuildResult:
        result = stored(tree)
        if result is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"No build for tree {tree}")
        return result

    @app.put("/builds/{tree}", dependencies=authorized)
    async def build(tree: TreeHash, request: Request) -> BuildResult:
        """Build the skill directory archive in the body (tar, optionally compressed).

        Blocks until the build finished. A tree that has a result, succeeded or failed, is
        answered from it without building.
        """
        async with locks[tree]:
            if (result := stored(tree)) is not None:
                return result
            archive = await request.body()
            if len(archive) > MAX_ARCHIVE_BYTES:
                raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "Skill archive too large")
            with tempfile.TemporaryDirectory(dir=work_dir) as source:
                _extract(archive, Path(source))
                logger.info(f"Building skill tree {tree}")
                result = await nix.build_skill(Path(source), tree, system, roots_dir)
            logger.info(f"Skill tree {tree}: {result.state}")
            store(result)
            return result

    return app


async def _start_checks() -> str:
    system = await nix.current_system()
    await nix.verify_sandbox(system)
    logger.info(f"Nix build sandbox is effective, building for {system}")
    return system


def main() -> None:
    """Entry point for `carapace-builder`."""
    token = os.environ.get("CARAPACE_BUILDER_TOKEN", "")
    if not token:
        raise SystemExit("CARAPACE_BUILDER_TOKEN must be set")
    system = asyncio.run(_start_checks())
    uvicorn.run(create_app(token, STATE_DIR, system), host="0.0.0.0", port=PORT)
