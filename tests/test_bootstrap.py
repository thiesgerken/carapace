"""Seeding a knowledge repo: a new one gets the flake that lists the bundled skills."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import carapace
from carapace.bootstrap import ensure_knowledge_dir
from carapace.skills import read_skills_flake


def test_a_new_repo_lists_its_bundled_skills_in_skills_flake(tmp_path: Path) -> None:
    created = ensure_knowledge_dir(tmp_path)

    listed = read_skills_flake(tmp_path / "skills")

    assert set(created) >= {"skills/flake.nix", "skills/flake.lock", "skills/config.json"}
    # All come from carapace as inputs; nothing is copied.
    assert {(skill.name, skill.directory) for skill in listed} == {
        ("artifacts", None),
        ("carapace-cli", None),
        ("create-skill", None),
        ("credentials", None),
        ("ferret", None),
        ("mermaid", None),
        ("web", None),
        ("wikipedia", None),
    }
    assert not [path for path in (tmp_path / "skills").iterdir() if path.is_dir()]
    # The ones that need a server, a key or an endpoint first are off.
    assert json.loads((tmp_path / "skills" / "config.json").read_text()) == {
        "carapace-cli": {"enable": False},
        "ferret": {"enable": False},
        "web": {"enable": False},
    }


def test_every_bundled_skill_is_an_input_on_carapace() -> None:
    assets = Path(carapace.__file__).parent / "assets" / "skills"
    flake = (assets / "flake.nix").read_text()
    inputs = dict(
        re.findall(
            r'    ([a-z-]+) = \{\n      url = "github:thiesgerken/carapace\?dir=src/carapace/assets/skills/([a-z-]+)";',
            flake,
        )
    )

    assert set(inputs.values()) == {path.name for path in assets.iterdir() if path.is_dir()}
    # Each follows the repo's carapace and nixpkgs, so `nix flake update carapace` moves them all.
    for name in inputs:
        block = flake[flake.index(f"    {name} = {{") :]
        block = block[: block.index("};")]
        assert 'inputs.nixpkgs.follows = "nixpkgs";' in block and 'inputs.carapace.follows = "carapace";' in block


def test_an_existing_repo_keeps_its_own_list(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "skills" / "mine").mkdir(parents=True)

    ensure_knowledge_dir(tmp_path)
    assert not (tmp_path / "skills" / "flake.nix").exists()

    (tmp_path / "skills" / "flake.nix").write_text("my own list\n")
    monkeypatch.setenv("CARAPACE_RESET_ASSETS", "true")
    ensure_knowledge_dir(tmp_path)
    assert (tmp_path / "skills" / "flake.nix").read_text() == "my own list\n"


def test_a_reset_overwrites_seeded_files_even_when_they_are_read_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ensure_knowledge_dir(tmp_path)
    security = tmp_path / "SECURITY.md"
    original = security.read_text()
    security.write_text("changed\n")
    # What copying from the Nix store left behind before.
    security.chmod(0o444)

    monkeypatch.setenv("CARAPACE_RESET_ASSETS", "true")
    ensure_knowledge_dir(tmp_path)

    assert security.read_text() == original
