from __future__ import annotations

from pathlib import Path

import yaml

from carapace.models import SkillInfo


class SkillRegistry:
    def __init__(self, skills_dir: Path):
        self.skills_dir = skills_dir
        self._catalog: list[SkillInfo] | None = None

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

    def get_full_instructions(self, skill_name: str) -> str | None:
        """Load the full SKILL.md body for a skill (activation)."""
        skill_dir = self.skills_dir / skill_name
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            return None
        return skill_md.read_text()

    def _parse_frontmatter(self, skill_md: Path, skill_dir: Path) -> SkillInfo | None:
        text = skill_md.read_text()
        if not text.startswith("---"):
            return SkillInfo(name=skill_dir.name, path=skill_dir)

        parts = text.split("---", 2)
        if len(parts) < 3:
            return SkillInfo(name=skill_dir.name, path=skill_dir)

        try:
            fm = yaml.safe_load(parts[1])
        except yaml.YAMLError:
            return SkillInfo(name=skill_dir.name, path=skill_dir)

        if not isinstance(fm, dict):
            return SkillInfo(name=skill_dir.name, path=skill_dir)

        return SkillInfo(
            name=fm.get("name", skill_dir.name),
            description=fm.get("description", ""),
            path=skill_dir,
        )
