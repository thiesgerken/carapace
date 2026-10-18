from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from loguru import logger

from .models.skills import SkillCarapaceConfig, SkillInfo


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


def parse_skill_document(text: str, *, fallback_name: str) -> SkillDocument:
    """Split *text* into frontmatter and body, tolerating missing or invalid YAML."""
    fallback = SkillDocument(name=fallback_name, description="", metadata={}, body=text)
    if not text.startswith("---"):
        return fallback

    parts = text.split("---", 2)
    if len(parts) < 3:
        return fallback

    try:
        raw = yaml.safe_load(parts[1])
    except yaml.YAMLError:
        return fallback

    if not isinstance(raw, dict):
        return fallback

    metadata = raw.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}

    name = raw.get("name")
    if not isinstance(name, str) or not name:
        name = fallback_name

    description = raw.get("description")
    if not isinstance(description, str):
        description = ""

    return SkillDocument(name=name, description=description, metadata=metadata, body=parts[2].lstrip("\n"))


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
            info = self._parse_frontmatter(skill_md, skill_dir)
            if info:
                catalog.append(info)

        self._catalog = catalog
        return catalog

    def is_disabled(self, skill_name: str) -> bool:
        """Read the current opt-out flag without validating runtime declarations."""
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
        """Load carapace skill config from SKILL.md frontmatter."""
        skill_dir = self.skills_dir / skill_name
        skill_md = skill_dir / "SKILL.md"
        if skill_md.exists():
            frontmatter = self._load_frontmatter(skill_md, skill_dir)
            raw_metadata = frontmatter.metadata.get("carapace")
            if raw_metadata is not None:
                try:
                    return SkillCarapaceConfig.model_validate(raw_metadata)
                except Exception as exc:
                    logger.warning(f"Failed to parse metadata.carapace in SKILL.md for skill '{skill_name}': {exc}")
                    return None
        return None

    def _parse_frontmatter(self, skill_md: Path, skill_dir: Path) -> SkillInfo | None:
        frontmatter = self._load_frontmatter(skill_md, skill_dir)
        if frontmatter.disabled:
            return None

        return SkillInfo(
            name=frontmatter.name,
            description=frontmatter.description,
            path=skill_dir,
        )

    def _load_frontmatter(self, skill_md: Path, skill_dir: Path) -> SkillDocument:
        return parse_skill_document(skill_md.read_text(), fallback_name=skill_dir.name)
