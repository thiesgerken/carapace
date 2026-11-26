from __future__ import annotations

import json
import posixpath
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlencode

import yaml
from loguru import logger
from pydantic import ValidationError

from .models.skills import SkillCarapaceConfig, SkillInfo


class SkillDocumentError(ValueError):
    """A SKILL.md whose frontmatter cannot be read as a skill declaration."""


class SkillsFlakeError(ValueError):
    """`skills/flake.nix` or its lock is missing or unreadable, so the repo has no skills."""


# The inputs of skills/flake.nix that every skill follows; all other inputs are skills.
_SHARED_INPUTS = frozenset({"nixpkgs", "carapace"})
_FIX = "List the skills in skills/flake.nix and run `nix flake lock ./skills` (docs/skill-flakes.md)."


@dataclass(frozen=True, slots=True)
class ListedSkill:
    """An input of skills/flake.nix: a skill, named by its attribute."""

    name: str
    # Below skills/, for a `path:` input; None for a flake from elsewhere.
    directory: PurePosixPath | None
    # Where it comes from: `./<dir>` for a local skill, the flake reference it was written as otherwise.
    origin: str
    # The commit and its time the lock pins; None for a local skill, which the lock does not pin.
    locked_rev: str | None
    locked_at: datetime | None


def parse_skills_lock(text: str) -> list[ListedSkill]:
    """The skills `skills/flake.lock` lists, sorted by name.

    The lock and not the flake: the server never evaluates Nix, and the lock holds every input the builder builds.
    """
    try:
        lock = json.loads(text)
        nodes = lock["nodes"]
        inputs = nodes[lock["root"]].get("inputs", {})
        skills = [
            _listed_skill(name, nodes[node]) for name, node in sorted(inputs.items()) if name not in _SHARED_INPUTS
        ]
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise SkillsFlakeError(f"skills/flake.lock is not a flake lock file ({exc}). {_FIX}") from exc
    return skills


def _listed_skill(name: str, node: dict[str, Any]) -> ListedSkill:
    locked = node["locked"]
    directory = _local_directory(name, node)
    modified = locked.get("lastModified")
    return ListedSkill(
        name=name,
        directory=directory,
        origin=f"./{directory}" if directory is not None else flake_ref(node.get("original", locked)),
        locked_rev=locked.get("rev"),
        locked_at=datetime.fromtimestamp(modified, UTC) if modified is not None else None,
    )


def flake_ref(attributes: dict[str, Any]) -> str:
    """The flake reference a lock entry's attributes stand for, e.g. `github:owner/repo/ref?dir=sub`."""
    kind = attributes["type"]
    query = {key: attributes[key] for key in ("dir",) if key in attributes}
    match kind:
        case "github" | "gitlab" | "sourcehut":
            ref = attributes.get("ref") or attributes.get("rev")
            base = f"{kind}:{attributes['owner']}/{attributes['repo']}" + (f"/{ref}" if ref else "")
        case "git":
            base = f"git+{attributes['url']}"
            query = {key: attributes[key] for key in ("ref", "rev") if key in attributes} | query
        case "path":
            base = f"path:{attributes['path']}"
        case "indirect":
            base = attributes["id"]
        case _:
            # tarball, file, mercurial: their URL says it.
            base = attributes.get("url", kind)
    return f"{base}?{urlencode(query)}" if query else base


def _local_directory(name: str, node: dict[str, Any]) -> PurePosixPath | None:
    locked = node["locked"]
    if locked["type"] != "path" or locked["path"].startswith("/"):
        return None
    directory = posixpath.normpath(locked["path"])
    if directory == "." or directory.startswith(".."):
        raise SkillsFlakeError(f"skill {name}: a local skill is a directory below skills/, not {locked['path']!r}")
    return PurePosixPath(directory)


def read_skills_flake(skills_dir: Path) -> list[ListedSkill]:
    """The skills of *skills_dir*'s flake. Without `flake.nix` a repo has no skills: there is no other discovery."""
    if not (skills_dir / "flake.nix").is_file():
        raise SkillsFlakeError(f"skills/flake.nix is missing, so this knowledge repo has no skills. {_FIX}")
    lock = skills_dir / "flake.lock"
    if not lock.is_file():
        raise SkillsFlakeError(f"skills/flake.lock is missing. {_FIX}")
    return parse_skills_lock(lock.read_text())


@dataclass(frozen=True)
class SkillDocument:
    """A parsed SKILL.md: frontmatter fields plus the markdown body below it."""

    name: str
    description: str
    metadata: dict[str, Any]
    body: str

    def carapace_config(self) -> SkillCarapaceConfig | None:
        """Validate ``metadata.carapace``; None only when the skill declares none."""
        raw = self.metadata.get("carapace")
        if raw is None:
            return None
        try:
            return SkillCarapaceConfig.model_validate(raw)
        except ValidationError as exc:
            # Compact on purpose: the message lands in prompts and tool results, and the
            # default rendering echoes input values and documentation links.
            problems = "; ".join(
                f"{'.'.join(map(str, error['loc']))}: {error['msg']}" if error["loc"] else error["msg"]
                for error in exc.errors()
            )
            raise SkillDocumentError(f"invalid metadata.carapace: {problems}") from exc


def parse_skill_document(text: str, *, fallback_name: str) -> SkillDocument:
    """Split *text* into frontmatter and body. A SKILL.md without frontmatter is all body."""
    if not text.startswith("---"):
        return SkillDocument(name=fallback_name, description="", metadata={}, body=text)

    parts = text.split("---", 2)
    if len(parts) < 3:
        raise SkillDocumentError("unterminated frontmatter: missing the closing '---'")

    try:
        raw = yaml.safe_load(parts[1])
    except yaml.YAMLError as exc:
        raise SkillDocumentError(f"invalid YAML frontmatter: {_describe_yaml_error(exc)}") from exc

    if not isinstance(raw, dict):
        raise SkillDocumentError("frontmatter must be a YAML mapping")

    metadata = raw.get("metadata")
    if metadata is None:
        metadata = {}
    elif not isinstance(metadata, dict):
        raise SkillDocumentError("`metadata` must be a mapping")

    return SkillDocument(
        name=_optional_str(raw, "name") or fallback_name,
        description=_optional_str(raw, "description") or "",
        metadata=metadata,
        body=parts[2].lstrip("\n"),
    )


def _optional_str(frontmatter: dict[str, Any], key: str) -> str | None:
    value = frontmatter.get(key)
    if value is not None and not isinstance(value, str):
        raise SkillDocumentError(f"`{key}` must be a string, got {type(value).__name__}")
    return value


def _describe_yaml_error(exc: yaml.YAMLError) -> str:
    # The default rendering quotes the offending line into the catalog; line and column suffice to find it.
    if isinstance(exc, yaml.MarkedYAMLError) and exc.problem_mark is not None:
        mark = exc.problem_mark
        return f"{exc.problem} (line {mark.line + 1}, column {mark.column + 1})"
    return str(exc)


class SkillRegistry:
    def __init__(self, skills_dir: Path):
        self.skills_dir = skills_dir
        self._catalog: list[SkillInfo] | None = None
        self._listed: dict[str, ListedSkill] | None = None

    def invalidate(self) -> None:
        self._catalog = None
        self._listed = None

    def listed(self) -> dict[str, ListedSkill]:
        """The skills of skills/flake.nix by name. Raises ``SkillsFlakeError`` when it or its lock is unusable."""
        if self._listed is None:
            self._listed = {skill.name: skill for skill in read_skills_flake(self.skills_dir)}
        return self._listed

    def scan(self) -> list[SkillInfo]:
        """Frontmatter of every listed local skill (progressive disclosure)."""
        if self._catalog is not None:
            return self._catalog
        try:
            listed = self.listed().values()
        except SkillsFlakeError as exc:
            logger.error(f"No skills in {self.skills_dir}: {exc}")
            listed = []
        # A skill from elsewhere has no SKILL.md in this repo to list.
        self._catalog = [
            self._catalog_entry(skill.name, self.skills_dir / skill.directory)
            for skill in listed
            if skill.directory is not None
        ]
        return self._catalog

    def skill_dir(self, skill_name: str) -> Path | None:
        """The directory of a listed local skill."""
        try:
            skill = self.listed().get(skill_name)
        except SkillsFlakeError:
            return None
        return None if skill is None or skill.directory is None else self.skills_dir / skill.directory

    def get_full_instructions(self, skill_name: str) -> str | None:
        """Load the full SKILL.md of a skill (``read_skill``)."""
        skill_md = self._skill_md(skill_name)
        return skill_md.read_text() if skill_md is not None else None

    def get_carapace_config(self, skill_name: str) -> SkillCarapaceConfig | None:
        """Load carapace skill config from SKILL.md frontmatter.

        Raises ``SkillDocumentError`` when the frontmatter or ``metadata.carapace`` is invalid.
        """
        skill_md = self._skill_md(skill_name)
        if skill_md is None:
            return None
        return parse_skill_document(skill_md.read_text(), fallback_name=skill_name).carapace_config()

    def _skill_md(self, skill_name: str) -> Path | None:
        skill_dir = self.skill_dir(skill_name)
        if skill_dir is None or not (skill_dir / "SKILL.md").is_file():
            return None
        return skill_dir / "SKILL.md"

    def _catalog_entry(self, name: str, skill_dir: Path) -> SkillInfo:
        skill_md = skill_dir / "SKILL.md"
        try:
            if not skill_md.is_file():
                raise SkillDocumentError(f"{skill_md.relative_to(self.skills_dir.parent)} is missing")
            document = parse_skill_document(skill_md.read_text(), fallback_name=name)
            document.carapace_config()
        except SkillDocumentError as exc:
            # Listed rather than dropped: the agent has to see the skill is broken to fix it.
            logger.error(f"Skill '{name}' has an invalid SKILL.md: {exc}")
            return SkillInfo(
                name=name,
                description=f"BROKEN, cannot be used until its SKILL.md is fixed: {exc}",
                path=skill_dir,
            )
        # Named by its attribute in skills/flake.nix, whatever the frontmatter says.
        return SkillInfo(name=name, description=document.description, path=skill_dir)
