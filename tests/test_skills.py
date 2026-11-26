"""Tests for SkillRegistry (no LLM tokens needed)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from carapace.prompt_prefix import shared_prompt_prefix
from carapace.skills import SkillDocumentError, SkillRegistry, SkillsFlakeError, parse_skills_lock
from tests.skills_flake import write_skills_flake


def _write_skill(skills_dir: Path, directory: str, text: str) -> Path:
    skill_md = skills_dir / directory / "SKILL.md"
    skill_md.parent.mkdir(parents=True, exist_ok=True)
    skill_md.write_text(text)
    return skill_md


def test_without_a_skills_flake_there_are_no_skills(tmp_path: Path) -> None:
    _write_skill(tmp_path, "my-skill", "---\nname: my-skill\ndescription: A test skill\n---\n")
    registry = SkillRegistry(tmp_path)

    assert registry.scan() == []
    assert registry.get_full_instructions("my-skill") is None
    with pytest.raises(SkillsFlakeError, match=r"skills/flake\.nix is missing"):
        registry.listed()


def test_without_a_lock_there_are_no_skills(tmp_path: Path) -> None:
    write_skills_flake(tmp_path, ["my-skill"])
    (tmp_path / "flake.lock").unlink()

    with pytest.raises(SkillsFlakeError, match=r"nix flake lock \./skills"):
        SkillRegistry(tmp_path).listed()


def test_scan_lists_only_what_the_flake_lists(tmp_path: Path) -> None:
    _write_skill(tmp_path, "my-skill", "---\nname: my-skill\ndescription: A test skill\n---\nBody here.\n")
    _write_skill(tmp_path, "unlisted", "---\nname: unlisted\ndescription: Not listed\n---\n")
    write_skills_flake(tmp_path, ["my-skill"], external=["tracker"])

    catalog = SkillRegistry(tmp_path).scan()

    # An external skill has no SKILL.md in this repo to list.
    assert [(info.name, info.description) for info in catalog] == [("my-skill", "A test skill")]


def test_a_skill_is_named_by_its_attribute(tmp_path: Path) -> None:
    content = "---\nname: carapace\ndescription: Drive carapace\n---\nDo the thing.\n"
    _write_skill(tmp_path, "carapace", content)
    write_skills_flake(tmp_path, {"carapace-cli": "carapace"})
    registry = SkillRegistry(tmp_path)

    assert [info.name for info in registry.scan()] == ["carapace-cli"]
    assert registry.get_full_instructions("carapace-cli") == content
    assert registry.get_full_instructions("carapace") is None


def test_scan_no_frontmatter(tmp_path: Path) -> None:
    _write_skill(tmp_path, "plain-skill", "Just a body, no frontmatter.\n")
    write_skills_flake(tmp_path, ["plain-skill"])

    assert [info.name for info in SkillRegistry(tmp_path).scan()] == ["plain-skill"]


def test_a_listed_skill_without_skill_md_is_listed_as_broken(tmp_path: Path) -> None:
    (tmp_path / "commands-only").mkdir()
    write_skills_flake(tmp_path, ["commands-only"])

    [entry] = SkillRegistry(tmp_path).scan()

    assert entry.name == "commands-only"
    assert entry.description.startswith("BROKEN") and "SKILL.md is missing" in entry.description


def test_get_full_instructions_missing(tmp_path: Path) -> None:
    write_skills_flake(tmp_path, [])
    assert SkillRegistry(tmp_path).get_full_instructions("nope") is None


def test_scan_caches(tmp_path: Path) -> None:
    registry = SkillRegistry(tmp_path)
    assert registry.scan() is registry.scan()


def test_disabled_in_the_frontmatter_is_refused(tmp_path: Path) -> None:
    text = (
        "---\nname: private-search\ndescription: Private indexed material\n"
        "metadata:\n  carapace:\n    disabled: true\n---\nFull instructions.\n"
    )
    _write_skill(tmp_path, "private-search", text)
    write_skills_flake(tmp_path, ["private-search"])
    registry = SkillRegistry(tmp_path)

    [entry] = registry.scan()

    assert entry.description.startswith("BROKEN") and "unlist it there" in entry.description
    assert "Private indexed material" not in shared_prompt_prefix(tmp_path, registry.scan())
    with pytest.raises(SkillDocumentError, match="disabled is gone"):
        registry.get_carapace_config("private-search")


@pytest.mark.parametrize("path", ["../outside", ".", "./a/../.."])
def test_a_local_skill_outside_skills_is_refused(path: str) -> None:
    lock = {
        "nodes": {"root": {"inputs": {"odd": "odd"}}, "odd": {"locked": {"type": "path", "path": path}}},
        "root": "root",
        "version": 7,
    }

    with pytest.raises(SkillsFlakeError, match="below skills/"):
        parse_skills_lock(json.dumps(lock))


@pytest.mark.parametrize("text", ["not json", "[]", '{"nodes": {}}', '{"nodes": {"root": {}}, "root": "elsewhere"}'])
def test_a_broken_lock_is_reported(text: str) -> None:
    with pytest.raises(SkillsFlakeError, match="not a flake lock file"):
        parse_skills_lock(text)
