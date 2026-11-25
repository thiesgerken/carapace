"""Tests for SkillRegistry (no LLM tokens needed)."""

from __future__ import annotations

from pathlib import Path

import pytest

from carapace.prompt_prefix import shared_prompt_prefix
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


@pytest.mark.parametrize("runtime_config", ["", "    commands: invalid\n"])
def test_disabled_skill_discovery_and_enable_transition(tmp_path: Path, runtime_config: str) -> None:
    skill_dir = tmp_path / "skills" / "private-search"
    skill_dir.mkdir(parents=True)
    skill_md = skill_dir / "SKILL.md"
    text = (
        "---\nname: private-search\ndescription: Private indexed material\n"
        "metadata:\n  carapace:\n    disabled: true\n"
        f"{runtime_config}---\nFull instructions.\n"
    )
    skill_md.write_text(text)
    registry = SkillRegistry(tmp_path / "skills")

    assert registry.scan() == []
    assert registry.is_disabled("private-search")
    assert "Private indexed material" not in shared_prompt_prefix(tmp_path, registry.scan())
    assert registry.get_full_instructions("private-search") == text
    if not runtime_config:
        config = registry.get_carapace_config("private-search")
        assert config is not None and config.disabled

    skill_md.write_text(text.replace("disabled: true", "disabled: false"))
    registry.invalidate()

    assert not registry.is_disabled("private-search")
    [entry] = registry.scan()
    assert entry.name == "private-search"
    if runtime_config:
        assert entry.description.startswith("BROKEN")
    else:
        assert "Private indexed material" in shared_prompt_prefix(tmp_path, registry.scan())
