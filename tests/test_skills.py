"""Listing skills from skills/flake.lock and reading SKILL.md frontmatter (no LLM tokens needed)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

import pytest

from carapace.skills import (
    SkillDocumentError,
    SkillsFlakeError,
    flake_ref,
    parse_skill_document,
    parse_skills_lock,
    read_skills_flake,
)
from tests.skills_flake import write_skills_flake


def _write_skill(skills_dir: Path, directory: str, text: str) -> Path:
    skill_md = skills_dir / directory / "SKILL.md"
    skill_md.parent.mkdir(parents=True, exist_ok=True)
    skill_md.write_text(text)
    return skill_md


def test_without_a_skills_flake_there_are_no_skills(tmp_path: Path) -> None:
    _write_skill(tmp_path, "my-skill", "---\nname: my-skill\ndescription: A test skill\n---\n")

    with pytest.raises(SkillsFlakeError, match=r"skills/flake\.nix is missing"):
        read_skills_flake(tmp_path)


def test_without_a_lock_there_are_no_skills(tmp_path: Path) -> None:
    write_skills_flake(tmp_path, ["my-skill"])
    (tmp_path / "flake.lock").unlink()

    with pytest.raises(SkillsFlakeError, match=r"nix flake lock \./skills"):
        read_skills_flake(tmp_path)


def test_only_what_the_flake_lists_is_a_skill_named_by_its_attribute(tmp_path: Path) -> None:
    _write_skill(tmp_path, "carapace", "---\nname: carapace\n---\n")
    _write_skill(tmp_path, "unlisted", "---\nname: unlisted\n---\n")
    write_skills_flake(tmp_path, {"carapace-cli": "carapace"}, external=["tracker"])

    listed = {skill.name: skill.directory for skill in read_skills_flake(tmp_path)}

    assert listed == {"carapace-cli": PurePosixPath("carapace"), "tracker": None}


def test_disabled_in_the_frontmatter_is_refused() -> None:
    text = "---\nname: private-search\nmetadata:\n  carapace:\n    disabled: true\n---\nFull instructions.\n"

    with pytest.raises(SkillDocumentError, match="disabled is gone"):
        parse_skill_document(text, fallback_name="private-search").carapace_config()


@pytest.mark.parametrize("path", ["../outside", ".", "./a/../.."])
def test_a_local_skill_outside_skills_is_refused(path: str) -> None:
    lock = {
        "nodes": {"root": {"inputs": {"odd": "odd"}}, "odd": {"locked": {"type": "path", "path": path}}},
        "root": "root",
        "version": 7,
    }

    with pytest.raises(SkillsFlakeError, match="below skills/"):
        parse_skills_lock(json.dumps(lock))


@pytest.mark.parametrize(
    "locked",
    [
        {"type": "path", "path": "/srv/skills/odd"},
        {"type": "file", "url": "file:///srv/skills/odd.tar.gz"},
        {"type": "git", "url": "file:///srv/skills/odd.git", "rev": "a" * 40},
        {"type": "tarball", "url": "file:///srv/skills/odd.tar.gz"},
    ],
)
def test_an_input_on_the_builders_disk_is_refused(locked: dict[str, str]) -> None:
    lock = {"nodes": {"root": {"inputs": {"odd": "odd"}}, "odd": {"locked": locked}}, "root": "root", "version": 7}

    with pytest.raises(SkillsFlakeError, match="reads the builder's disk"):
        parse_skills_lock(json.dumps(lock))


@pytest.mark.parametrize("text", ["not json", "[]", '{"nodes": {}}', '{"nodes": {"root": {}}, "root": "elsewhere"}'])
def test_a_broken_lock_is_reported(text: str) -> None:
    with pytest.raises(SkillsFlakeError, match="not a flake lock file"):
        parse_skills_lock(text)


def test_a_listed_skill_says_where_it_comes_from_and_what_is_locked() -> None:
    lock = {
        "nodes": {
            "root": {"inputs": {"notes": "notes", "tracker": "tracker"}},
            "notes": {"locked": {"type": "path", "path": "./notes"}},
            "tracker": {
                "locked": {"type": "github", "owner": "someone", "repo": "skills", "rev": "a" * 40, "lastModified": 1},
                "original": {"type": "github", "owner": "someone", "repo": "skills", "dir": "tracker"},
            },
        },
        "root": "root",
        "version": 7,
    }

    notes, tracker = parse_skills_lock(json.dumps(lock))

    assert (notes.origin, notes.locked_rev, notes.locked_at) == ("./notes", None, None)
    assert (tracker.origin, tracker.locked_rev) == ("github:someone/skills?dir=tracker", "a" * 40)
    assert tracker.locked_at == datetime.fromtimestamp(1, UTC)


@pytest.mark.parametrize(
    ("attributes", "ref"),
    [
        ({"type": "github", "owner": "o", "repo": "r", "ref": "v1.2"}, "github:o/r/v1.2"),
        ({"type": "gitlab", "owner": "o", "repo": "r", "rev": "abc"}, "gitlab:o/r/abc"),
        (
            {"type": "git", "url": "https://example.com/r.git", "ref": "main", "dir": "a/b"},
            "git+https://example.com/r.git?ref=main&dir=a/b",
        ),
        ({"type": "path", "path": "/srv/skills/x"}, "path:/srv/skills/x"),
        ({"type": "indirect", "id": "flake-utils"}, "flake-utils"),
        ({"type": "tarball", "url": "https://example.com/x.tar.gz"}, "https://example.com/x.tar.gz"),
    ],
)
def test_flake_references_read_as_written(attributes: dict[str, str], ref: str) -> None:
    assert flake_ref(attributes) == ref
