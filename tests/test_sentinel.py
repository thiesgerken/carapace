from __future__ import annotations

from pathlib import Path

from pydantic_ai.models.test import TestModel

from carapace.security.context import SessionSecurity
from carapace.security.sentinel import Sentinel


def _make_sentinel(tmp_path: Path) -> tuple[Sentinel, Path]:
    knowledge_dir = tmp_path / "knowledge"
    skills_dir = tmp_path / "skills"
    knowledge_dir.mkdir()
    skills_dir.mkdir()
    sentinel = Sentinel(
        model="test:model",
        knowledge_dir=knowledge_dir,
        skills_dir=skills_dir,
        model_factory=lambda _name: TestModel(),
    )
    return sentinel, skills_dir


def test_read_skill_file_cached_reuses_unchanged_content(tmp_path: Path) -> None:
    sentinel, skills_dir = _make_sentinel(tmp_path)
    skill_dir = skills_dir / "moneydb"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("# MoneyDB\n")

    first = sentinel._read_skill_file_cached(skills_dir, "moneydb", "SKILL.md")
    second = sentinel._read_skill_file_cached(skills_dir, "moneydb", "SKILL.md")

    assert first == "# MoneyDB\n"
    assert "already provided earlier in this sentinel conversation" in second
    assert "SKILL.md" in second
    assert "moneydb" in second


def test_read_skill_file_cached_reloads_changed_file(tmp_path: Path) -> None:
    sentinel, skills_dir = _make_sentinel(tmp_path)
    skill_dir = skills_dir / "moneydb"
    skill_dir.mkdir()
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text("version-1\n")

    assert sentinel._read_skill_file_cached(skills_dir, "moneydb", "SKILL.md") == "version-1\n"

    skill_file.write_text("version-2\n")

    assert sentinel._read_skill_file_cached(skills_dir, "moneydb", "SKILL.md") == "version-2\n"


def test_reset_clears_skill_file_cache(tmp_path: Path) -> None:
    sentinel, skills_dir = _make_sentinel(tmp_path)
    skill_dir = skills_dir / "moneydb"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("# MoneyDB\n")

    sentinel._read_skill_file_cached(skills_dir, "moneydb", "SKILL.md")
    cached = sentinel._read_skill_file_cached(skills_dir, "moneydb", "SKILL.md")
    assert "already provided earlier in this sentinel conversation" in cached

    session = SessionSecurity("session-1")
    session.sentinel_eval_count = 1
    sentinel._reset(session)

    assert sentinel._read_skill_file_cached(skills_dir, "moneydb", "SKILL.md") == "# MoneyDB\n"
