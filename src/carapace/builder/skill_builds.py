"""Which skills are built, building or failed, and the commands a built skill has.

One instance per installation: a result belongs to a build key, so users with the same skill share it. The
builder keeps every result, so this only remembers what it has seen; after a restart a lookup is enough.
The skill catalog comes from here too: the names and the descriptions of the SKILL.md files the builds read.
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

from ..models.skills import SkillInfo
from ..skills import SkillDocumentError, parse_skill_document
from ..spans import span
from .client import BuilderClient, BuilderSystemMismatchError
from .models import BuildResult
from .skill_updates import SkillUpdates
from .skills_head import archive_skills, object_id, skills_flake_at_head


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
    # The skill directory in the store and what the builder read from it; also kept for a failed build.
    skill_dir: str | None = None
    skill_md: str | None = None
    skill_files: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class SkillBuild:
    skill: str
    key: str
    state: BuildState
    store_paths: list[str]
    commands: dict[str, SkillCommand]
    detail: str
    # None and empty while building, unavailable, or failed before the builder could read them.
    skill_dir: str | None = None
    skill_md: str | None = None
    skill_files: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class _HeadSkill:
    """A skill skills/flake.nix lists at HEAD."""

    name: str
    key: str
    # The skills/ tree at HEAD, which the builder gets as an archive.
    skills_tree: str


_BUILDING = _Outcome(state="building")
_NO_BUILDER = _Outcome(state="unavailable", detail="No skill builder is configured (CARAPACE_BUILDER_URL).")


class RetryRefusedError(Exception):
    """Only a failed build of a skill at head can be retried."""


class SkillBuilds:
    def __init__(self, builder: BuilderClient | None) -> None:
        self._builder = builder
        # Whether the skills have something newer: the same builder and repos, a separate question.
        self.updates = SkillUpdates(builder)
        self._results: dict[str, _Outcome] = {}
        self._running: dict[str, asyncio.Task[None]] = {}
        # The skills each repo listed at its head when last asked, for the catalog.
        self._heads: dict[Path, list[_HeadSkill]] = {}

    async def ensure_built(self, repo_dir: Path) -> list[SkillBuild]:
        """The build state of every skill skills/flake.nix lists at the head of *repo_dir*.

        A key without a result starts building in the background; this never waits for a build. A skill
        whose key did not change since its last build already has a result, so a push builds only what it touched.
        """
        heads = await _skills_at_head(repo_dir)
        self._heads[repo_dir] = heads
        return [_build(skill, self._outcome(repo_dir, skill)) for skill in heads]

    def catalog(self, repo_dir: Path) -> list[SkillInfo]:
        """Name and description of every skill *repo_dir* listed when `ensure_built` last looked, as known now.

        It starts nothing and does not wait: the catalog is part of the shared prompt prefix, which sentinel,
        memory and compaction build outside a turn. A turn refreshes it by calling `ensure_built` first.
        """
        return [_catalog_entry(skill.name, self._known(skill)) for skill in self._heads.get(repo_dir, [])]

    async def skill_file(self, build: SkillBuild, path: str) -> bytes | None:
        """A file of *build*'s skill directory; None when it has no such file or no skill directory."""
        if self._builder is None or build.skill_dir is None:
            return None
        return await self._builder.skill_file(build.key, path)

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
        result = self._known(skill)
        # Unavailable is the builder's state, not the skill's: every request tries again.
        if self._builder is not None and result.state in ("building", "unavailable") and skill.key not in self._running:
            self._start(self._builder, repo_dir, skill)
        return result

    def _known(self, skill: _HeadSkill) -> _Outcome:
        if self._builder is None:
            return _NO_BUILDER
        return self._results.get(skill.key) or _BUILDING

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
                archive = await archive_skills(repo_dir, skill.skills_tree)
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
        return _Outcome(
            state="failed",
            detail=result.log_tail,
            skill_dir=result.skill_dir,
            skill_md=result.skill_md,
            skill_files=result.skill_files,
        )
    try:
        metadata = SkillMetadata.model_validate(result.metadata)
    except ValidationError as exc:
        return _Outcome(
            state="failed",
            detail=f"The skill package has no valid passthru.carapace; build it with mkSkill. {exc}",
        )
    if result.skill_dir is None:
        return _Outcome(state="failed", detail=_NO_SKILL_DIR)
    return _Outcome(
        state="succeeded",
        store_paths=result.store_paths,
        commands=metadata.commands,
        skill_dir=result.skill_dir,
        skill_md=result.skill_md,
        skill_files=result.skill_files,
    )


_NO_SKILL_DIR = (
    "The skill package names no skill directory: its Carapace helpers are older than mkSkill's src. "
    "Pass src = ./. to mkSkill and update the carapace input: nix flake update carapace --flake ./skills"
)


def _build(skill: _HeadSkill, outcome: _Outcome) -> SkillBuild:
    return SkillBuild(
        skill=skill.name,
        key=skill.key,
        state=outcome.state,
        store_paths=outcome.store_paths,
        commands=outcome.commands,
        detail=outcome.detail,
        skill_dir=outcome.skill_dir,
        skill_md=outcome.skill_md,
        skill_files=outcome.skill_files,
    )


def _catalog_entry(name: str, outcome: _Outcome) -> SkillInfo:
    """The skill under its attribute name, with the description of its SKILL.md or why there is none yet."""
    if outcome.skill_md is None:
        description = {
            "building": "Being built; its description follows once it is. read_skill waits for the build.",
            # Fixed text, not the error: the catalog is part of the cached prompt prefix.
            "unavailable": "Not available: the skill builder cannot be reached. read_skill shows why.",
        }.get(outcome.state, "BROKEN, its build has no SKILL.md; read_skill shows why.")
        return SkillInfo(name=name, description=description)
    try:
        document = parse_skill_document(outcome.skill_md, fallback_name=name)
        document.carapace_config()
    except SkillDocumentError as exc:
        # Listed rather than dropped: the agent has to see the skill is broken to fix it.
        return SkillInfo(name=name, description=f"BROKEN, cannot be used until its SKILL.md is fixed: {exc}")
    return SkillInfo(name=name, description=document.description)


async def _skills_at_head(repo_dir: Path) -> list[_HeadSkill]:
    """The skills skills/flake.nix lists at HEAD, each with its build key."""
    head = await skills_flake_at_head(repo_dir)
    if head is None:
        return []
    skills: list[_HeadSkill] = []
    for skill in head.skills:
        # A missing directory keys as empty; the builder then reports what Nix says about it.
        directory = await object_id(repo_dir, f"HEAD:skills/{skill.directory}") if skill.directory else ""
        key = build_key(skill.name, head.flake, head.lock, directory)
        skills.append(_HeadSkill(name=skill.name, key=key, skills_tree=head.tree))
    return skills


def build_key(skill: str, flake: str, lock: str, directory: str) -> str:
    """What a skill's build depends on: its attribute, the Git ids of skills/flake.nix and its lock, and of
    its own directory (empty for a flake from elsewhere, which the lock pins).

    Editing one local skill re-keys only that skill, so the others keep their results and stay on PATH.
    """
    # ponytail: a local skill that reads files outside its own directory is not re-keyed when they change;
    # key on the whole skills/ tree if that ever matters.
    return hashlib.sha256("\0".join([skill, flake, lock, directory]).encode()).hexdigest()
