"""Tests for SkillRegistry (no LLM tokens needed)."""

from pathlib import Path

from carapace.skills import SkillRegistry


def test_scan_empty(tmp_path: Path):
    registry = SkillRegistry(tmp_path / "skills")
    catalog = registry.scan()
    assert catalog == []


def test_scan_finds_skill(tmp_path: Path):
    skill_dir = tmp_path / "my-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("---\nname: my-skill\ndescription: A test skill\n---\nBody here.\n")
    registry = SkillRegistry(tmp_path)
    catalog = registry.scan()
    assert len(catalog) == 1
    assert catalog[0].name == "my-skill"
    assert catalog[0].description == "A test skill"


def test_scan_no_frontmatter(tmp_path: Path):
    skill_dir = tmp_path / "plain-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("Just a body, no frontmatter.\n")
    registry = SkillRegistry(tmp_path)
    catalog = registry.scan()
    assert len(catalog) == 1
    assert catalog[0].name == "plain-skill"


def test_get_full_instructions(tmp_path: Path):
    skill_dir = tmp_path / "my-skill"
    skill_dir.mkdir()
    content = "---\nname: my-skill\n---\nDo the thing.\n"
    (skill_dir / "SKILL.md").write_text(content)
    registry = SkillRegistry(tmp_path)
    assert registry.get_full_instructions("my-skill") == content


def test_get_full_instructions_missing(tmp_path: Path):
    registry = SkillRegistry(tmp_path)
    assert registry.get_full_instructions("nope") is None


def test_scan_caches(tmp_path: Path):
    registry = SkillRegistry(tmp_path)
    cat1 = registry.scan()
    cat2 = registry.scan()
    assert cat1 is cat2
