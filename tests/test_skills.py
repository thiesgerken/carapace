"""Listing skills from skills/flake.lock (no LLM tokens needed)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

import pytest

from carapace.skills import (
    SkillsFlakeError,
    flake_ref,
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


NAR = {"narHash": "sha256-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="}


@pytest.mark.parametrize("node_id", ["tracker", "nested"])
def test_an_input_locked_without_a_nar_hash_is_refused(node_id: str) -> None:
    """A rev alone counts as locked, and the builder's Git cache would serve a commit another user's token fetched."""
    nodes = {
        "root": {"inputs": {"tracker": "tracker", "local": "local"}},
        "tracker": {
            "inputs": {"nested": "nested"},
            "locked": {"type": "git", "url": "https://git.example.org/alice/tracker", "rev": "2" * 40, **NAR},
        },
        "nested": {"locked": {"type": "github", "owner": "alice", "repo": "nested", "rev": "3" * 40, **NAR}},
        # A local skill's node never has one; it comes from the repo itself.
        "local": {"locked": {"type": "path", "path": "./local"}},
    }
    lock = {"nodes": nodes, "root": "root", "version": 7}
    assert [skill.name for skill in parse_skills_lock(json.dumps(lock))] == ["local", "tracker"]

    del nodes[node_id]["locked"]["narHash"]

    with pytest.raises(SkillsFlakeError, match=f"input {node_id}: its lock entry has no narHash"):
        parse_skills_lock(json.dumps(lock))


@pytest.mark.parametrize("node_id", ["nixpkgs", "nested"])
def test_a_shared_or_nested_input_on_the_builders_disk_is_refused(node_id: str) -> None:
    nodes = {
        "root": {"inputs": {"nixpkgs": "nixpkgs", "tracker": "tracker"}},
        "nixpkgs": {"locked": {"type": "github", "owner": "NixOS", "repo": "nixpkgs", "rev": "0" * 40, **NAR}},
        "tracker": {
            "inputs": {"nested": "nested"},
            "locked": {"type": "github", "owner": "someone", "repo": "tracker", "rev": "2" * 40, **NAR},
        },
        "nested": {"locked": {"type": "github", "owner": "someone", "repo": "nested", "rev": "3" * 40, **NAR}},
    }
    nodes[node_id]["locked"] = {"type": "path", "path": "/etc", "narHash": "sha256-x"}

    with pytest.raises(SkillsFlakeError, match=f"input {node_id}: .*reads the builder's disk"):
        parse_skills_lock(json.dumps({"nodes": nodes, "root": "root", "version": 7}))


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
                "locked": {
                    "type": "github",
                    "owner": "someone",
                    "repo": "skills",
                    "rev": "a" * 40,
                    "lastModified": 1,
                    **NAR,
                },
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
