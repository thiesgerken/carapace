from __future__ import annotations

import json
import posixpath
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml
from pydantic import ValidationError

from .models.skills import SkillCarapaceConfig


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


def parse_skills_lock(text: str) -> list[ListedSkill]:
    """The skills `skills/flake.lock` lists, sorted by name.

    The lock and not the flake: the server never evaluates Nix, and the lock holds every input the builder builds.
    """
    try:
        lock = json.loads(text)
        nodes = lock["nodes"]
        inputs = nodes[lock["root"]].get("inputs", {})
        skills = [
            ListedSkill(name=name, directory=_local_directory(name, nodes[node]))
            for name, node in sorted(inputs.items())
            if name not in _SHARED_INPUTS
        ]
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise SkillsFlakeError(f"skills/flake.lock is not a flake lock file ({exc}). {_FIX}") from exc
    return skills


def _local_directory(name: str, node: dict[str, Any]) -> PurePosixPath | None:
    locked = node["locked"]
    # A path on the builder's own disk: it would read the builder, not this repo, and no key covers it.
    if (
        (locked["type"] == "path" and locked["path"].startswith("/"))
        or locked["type"] == "file"
        or (str(locked.get("url", "")).startswith("file:"))
    ):
        raise SkillsFlakeError(
            f"skill {name}: an absolute path, file: or git+file: input reads the builder's disk; "
            "use path:./<dir> for a skill in this repo or a remote flake reference"
        )
    if locked["type"] != "path":
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
