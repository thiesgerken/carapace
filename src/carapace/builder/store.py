"""Build results and GC roots on the builder's store volume, and what garbage collection drops.

The server tells the builder which build keys the skills at the current heads of all knowledge repos
have (`PUT /roots`). A key keeps its result and GC root until no head has referenced it for the grace
period, so a sandbox can still download a path for a while after a push replaced it.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator
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
        # One build per key at a time, and dropping a key waits for its build.
        self._locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._gc_lock = asyncio.Lock()

    @asynccontextmanager
    async def locked(self, key: str) -> AsyncIterator[None]:
        async with self._locks[key]:
            yield

    def result(self, key: str) -> BuildResult | None:
        path = self._builds / f"{key}.json"
        return BuildResult.model_validate_json(path.read_text()) if path.exists() else None

    def save(self, result: BuildResult) -> None:
        _write(self._builds / f"{result.key}.json", result.model_dump_json().encode())

    # The last-seen map is read and written without awaiting in between, so requests never interleave.
    def _read_last_seen(self) -> dict[str, datetime]:
        return _LAST_SEEN.validate_json(self._last_seen_file.read_bytes()) if self._last_seen_file.exists() else {}

    def _write_last_seen(self, last_seen: dict[str, datetime]) -> None:
        _write(self._last_seen_file, _LAST_SEEN.dump_json(last_seen))

    def _expired(self, last_seen: dict[str, datetime], key: str) -> bool:
        return last_seen[key] < _now() - self._grace

    def referenced(self, keys: list[str]) -> None:
        """Record that current heads reference *keys*."""
        last_seen = self._read_last_seen()
        last_seen.update(dict.fromkeys(keys, _now()))
        self._write_last_seen(last_seen)

    def _expired_keys(self) -> list[str]:
        last_seen = self._read_last_seen()
        # A built key no head has referenced yet gets its grace period from now.
        for path in self._builds.glob("*.json"):
            last_seen.setdefault(path.stem, _now())
        self._write_last_seen(last_seen)
        return [key for key in last_seen if self._expired(last_seen, key)]

    async def _drop(self, key: str) -> bool:
        async with self.locked(key):
            last_seen = self._read_last_seen()
            if key in last_seen and not self._expired(last_seen, key):
                return False  # referenced again while this waited for the build
            # Result and root go together, so no stored result names a collected path.
            (self._builds / f"{key}.json").unlink(missing_ok=True)
            (self.roots / key).unlink(missing_ok=True)
            last_seen.pop(key, None)
            self._write_last_seen(last_seen)
            return True

    async def collect_garbage(self) -> GcResult:
        async with self._gc_lock:
            dropped = [key for key in self._expired_keys() if await self._drop(key)]
            log = await nix.collect_garbage()
        summary = next((line for line in log.splitlines() if "store paths deleted" in line), "")
        logger.info(f"GC dropped {len(dropped)} skill builds; {summary}")
        return GcResult(dropped=dropped, log_tail=log)

    async def collect_garbage_every(self, interval: timedelta) -> None:
        while True:
            await asyncio.sleep(interval.total_seconds())
            await self.collect_garbage()
