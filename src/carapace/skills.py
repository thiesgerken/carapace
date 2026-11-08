from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from loguru import logger
from pydantic import ValidationError

from .models.skills import SkillCarapaceConfig, SkillInfo


class SkillDocumentError(ValueError):
    """A SKILL.md whose frontmatter cannot be read as a skill declaration."""


@dataclass(frozen=True)
class SkillDocument:
    """A parsed SKILL.md: frontmatter fields plus the markdown body below it."""

    name: str
    description: str
    metadata: dict[str, Any]
    body: str

    @property
    def disabled(self) -> bool:
        # Opt-out must survive validation failures in unrelated runtime declarations.
        config = self.metadata.get("carapace")
        return isinstance(config, dict) and config.get("disabled") is True

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
    # The default rendering quotes the offending line, which would leak the content of
    # a skill that may be disabled into the catalog; line and column suffice to find it.
    if isinstance(exc, yaml.MarkedYAMLError) and exc.problem_mark is not None:
        mark = exc.problem_mark
        return f"{exc.problem} (line {mark.line + 1}, column {mark.column + 1})"
    return str(exc)


class SkillRegistry:
    def __init__(self, skills_dir: Path):
        self.skills_dir = skills_dir
        self._catalog: list[SkillInfo] | None = None

    def invalidate(self) -> None:
        self._catalog = None

    def scan(self) -> list[SkillInfo]:
        """Scan skills/ directory and load frontmatter only (progressive disclosure)."""
        if self._catalog is not None:
            return self._catalog

        catalog: list[SkillInfo] = []
        if not self.skills_dir.exists():
            self._catalog = catalog
            return catalog

        for skill_dir in sorted(self.skills_dir.iterdir()):
            if not skill_dir.is_dir():
                continue
            skill_md = skill_dir / "SKILL.md"
            if not skill_md.exists():
                continue
            info = self._catalog_entry(skill_md, skill_dir)
            if info:
                catalog.append(info)

        self._catalog = catalog
        return catalog

    def is_disabled(self, skill_name: str) -> bool:
        """Read the current opt-out flag without validating runtime declarations.

        Raises ``SkillDocumentError`` when the frontmatter itself is unreadable.
        """
        skill_dir = self.skills_dir / skill_name
        skill_md = skill_dir / "SKILL.md"
        return skill_md.exists() and self._load_frontmatter(skill_md, skill_dir).disabled

    def get_full_instructions(self, skill_name: str) -> str | None:
        """Load the full SKILL.md body for a skill (activation)."""
        skill_dir = self.skills_dir / skill_name
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            return None
        return skill_md.read_text()

    def get_carapace_config(self, skill_name: str) -> SkillCarapaceConfig | None:
        """Load carapace skill config from SKILL.md frontmatter.

        Raises ``SkillDocumentError`` when the frontmatter or ``metadata.carapace`` is invalid.
        """
        skill_dir = self.skills_dir / skill_name
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            return None
        return self._load_frontmatter(skill_md, skill_dir).carapace_config()

    def _catalog_entry(self, skill_md: Path, skill_dir: Path) -> SkillInfo | None:
        try:
            document = self._load_frontmatter(skill_md, skill_dir)
            if document.disabled:
                return None
            document.carapace_config()
        except SkillDocumentError as exc:
            # Listed rather than dropped: the agent has to see the skill is broken to fix it.
            logger.error(f"Skill '{skill_dir.name}' has an invalid SKILL.md: {exc}")
            return SkillInfo(
                name=skill_dir.name,
                description=f"BROKEN, cannot be activated until its SKILL.md frontmatter is fixed: {exc}",
                path=skill_dir,
            )

        return SkillInfo(name=document.name, description=document.description, path=skill_dir)

    def _load_frontmatter(self, skill_md: Path, skill_dir: Path) -> SkillDocument:
        return parse_skill_document(skill_md.read_text(), fallback_name=skill_dir.name)
