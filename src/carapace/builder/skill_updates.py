"""Whether a skill has something newer than skills/flake.lock pins: an upstream update or a stale local lock.

One check covers both: the builder runs `nix flake update <skill>` on a copy of skills/ and returns the
lock it would write, and the skill's part of that lock is compared with the repo's. Results live in
memory per knowledge repo; a restart checks again. They never reach the skill catalog, which is part of
the cached prompt prefix (docs/persistent-context.md).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import httpx
from loguru import logger

from .client import BuilderClient, BuilderSystemMismatchError
from .skills_head import archive_skills, skills_flake_at_head

type UpdateState = Literal["current", "available", "outdated", "failed"]


@dataclass(frozen=True, slots=True)
class SkillUpdate:
    # current: nothing newer. available: an external skill's upstream moved. outdated: a local skill's
    # inputs or lock changed without `nix flake update <name>`. failed: the check could not tell.
    state: UpdateState
    # What an update would lock, for an available one.
    available_rev: str | None = None
    available_at: datetime | None = None
    # How to fix an outdated skill, or why the check failed.
    detail: str = ""


@dataclass(frozen=True, slots=True)
class UpdateCheck:
    # The skills/ tree at HEAD that was checked: a push makes the result stale until the next check.
    skills_tree: str
    checked_at: datetime
    skills: dict[str, SkillUpdate]
    # Why nothing could be checked (no builder, builder unreachable); empty otherwise.
    error: str = ""


def compare(name: str, current: dict[str, Any], updated: dict[str, Any]) -> SkillUpdate:
    """What changed for input *name* between the repo's lock and the lock an update of it would write."""
    before, after = _resolved(current, name), _resolved(updated, name)
    if before == after:
        return SkillUpdate(state="current")
    if after["locked"]["type"] == "path":
        return SkillUpdate(
            state="outdated",
            detail=f"Its inputs or flake.lock changed since skills/flake.lock was written: run "
            f"`nix flake update {name} --flake ./skills` and commit skills/flake.lock.",
        )
    modified = after["locked"].get("lastModified")
    return SkillUpdate(
        state="available",
        available_rev=after["locked"].get("rev"),
        available_at=datetime.fromtimestamp(modified, UTC) if modified is not None else None,
    )


def _resolved(lock: dict[str, Any], name: str) -> dict[str, Any]:
    """Input *name* with its own inputs nested in, so two locks compare whatever their nodes are called."""
    nodes = lock["nodes"]

    def node(node_id: str) -> dict[str, Any]:
        entry = nodes[node_id]
        inputs = {
            # A follows (a list of names) stays as written: the input it names is checked on its own.
            key: target if isinstance(target, list) else node(target)
            for key, target in entry.get("inputs", {}).items()
        }
        return {"locked": entry["locked"], "original": entry.get("original"), "inputs": inputs}

    return node(nodes[lock["root"]]["inputs"][name])


class SkillUpdates:
    def __init__(self, builder: BuilderClient | None) -> None:
        self._builder = builder
        self._checks: dict[Path, UpdateCheck] = {}
        self._running: dict[Path, asyncio.Task[None]] = {}

    def latest(self, repo_dir: Path) -> UpdateCheck | None:
        return self._checks.get(repo_dir)

    def running(self, repo_dir: Path) -> bool:
        return repo_dir in self._running

    def start(self, repo_dir: Path) -> None:
        """Check *repo_dir*'s skills in the background, unless a check already runs for it."""
        if repo_dir in self._running:
            return
        task = asyncio.create_task(self._check(repo_dir))
        task.add_done_callback(lambda done: _log_crash(done, repo_dir))
        self._running[repo_dir] = task

    async def wait(self, repo_dir: Path) -> None:
        if (task := self._running.get(repo_dir)) is not None:
            await asyncio.shield(task)

    async def check_every(self, interval: timedelta, repo_dirs: Callable[[], Iterable[Path]]) -> None:
        """Check every repo now and then once per *interval*."""
        while True:
            for repo_dir in repo_dirs():
                self.start(repo_dir)
            await asyncio.sleep(interval.total_seconds())

    async def _check(self, repo_dir: Path) -> None:
        try:
            if (check := await self._run(repo_dir)) is not None:
                self._checks[repo_dir] = check
        finally:
            del self._running[repo_dir]

    async def _run(self, repo_dir: Path) -> UpdateCheck | None:
        head = await skills_flake_at_head(repo_dir)
        if head is None:
            self._checks.pop(repo_dir, None)
            return None
        now = datetime.now(UTC)
        if self._builder is None:
            return UpdateCheck(head.tree, now, {}, error="No skill builder is configured (CARAPACE_BUILDER_URL).")
        names = [skill.name for skill in head.skills]
        try:
            result = await self._builder.check_updates(await archive_skills(repo_dir, head.tree), names)
        except (httpx.HTTPError, BuilderSystemMismatchError) as exc:
            logger.warning(f"Cannot check the skills of {repo_dir} for updates: {type(exc).__name__}: {exc}")
            return UpdateCheck(head.tree, now, {}, error=f"The skill builder is unavailable: {exc}")
        current = json.loads(head.lock_text)
        skills: dict[str, SkillUpdate] = {}
        for name in names:
            update = result.inputs.get(name)
            if update is None or update.lock is None:
                log = update.log_tail if update else "the builder did not answer for it"
                skills[name] = SkillUpdate(state="failed", detail=log)
            else:
                skills[name] = compare(name, current, json.loads(update.lock))
        return UpdateCheck(head.tree, now, skills)


def _log_crash(task: asyncio.Task[None], repo_dir: Path) -> None:
    if not task.cancelled() and (exc := task.exception()) is not None:
        logger.opt(exception=exc).error(f"Checking the skills of {repo_dir} for updates crashed")
