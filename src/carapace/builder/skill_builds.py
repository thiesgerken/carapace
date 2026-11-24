"""Which skill trees are built, building or failed, and the commands a built skill has.

One instance per installation: a result belongs to a tree hash, so users with the same skill share it. The
builder keeps every result, so this only remembers what it has seen; after a restart a lookup is enough.
The skill catalog never reads from here: it is part of the cached prompt prefix (#548).
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import httpx
from loguru import logger
from pydantic import BaseModel, ValidationError

from ..skills import SkillDocumentError, parse_skill_document
from ..spans import span
from .client import BuilderClient, BuilderSystemMismatchError
from .models import BuildResult


class SkillNeeds(BaseModel):
    """What a command declared it needs from outside the sandbox, resolved by `mkSkill`."""

    domains: list[str]
    credentials: dict[str, str]
    tunnels: list[str]
    # Added after the first `mkSkill`: a skill pinning an older Carapace has none.
    oauth: list[str] = []


class SkillCommand(BaseModel):
    description: str
    needs: SkillNeeds


class SkillMetadata(BaseModel):
    """`passthru.carapace` of a skill package, as `mkSkill` writes it (docs/skill-flakes.md)."""

    name: str
    commands: dict[str, SkillCommand]


type BuildState = Literal["building", "succeeded", "failed", "unavailable"]


@dataclass(frozen=True, slots=True)
class _Outcome:
    state: BuildState
    store_paths: list[str] = field(default_factory=list)
    commands: dict[str, SkillCommand] = field(default_factory=dict)
    # Why a build failed or is unavailable: the builder's log tail, or what went wrong before it.
    detail: str = ""


@dataclass(frozen=True, slots=True)
class SkillBuild:
    skill: str
    tree: str
    state: BuildState
    store_paths: list[str]
    commands: dict[str, SkillCommand]
    detail: str


@dataclass(frozen=True, slots=True)
class _FlakeSkill:
    name: str
    tree: str
    # Set when the SKILL.md cannot be read, so whether it is disabled is unknown: not built.
    error: str = ""


_BUILDING = _Outcome(state="building")


class RetryRefusedError(Exception):
    """Only a failed build of a flake skill at head can be retried."""


class SkillBuilds:
    def __init__(self, builder: BuilderClient | None) -> None:
        self._builder = builder
        self._results: dict[str, _Outcome] = {}
        self._running: dict[str, asyncio.Task[None]] = {}

    async def ensure_built(self, repo_dir: Path) -> list[SkillBuild]:
        """The build state of every enabled flake skill at the head of *repo_dir*.

        A tree without a result starts building in the background; this never waits for a build. A tree
        that did not change since its last build already has a result, so a push builds only what it touched.
        """
        builds: list[SkillBuild] = []
        for skill in await _flake_skills_at_head(repo_dir):
            outcome = self._outcome(repo_dir, skill)
            builds.append(
                SkillBuild(
                    skill=skill.name,
                    tree=skill.tree,
                    state=outcome.state,
                    store_paths=outcome.store_paths,
                    commands=outcome.commands,
                    detail=outcome.detail,
                )
            )
        return builds

    async def wait_built(self, repo_dir: Path, skill: str) -> tuple[SkillBuild | None, list[SkillBuild]]:
        """*skill*'s build once it no longer runs (None for a skill without a flake), and every build.

        A crashed build raises here: asking again would only start it again. The build is shared by every
        session on its tree, so a waiter that is cancelled (a stopped turn) leaves it running for the others.
        """
        while True:
            builds = await self.ensure_built(repo_dir)
            build = next((build for build in builds if build.skill == skill), None)
            if build is None or build.state != "building":
                return build, builds
            with span("skill", "build wait", skill=skill):
                await asyncio.shield(self._running[build.tree])

    async def sync_roots(self, repo_dirs: Iterable[Path]) -> None:
        """Tell the builder which trees the heads of *repo_dirs* reference; it may collect the others.

        Results of other trees are forgotten here, so a later lookup asks the builder again instead of
        trusting store paths that its garbage collection may have deleted by then.
        """
        if self._builder is None:
            return
        trees: set[str] = set()
        for repo_dir in repo_dirs:
            try:
                trees.update(skill.tree for skill in await _flake_skills_at_head(repo_dir))
            except RuntimeError as exc:
                # One broken repo must not stop the others' roots. Its own trees expire after the
                # grace period and are built again on the next lookup.
                logger.error(f"Cannot read the skill trees of {repo_dir}; not sending them to the builder: {exc}")
        await self._builder.put_roots(sorted(trees))
        for tree in self._results.keys() - trees:
            del self._results[tree]

    async def retry(self, repo_dir: Path, name: str) -> None:
        """Build the failed skill *name* at the head of *repo_dir* again, in the background."""
        skill = next((skill for skill in await _flake_skills_at_head(repo_dir) if skill.name == name), None)
        if skill is None:
            raise RetryRefusedError(f"{name} is not a flake skill at the head of the knowledge repo")
        if skill.error:
            raise RetryRefusedError(f"{name} cannot be built until its SKILL.md is fixed: {skill.error}")
        if self._builder is None or skill.tree in self._running:
            raise RetryRefusedError(f"{name} is not waiting for a retry")
        result = self._results.get(skill.tree)
        if result is None or result.state != "failed":
            state = result.state if result else "not looked up yet"
            raise RetryRefusedError(f"Only a failed build can be retried; {name} is {state}")
        del self._results[skill.tree]
        self._start(self._builder, repo_dir, skill.tree, retry=True)

    def _start(self, builder: BuilderClient, repo_dir: Path, tree: str, *, retry: bool = False) -> None:
        task = asyncio.create_task(self._build(builder, repo_dir, tree, retry=retry))
        task.add_done_callback(lambda done: _log_crash(done, tree))
        self._running[tree] = task

    def _outcome(self, repo_dir: Path, skill: _FlakeSkill) -> _Outcome:
        if skill.error:
            return _Outcome(state="failed", detail=skill.error)
        if self._builder is None:
            return _Outcome(state="unavailable", detail="No skill builder is configured (CARAPACE_BUILDER_URL).")
        result = self._results.get(skill.tree)
        if result is not None and result.state != "unavailable":
            return result
        # Unavailable is the builder's state, not the skill's: every request tries again.
        if skill.tree not in self._running:
            self._start(self._builder, repo_dir, skill.tree)
        return result or _BUILDING

    async def _build(self, builder: BuilderClient, repo_dir: Path, tree: str, *, retry: bool) -> None:
        try:
            self._results[tree] = await _build_outcome(builder, repo_dir, tree, retry=retry)
        finally:
            del self._running[tree]


async def _build_outcome(builder: BuilderClient, repo_dir: Path, tree: str, *, retry: bool) -> _Outcome:
    try:
        # A retry skips the stored result: it is the failure being retried.
        result = None if retry else await builder.get(tree)
        if result is None:
            try:
                archive = await _git(repo_dir, "archive", tree)
            except RuntimeError as exc:
                return _Outcome(state="failed", detail=str(exc))
            result = await builder.build(tree, archive, retry=retry)
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        # The builder refused this skill (an archive its filter rejects, one too large): asking again won't help.
        # 401 is the server's own token, so that one is the builder's state like any outage.
        if 400 <= status < 500 and status != 401:
            return _Outcome(state="failed", detail=f"The builder refused the skill ({status}): {exc.response.text}")
        return _unavailable(tree, exc)
    except (httpx.HTTPError, BuilderSystemMismatchError) as exc:
        return _unavailable(tree, exc)
    return _read_result(result)


def _unavailable(tree: str, exc: Exception) -> _Outcome:
    logger.error(f"Skill tree {tree} could not be built: {type(exc).__name__}: {exc}")
    return _Outcome(state="unavailable", detail=f"The skill builder is unavailable: {type(exc).__name__}: {exc}")


def _log_crash(task: asyncio.Task[None], tree: str) -> None:
    if not task.cancelled() and (exc := task.exception()) is not None:
        logger.opt(exception=exc).error(f"Building skill tree {tree} crashed")


def _read_result(result: BuildResult) -> _Outcome:
    if result.state == "failed":
        return _Outcome(state="failed", detail=result.log_tail)
    try:
        metadata = SkillMetadata.model_validate(result.metadata)
    except ValidationError as exc:
        return _Outcome(
            state="failed",
            detail=f"The skill package has no valid passthru.carapace; build it with mkSkill. {exc}",
        )
    return _Outcome(state="succeeded", store_paths=result.store_paths, commands=metadata.commands)


async def _flake_skills_at_head(repo_dir: Path) -> list[_FlakeSkill]:
    """Skill directories at HEAD that have a flake.nix and are not disabled, read from Git objects.

    Git and not the working tree: the tree hash, the archive and the files checked here all belong to HEAD.
    """
    if not await _git_ok(repo_dir, "rev-parse", "--verify", "--quiet", "HEAD"):
        return []
    skills: list[_FlakeSkill] = []
    for name, tree in _entries(await _git(repo_dir, "ls-tree", "-z", "HEAD", "skills/"), "tree"):
        files = {path for path, _ in _entries(await _git(repo_dir, "ls-tree", "-z", tree), "blob")}
        if not {"SKILL.md", "flake.nix"} <= files:
            continue
        try:
            text = (await _git(repo_dir, "cat-file", "blob", f"{tree}:SKILL.md")).decode()
            document = parse_skill_document(text, fallback_name=name)
        except (SkillDocumentError, UnicodeDecodeError) as exc:
            skills.append(_FlakeSkill(name=name, tree=tree, error=f"skills/{name}/SKILL.md: {exc}"))
            continue
        if not document.disabled:
            skills.append(_FlakeSkill(name=name, tree=tree))
    return skills


def _entries(listing: bytes, kind: str) -> list[tuple[str, str]]:
    """(name, object hash) of the `ls-tree -z` entries of *kind*."""
    entries: list[tuple[str, str]] = []
    for entry in listing.decode().split("\0"):
        if not entry:
            continue
        meta, path = entry.split("\t", 1)
        _mode, object_type, object_hash = meta.split()
        if object_type == kind:
            entries.append((path.rsplit("/", 1)[-1], object_hash))
    return entries


async def _git(repo_dir: Path, *args: str) -> bytes:
    process = await asyncio.create_subprocess_exec(
        "git", "-C", str(repo_dir), *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed in {repo_dir}: {stderr.decode(errors='replace').strip()}")
    return stdout


async def _git_ok(repo_dir: Path, *args: str) -> bool:
    process = await asyncio.create_subprocess_exec(
        "git", "-C", str(repo_dir), *args, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
    )
    return await process.wait() == 0
