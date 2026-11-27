"""Build results and GC roots on the builder's store volume, and what garbage collection drops.

The server tells the builder which skill trees the current heads of all knowledge repos reference
(`PUT /roots`). A tree keeps its result and GC root until no head has referenced it for the grace
period, so a sandbox can still download a path for a while after a push replaced it.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from loguru import logger
from pydantic import TypeAdapter

from . import nix
from .models import BuildResult, GcResult

_LAST_SEEN = TypeAdapter(dict[str, datetime])


def _now() -> datetime:
    return datetime.now(UTC)


def _write(path: Path, content: bytes) -> None:
    partial = path.with_suffix(".partial")
    partial.write_bytes(content)
    partial.replace(path)


class SkillStore:
    def __init__(self, state_dir: Path, gc_grace: timedelta) -> None:
        self._builds = state_dir / "builds"
        self.roots = state_dir / "roots"
        self.work = state_dir / "work"
        self._last_seen_file = state_dir / "last-seen.json"
        for directory in (self._builds, self.roots, self.work):
            directory.mkdir(parents=True, exist_ok=True)
        self._grace = gc_grace
        # One build per tree at a time, and dropping a tree waits for its build.
        self._locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._gc_lock = asyncio.Lock()

    @asynccontextmanager
    async def locked(self, tree: str) -> AsyncGenerator[None]:
        async with self._locks[tree]:
            yield

    def result(self, tree: str) -> BuildResult | None:
        path = self._builds / f"{tree}.json"
        return BuildResult.model_validate_json(path.read_text()) if path.exists() else None

    def save(self, result: BuildResult) -> None:
        _write(self._builds / f"{result.tree}.json", result.model_dump_json().encode())

    # The last-seen map is read and written without awaiting in between, so requests never interleave.
    def _read_last_seen(self) -> dict[str, datetime]:
        return _LAST_SEEN.validate_json(self._last_seen_file.read_bytes()) if self._last_seen_file.exists() else {}

    def _write_last_seen(self, last_seen: dict[str, datetime]) -> None:
        _write(self._last_seen_file, _LAST_SEEN.dump_json(last_seen))

    def _expired(self, last_seen: dict[str, datetime], tree: str) -> bool:
        return last_seen[tree] < _now() - self._grace

    def referenced(self, trees: list[str]) -> None:
        """Record that current heads reference *trees*."""
        last_seen = self._read_last_seen()
        last_seen.update(dict.fromkeys(trees, _now()))
        self._write_last_seen(last_seen)

    def _expired_trees(self) -> list[str]:
        last_seen = self._read_last_seen()
        # A built tree no head has referenced yet gets its grace period from now.
        for path in self._builds.glob("*.json"):
            last_seen.setdefault(path.stem, _now())
        self._write_last_seen(last_seen)
        return [tree for tree in last_seen if self._expired(last_seen, tree)]

    async def _drop(self, tree: str) -> bool:
        async with self.locked(tree):
            last_seen = self._read_last_seen()
            if tree in last_seen and not self._expired(last_seen, tree):
                return False  # referenced again while this waited for the build
            # Result and root go together, so no stored result names a collected path.
            (self._builds / f"{tree}.json").unlink(missing_ok=True)
            (self.roots / tree).unlink(missing_ok=True)
            last_seen.pop(tree, None)
            self._write_last_seen(last_seen)
            return True

    async def collect_garbage(self) -> GcResult:
        async with self._gc_lock:
            dropped = [tree for tree in self._expired_trees() if await self._drop(tree)]
            log = await nix.collect_garbage()
        summary = next((line for line in log.splitlines() if "store paths deleted" in line), "")
        logger.info(f"GC dropped {len(dropped)} skill trees; {summary}")
        return GcResult(dropped=dropped, log_tail=log)

    async def collect_garbage_every(self, interval: timedelta) -> None:
        while True:
            await asyncio.sleep(interval.total_seconds())
            await self.collect_garbage()
