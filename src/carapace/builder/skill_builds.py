"""Which skills are built, building or failed, and the commands a built skill has.

One instance per installation: a result belongs to a build key, so users with the same skill share it. The
builder keeps every result, so this only remembers what it has seen; after a restart a lookup is enough.
The skill catalog comes from here too: the names and the descriptions of the SKILL.md files the builds read.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import httpx
from loguru import logger
from pydantic import BaseModel, ValidationError

from ..models.skills import SkillInfo
from ..skills import SkillDocumentError, parse_skill_document
from ..span_names import SKILL_BUILD_WAIT_SPAN
from ..spans import span
from .client import BuilderClient, BuilderSystemMismatchError
from .models import BuildResult, FetchCredential, SkillDeclarations
from .skill_updates import FetchCredentials, SkillUpdates, no_fetch_credentials
from .skills_head import archive_skills, object_id, skills_flake_at_head


class SkillNeeds(BaseModel):
    """What a command needs from outside the sandbox, resolved for this instance's settings."""

    domains: list[str]
    # Credential slot (the environment variable) to the vault path skills/config.json binds; None while unbound.
    credentials: dict[str, str | None]
    # OAuth slot to the vault path of its entry, whose access token the command fetches; None while unbound.
    oauth: dict[str, str | None]
    tunnels: list[str]


class SkillCommand(BaseModel):
    description: str
    needs: SkillNeeds
    # An MCP server from `mcpCommands`.
    mcp: bool


type SettingValue = str | int | bool


class SkillManifest(BaseModel):
    """`manifests.<system>.<skill>` of skills/flake.nix, as `skillsFlake` writes it (docs/skill-flakes.md).

    A skill that skills/config.json turns off has only `enable`.
    """

    enable: bool
    settings: dict[str, SettingValue] = {}
    commands: dict[str, SkillCommand] = {}


type BuildState = Literal["building", "succeeded", "failed", "unavailable"]


@dataclass(frozen=True, slots=True)
class _Outcome:
    state: BuildState
    store_paths: list[str] = field(default_factory=list)
    commands: dict[str, SkillCommand] = field(default_factory=dict)
    # Why a build failed or is unavailable: the builder's log tail, or what went wrong before it.
    detail: str = ""
    # False for a skill skills/config.json turns off: it counts as not listed.
    enabled: bool = True
    settings: dict[str, SettingValue] = field(default_factory=dict)
    # The skill directory in the store and what the builder read from it; also kept for a failed build.
    skill_dir: str | None = None
    skill_md: str | None = None
    skill_files: list[str] = field(default_factory=list)
    declarations: SkillDeclarations | None = None


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
    enabled: bool = True
    # This instance's values, which a command gets as environment variables (`cgate request --command`).
    settings: dict[str, SettingValue] = field(default_factory=dict)
    # What the skill declares, for the Knowledge view to offer: also there for a failed or turned-off build,
    # None while building or when the package did not evaluate.
    declarations: SkillDeclarations | None = None

    def unbound(self, command: str) -> list[str]:
        """The credential slots *command* needs that skills/config.json does not bind."""
        needs = self.commands[command].needs
        return sorted(slot for slot, path in (needs.credentials | needs.oauth).items() if path is None)


@dataclass(frozen=True, slots=True)
class _HeadSkill:
    """A skill skills/flake.nix lists at HEAD."""

    name: str
    key: str
    # The skills/ tree at HEAD, which the builder gets part of as an archive.
    skills_tree: str
    # The skill's directory below skills/; None for a flake from elsewhere.
    directory: str | None
    # Whether skills/ has a config.json, which the builder gets along for the manifest.
    config: bool


_BUILDING = _Outcome(state="building")
# How long a refresh waits for the builder's answer to its lookups before the catalog goes on without them.
_LOOKUP_WAIT_SECONDS = 5.0
_NO_BUILDER = _Outcome(state="unavailable", detail="No skill builder is configured (CARAPACE_BUILDER_URL).")


class RetryRefusedError(Exception):
    """Only a failed build of a skill at head can be retried."""


class SkillBuilds:
    def __init__(
        self, builder: BuilderClient | None, fetch_credentials: FetchCredentials = no_fetch_credentials
    ) -> None:
        self._builder = builder
        self._fetch_credentials = fetch_credentials
        # Whether the skills have something newer: the same builder and repos, a separate question.
        self.updates = SkillUpdates(builder, fetch_credentials)
        self._results: dict[str, _Outcome] = {}
        self._running: dict[str, asyncio.Task[None]] = {}
        # The skills each repo listed at its head when last asked, for the catalog, and that head's commit.
        self._heads: dict[Path, list[_HeadSkill]] = {}
        self._head_commits: dict[Path, str] = {}
        # Set once the builder said whether it has a running key's result already, before any build.
        self._looked_up: dict[str, asyncio.Event] = {}
        # The last succeeded build of each (repo, attribute), used while its key builds or failed.
        self._last_succeeded: dict[tuple[Path, str], SkillBuild] = {}
        # The last declarations each (repo, attribute) had, from whatever state: what the form offers while
        # its key evaluates again, even for a skill that never succeeded.
        self._last_declarations: dict[tuple[Path, str], SkillDeclarations] = {}

    async def ensure_built(self, repo_dir: Path) -> list[SkillBuild]:
        """The build state of every skill skills/flake.nix lists at the head of *repo_dir*.

        A key without a result starts building in the background; this never waits for a build. A skill
        whose key did not change since its last build already has a result, so a push builds only what it touched.
        """
        heads = await self._skills_at_head(repo_dir)
        if heads:
            self.updates.check_if_stale(repo_dir, heads[0].skills_tree)
        builds = [_build(skill, self._outcome(repo_dir, skill)) for skill in heads]
        self._remember_succeeded(repo_dir, builds)
        return builds

    async def installable(self, repo_dir: Path) -> list[SkillBuild]:
        """What the session profile should hold: each skill's build at head, or its last succeeded one.

        A change to skills/flake.nix or its lock re-keys every skill; without the fallback, every command
        would leave PATH until its rebuild is done, and a failed rebuild would keep it off.
        """
        usable = [self._usable(repo_dir, build) for build in await self.ensure_built(repo_dir)]
        return [build for build in usable if build.enabled]

    async def command_build(self, repo_dir: Path, store_path: str, command: str) -> SkillBuild | None:
        """The installable build a wrapper belongs to: the one whose package is *store_path* (its `@out@`), else
        the one with a command named *command*. None when no installable build has that command.

        A package built in the workspace (`nix shell path:./skills/<name>`) is not installed; command names are
        unique on PATH, so it gets the settings and needs of the committed version of its command. That grants
        nothing new: the sandbox can run the installed command anyway, and whatever leaves the sandbox still goes
        through the review of those needs. The same holds for anything else the answer carries (credentials).
        """
        builds = [build for build in await self.installable(repo_dir) if command in build.commands]
        return next((build for build in builds if store_path in build.store_paths), builds[0] if builds else None)

    def declarations(self, repo_dir: Path, build: SkillBuild) -> SkillDeclarations | None:
        """What *build*'s skill declares, or what it last declared while it re-keys.

        A config.json change re-keys every skill: without the fallback, every form would empty out until
        the manifests are evaluated again.
        """
        return build.declarations or self._last_declarations.get((repo_dir, build.skill))

    async def refresh(self, repo_dir: Path) -> None:
        """`ensure_built`, then wait briefly until the builder said which of the new keys it built before.

        After a restart nothing is known, and a lookup is one request where a build may take minutes: without
        the wait, the catalog would show every skill as being built and change again on the next turn.
        """
        builds = await self.ensure_built(repo_dir)
        lookups = [self._looked_up[build.key].wait() for build in builds if build.key in self._looked_up]
        # A slow builder only leaves those skills at what the catalog knew of them.
        with contextlib.suppress(TimeoutError):
            async with asyncio.timeout(_LOOKUP_WAIT_SECONDS):
                await asyncio.gather(*lookups)
        self._remember_succeeded(repo_dir, [_build(skill, self._known(skill)) for skill in self._heads[repo_dir]])

    def catalog(self, repo_dir: Path) -> list[SkillInfo]:
        """Name and description of every skill *repo_dir* listed when `ensure_built` last looked, as known now.

        It starts nothing and does not wait: the catalog is part of the shared prompt prefix, which sentinel,
        memory and compaction build outside a turn. A turn refreshes it first (`refresh`).
        """
        heads = self._heads.get(repo_dir, [])
        return [_catalog_entry(skill.name, shown) for skill in heads if (shown := self._shown(repo_dir, skill)).enabled]

    def readable(self, repo_dir: Path, name: str) -> SkillBuild | None:
        """The build of *name* whose skill directory the catalog and the sentinel read.

        That is the build at head once it has one, and until then the last succeeded build of this attribute:
        a changed skill keeps its description and files until the new ones are there, instead of dropping to
        "being built" and back. None for a skill whose skill directory was never read, and for one that is off.
        """
        skill = next((skill for skill in self._heads.get(repo_dir, []) if skill.name == name), None)
        if skill is None:
            return None
        shown = self._shown(repo_dir, skill)
        return shown if shown.enabled and shown.skill_dir is not None else None

    def _shown(self, repo_dir: Path, skill: _HeadSkill) -> SkillBuild:
        """The build at head once it has a skill directory or is off, until then the last succeeded build.

        So a skill that is off stays off while a config change re-keys it, like a changed skill keeps its
        description until the new one is read.
        """
        build = _build(skill, self._known(skill))
        if build.skill_dir is not None or not build.enabled:
            return build
        return self._last_succeeded.get((repo_dir, skill.name), build)

    async def skill_file(self, build: SkillBuild, path: str) -> bytes | None:
        """A file of *build*'s skill directory; None when it has no such file or no skill directory."""
        if self._builder is None or build.skill_dir is None:
            return None
        return await self._builder.skill_file(build.key, path)

    async def wait_built(self, repo_dir: Path, skill: str) -> SkillBuild | None:
        """*skill*'s build once it no longer runs; None for a skill skills/flake.nix does not list.

        A crashed build raises here: asking again would only start it again. The build is shared by every
        session on its key, so a waiter that is cancelled (a stopped turn) leaves it running for the others.
        """
        while True:
            builds = await self.ensure_built(repo_dir)
            build = next((build for build in builds if build.skill == skill), None)
            if build is None or build.state != "building":
                return build
            with span("skill", SKILL_BUILD_WAIT_SPAN, skill=skill):
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

    async def _skills_at_head(self, repo_dir: Path) -> list[_HeadSkill]:
        # One git call while the head stays: every turn asks, and the skills are a function of the commit.
        commit = await object_id(repo_dir, "HEAD")
        if self._head_commits.get(repo_dir) != commit:
            # Without a commit there is nothing to list.
            self._heads[repo_dir] = await _skills_at_head(repo_dir) if commit else []
            self._head_commits[repo_dir] = commit
        return self._heads[repo_dir]

    def _remember_succeeded(self, repo_dir: Path, builds: list[SkillBuild]) -> None:
        listed = {build.skill for build in builds}
        for repo, name in [key for key in self._last_succeeded if key[0] == repo_dir and key[1] not in listed]:
            del self._last_succeeded[(repo, name)]
        for repo, name in [key for key in self._last_declarations if key[0] == repo_dir and key[1] not in listed]:
            del self._last_declarations[(repo, name)]
        for build in builds:
            if build.state == "succeeded":
                self._last_succeeded[(repo_dir, build.skill)] = build
            if build.declarations is not None:
                self._last_declarations[(repo_dir, build.skill)] = build.declarations

    def _usable(self, repo_dir: Path, build: SkillBuild) -> SkillBuild:
        if build.state == "succeeded":
            return build
        return self._last_succeeded.get((repo_dir, build.skill), build)

    def _start(self, builder: BuilderClient, repo_dir: Path, skill: _HeadSkill, *, retry: bool = False) -> None:
        self._looked_up[skill.key] = asyncio.Event()
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
        looked_up = self._looked_up[skill.key]
        try:
            credential = self._fetch_credentials(repo_dir)
            self._results[skill.key] = await _build_outcome(
                builder, repo_dir, skill, credential, looked_up, retry=retry
            )
        finally:
            looked_up.set()
            del self._looked_up[skill.key]
            del self._running[skill.key]


async def _build_outcome(
    builder: BuilderClient,
    repo_dir: Path,
    skill: _HeadSkill,
    credential: FetchCredential | None,
    looked_up: asyncio.Event,
    *,
    retry: bool,
) -> _Outcome:
    try:
        # A retry skips the stored result: it is the failure being retried.
        try:
            result = None if retry else await builder.get(skill.key)
        finally:
            looked_up.set()
        if result is None:
            try:
                # Only what the key covers: results are shared between users with the same key, so a skill
                # that reads another directory of skills/ must fail rather than build from someone's tree.
                paths = [
                    "flake.nix",
                    "flake.lock",
                    *(["config.json"] if skill.config else []),
                    *([skill.directory] if skill.directory else []),
                ]
                archive = await archive_skills(repo_dir, skill.skills_tree, *paths)
            except RuntimeError as exc:
                return _Outcome(state="failed", detail=str(exc))
            result = await builder.build(skill.key, skill.name, archive, credential, retry=retry)
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
    declarations = result.declarations
    if result.state == "failed":
        return _Outcome(
            state="failed",
            detail=result.log_tail,
            skill_dir=result.skill_dir,
            skill_md=result.skill_md,
            skill_files=result.skill_files,
            declarations=declarations,
        )
    try:
        manifest = SkillManifest.model_validate(result.metadata)
    except ValidationError as exc:
        detail = f"The skill has no valid manifest; see docs/skill-flakes.md. {exc}"
        return _Outcome(state="failed", detail=detail, declarations=declarations)
    if not manifest.enable:
        return _Outcome(
            state="succeeded", enabled=False, detail="Turned off in skills/config.json.", declarations=declarations
        )
    if result.skill_dir is None:
        return _Outcome(state="failed", detail=_NO_SKILL_DIR, declarations=declarations)
    return _Outcome(
        declarations=declarations,
        state="succeeded",
        store_paths=result.store_paths,
        commands=manifest.commands,
        settings=manifest.settings,
        skill_dir=result.skill_dir,
        skill_md=result.skill_md,
        skill_files=result.skill_files,
    )


def unbound_slot_hint(skill: str, slots: list[str]) -> str:
    """Why a command cannot run yet, and the `skills/config.json` entry that fixes it."""
    example = json.dumps({skill: {"credentials": {slot: "<backend>/<id>" for slot in slots}}})
    if len(slots) == 1:
        problem = f"credential slot {slots[0]} is not bound; bind it to a password-manager entry"
    else:
        problem = f"credential slots {', '.join(slots)} are not bound; bind them to password-manager entries"
    return f"{skill}: {problem} in skills/config.json: {example}"


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
        enabled=outcome.enabled,
        settings=outcome.settings,
        declarations=outcome.declarations,
    )


def _catalog_entry(name: str, build: SkillBuild) -> SkillInfo:
    """The skill under its attribute name, with the description of its SKILL.md or why there is none yet."""
    if build.skill_md is None:
        description = {
            "building": "Being built; its description follows once it is. read_skill waits for the build.",
            # Fixed text, not the error: the catalog is part of the cached prompt prefix.
            "unavailable": "Not available: the skill builder cannot be reached. read_skill shows why.",
        }.get(build.state, "BROKEN, its build has no SKILL.md; read_skill shows why.")
        return SkillInfo(name=name, description=description)
    try:
        document = parse_skill_document(build.skill_md, fallback_name=name)
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
        # A missing directory keys as empty; archiving it then fails and says why.
        directory = await object_id(repo_dir, f"{head.tree}:{skill.directory}") if skill.directory else ""
        key = build_key(skill.name, head.flake, head.lock, head.config, directory)
        local = str(skill.directory) if skill.directory is not None else None
        skills.append(
            _HeadSkill(name=skill.name, key=key, skills_tree=head.tree, directory=local, config=bool(head.config))
        )
    return skills


def build_key(skill: str, flake: str, lock: str, config: str, directory: str) -> str:
    """What a skill's build depends on: its attribute, the Git ids of skills/flake.nix, its lock and
    skills/config.json (empty without one), and of its own directory (empty for a flake from elsewhere,
    which the lock pins).

    Editing one local skill re-keys only that skill, so the others keep their results and stay on PATH.
    A change to config.json re-keys every skill, but builds nothing new: the packages do not depend on it,
    only the manifests the builder evaluates again.
    """
    # Exactly what the builder gets (`_build_outcome` archives these paths), so a key cannot hide a change.
    # A config.json change re-evaluates every manifest; key on each skill's entry if that ever gets slow.
    return hashlib.sha256("\0".join([skill, flake, lock, config, directory]).encode()).hexdigest()
