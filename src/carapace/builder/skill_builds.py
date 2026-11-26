"""Which skills are built, building or failed, and the commands a built skill has.

One instance per installation: a result belongs to a build key, so users with the same skill share it. The
builder keeps every result, so this only remembers what it has seen; after a restart a lookup is enough.
The skill catalog never reads from here: it is part of the cached prompt prefix (#548).
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import httpx
from loguru import logger
from pydantic import BaseModel, ValidationError

from ..skills import SkillsFlakeError, parse_skills_lock
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
    # An MCP server from `mcpCommands`. Added after the first `mkSkill`: older pins mark none.
    mcp: bool = False


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
    key: str
    state: BuildState
    store_paths: list[str]
    commands: dict[str, SkillCommand]
    detail: str


@dataclass(frozen=True, slots=True)
class _HeadSkill:
    """A skill skills/flake.nix lists at HEAD."""

    name: str
    key: str
    # The skills/ tree at HEAD, which the builder gets as an archive.
    skills_tree: str


_BUILDING = _Outcome(state="building")


class RetryRefusedError(Exception):
    """Only a failed build of a skill at head can be retried."""


class SkillBuilds:
    def __init__(self, builder: BuilderClient | None) -> None:
        self._builder = builder
        self._results: dict[str, _Outcome] = {}
        self._running: dict[str, asyncio.Task[None]] = {}

    async def ensure_built(self, repo_dir: Path) -> list[SkillBuild]:
        """The build state of every skill skills/flake.nix lists at the head of *repo_dir*.

        A key without a result starts building in the background; this never waits for a build. A skill
        whose key did not change since its last build already has a result, so a push builds only what it touched.
        """
        builds: list[SkillBuild] = []
        for skill in await _skills_at_head(repo_dir):
            outcome = self._outcome(repo_dir, skill)
            builds.append(
                SkillBuild(
                    skill=skill.name,
                    key=skill.key,
                    state=outcome.state,
                    store_paths=outcome.store_paths,
                    commands=outcome.commands,
                    detail=outcome.detail,
                )
            )
        return builds

    async def wait_built(self, repo_dir: Path, skill: str) -> tuple[SkillBuild | None, list[SkillBuild]]:
        """*skill*'s build once it no longer runs (None for a skill skills/flake.nix does not list), and every build.

        A crashed build raises here: asking again would only start it again. The build is shared by every
        session on its key, so a waiter that is cancelled (a stopped turn) leaves it running for the others.
        """
        while True:
            builds = await self.ensure_built(repo_dir)
            build = next((build for build in builds if build.skill == skill), None)
            if build is None or build.state != "building":
                return build, builds
            with span("skill", "build wait", skill=skill):
                await asyncio.shield(self._running[build.key])

    async def sync_roots(self, repo_dirs: Iterable[Path]) -> None:
        """Tell the builder which build keys the heads of *repo_dirs* have; it may collect the others.

        Results of other keys are forgotten here, so a later lookup asks the builder again instead of
        trusting store paths that its garbage collection may have deleted by then.
        """
        if self._builder is None:
            return
        keys: set[str] = set()
        for repo_dir in repo_dirs:
            try:
                keys.update(skill.key for skill in await _skills_at_head(repo_dir))
            except RuntimeError as exc:
                # One broken repo must not stop the others' roots. Its own keys expire after the
                # grace period and are built again on the next lookup.
                logger.error(f"Cannot read the skills of {repo_dir}; not sending them to the builder: {exc}")
        await self._builder.put_roots(sorted(keys))
        for key in self._results.keys() - keys:
            del self._results[key]

    async def retry(self, repo_dir: Path, name: str) -> None:
        """Build the failed skill *name* at the head of *repo_dir* again, in the background."""
        skill = next((skill for skill in await _skills_at_head(repo_dir) if skill.name == name), None)
        if skill is None:
            raise RetryRefusedError(f"{name} is not a skill at the head of the knowledge repo")
        if self._builder is None or skill.key in self._running:
            raise RetryRefusedError(f"{name} is not waiting for a retry")
        result = self._results.get(skill.key)
        if result is None or result.state != "failed":
            state = result.state if result else "not looked up yet"
            raise RetryRefusedError(f"Only a failed build can be retried; {name} is {state}")
        del self._results[skill.key]
        self._start(self._builder, repo_dir, skill, retry=True)

    def _start(self, builder: BuilderClient, repo_dir: Path, skill: _HeadSkill, *, retry: bool = False) -> None:
        task = asyncio.create_task(self._build(builder, repo_dir, skill, retry=retry))
        task.add_done_callback(lambda done: _log_crash(done, skill))
        self._running[skill.key] = task

    def _outcome(self, repo_dir: Path, skill: _HeadSkill) -> _Outcome:
        if self._builder is None:
            return _Outcome(state="unavailable", detail="No skill builder is configured (CARAPACE_BUILDER_URL).")
        result = self._results.get(skill.key)
        if result is not None and result.state != "unavailable":
            return result
        # Unavailable is the builder's state, not the skill's: every request tries again.
        if skill.key not in self._running:
            self._start(self._builder, repo_dir, skill)
        return result or _BUILDING

    async def _build(self, builder: BuilderClient, repo_dir: Path, skill: _HeadSkill, *, retry: bool) -> None:
        try:
            self._results[skill.key] = await _build_outcome(builder, repo_dir, skill, retry=retry)
        finally:
            del self._running[skill.key]


async def _build_outcome(builder: BuilderClient, repo_dir: Path, skill: _HeadSkill, *, retry: bool) -> _Outcome:
    try:
        # A retry skips the stored result: it is the failure being retried.
        result = None if retry else await builder.get(skill.key)
        if result is None:
            try:
                archive = await _git(repo_dir, "archive", skill.skills_tree)
            except RuntimeError as exc:
                return _Outcome(state="failed", detail=str(exc))
            result = await builder.build(skill.key, skill.name, archive, retry=retry)
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        # The builder refused this skill (an archive its filter rejects, one too large): asking again won't help.
        # 401 is the server's own token, so that one is the builder's state like any outage.
        if 400 <= status < 500 and status != 401:
            return _Outcome(state="failed", detail=f"The builder refused the skill ({status}): {exc.response.text}")
        return _unavailable(skill, exc)
    except (httpx.HTTPError, BuilderSystemMismatchError) as exc:
        return _unavailable(skill, exc)
    return _read_result(result)


def _unavailable(skill: _HeadSkill, exc: Exception) -> _Outcome:
    logger.error(f"Skill {skill.name} ({skill.key}) could not be built: {type(exc).__name__}: {exc}")
    return _Outcome(state="unavailable", detail=f"The skill builder is unavailable: {type(exc).__name__}: {exc}")


def _log_crash(task: asyncio.Task[None], skill: _HeadSkill) -> None:
    if not task.cancelled() and (exc := task.exception()) is not None:
        logger.opt(exception=exc).error(f"Building skill {skill.name} ({skill.key}) crashed")


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


async def _skills_at_head(repo_dir: Path) -> list[_HeadSkill]:
    """The skills skills/flake.nix lists at HEAD, read from Git objects.

    Git and not the working tree: the keys and the archive the builder gets all describe HEAD. Without a
    usable flake there are no skills to build; the knowledge view says why.
    """
    skills_tree = await _object_id(repo_dir, "HEAD:skills")
    flake = await _object_id(repo_dir, "HEAD:skills/flake.nix")
    lock = await _object_id(repo_dir, "HEAD:skills/flake.lock")
    if not (skills_tree and flake and lock):
        return []
    try:
        listed = parse_skills_lock((await _git(repo_dir, "cat-file", "blob", lock)).decode())
    except (SkillsFlakeError, UnicodeDecodeError):
        return []
    skills: list[_HeadSkill] = []
    for skill in listed:
        # A missing directory keys as empty; the builder then reports what Nix says about it.
        directory = await _object_id(repo_dir, f"HEAD:skills/{skill.directory}") if skill.directory else ""
        skills.append(
            _HeadSkill(name=skill.name, key=build_key(skill.name, flake, lock, directory), skills_tree=skills_tree)
        )
    return skills


def build_key(skill: str, flake: str, lock: str, directory: str) -> str:
    """What a skill's build depends on: its attribute, the Git ids of skills/flake.nix and its lock, and of
    its own directory (empty for a flake from elsewhere, which the lock pins).

    Editing one local skill re-keys only that skill, so the others keep their results and stay on PATH.
    """
    # ponytail: a local skill that reads files outside its own directory is not re-keyed when they change;
    # key on the whole skills/ tree if that ever matters.
    return hashlib.sha256("\0".join([skill, flake, lock, directory]).encode()).hexdigest()


async def _object_id(repo_dir: Path, spec: str) -> str:
    """The Git object *spec* names, or empty when it does not exist."""
    process = await asyncio.create_subprocess_exec(
        "git",
        "-C",
        str(repo_dir),
        "rev-parse",
        "--verify",
        "--quiet",
        spec,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await process.communicate()
    return stdout.decode().strip() if process.returncode == 0 else ""


async def _git(repo_dir: Path, *args: str) -> bytes:
    process = await asyncio.create_subprocess_exec(
        "git", "-C", str(repo_dir), *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed in {repo_dir}: {stderr.decode(errors='replace').strip()}")
    return stdout
