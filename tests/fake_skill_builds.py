"""Skill builds for tests that read a built skill's files without a builder."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from carapace.builder.skill_builds import SkillBuild, SkillBuilds


class FakeSkillBuilds:
    """One built skill whose directory holds *files*. A change re-keys it, as a push of the skill does."""

    def __init__(self, name: str, files: dict[str, str]) -> None:
        self.name = name
        self.files = dict(files)
        self._version = 0

    def change(self, path: str, content: str) -> None:
        self.files[path] = content
        self._version += 1

    async def ensure_built(self, _repo_dir: Path) -> list[SkillBuild]:
        return [self._build()]

    def readable(self, _repo_dir: Path, name: str) -> SkillBuild | None:
        return self._build() if name == self.name else None

    def _build(self) -> SkillBuild:
        return SkillBuild(
            skill=self.name,
            key=f"{self._version:064x}",
            state="succeeded",
            store_paths=[],
            commands={},
            detail="",
            skill_dir=f"/nix/store/{'c' * 32}-skill-{self.name}-src",
            skill_md=self.files.get("SKILL.md"),
            skill_files=sorted(self.files),
        )

    async def skill_file(self, _build: SkillBuild, path: str) -> bytes | None:
        content = self.files.get(path)
        return None if content is None else content.encode()


def fake_skill_builds(name: str, files: dict[str, str]) -> tuple[SkillBuilds, FakeSkillBuilds]:
    """The fake as the type a sentinel takes, and as itself to change its files."""
    fake = FakeSkillBuilds(name, files)
    return cast(SkillBuilds, fake), fake
