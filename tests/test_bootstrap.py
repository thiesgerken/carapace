"""Seeding a knowledge repo: a new one gets the bundled skills and the flake that lists them."""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath

import pytest

import carapace
from carapace.bootstrap import LOCAL_BUNDLED_SKILLS, ensure_knowledge_dir
from carapace.skills import read_skills_flake


def test_a_new_repo_lists_its_bundled_skills_in_skills_flake(tmp_path: Path) -> None:
    created = ensure_knowledge_dir(tmp_path)

    listed = read_skills_flake(tmp_path / "skills")

    assert {"skills/flake.nix", "skills/flake.lock"} <= set(created)
    # The config-free ones come from carapace as external inputs, the others are copied.
    assert {(skill.name, skill.directory) for skill in listed} == {
        ("artifacts", None),
        ("carapace-cli", PurePosixPath("carapace")),
        ("create-skill", None),
        ("credentials", None),
        ("mermaid", None),
        ("wikipedia", None),
    }
    assert sorted(path.name for path in (tmp_path / "skills").iterdir() if path.is_dir()) == [
        "carapace",
        "ferret",
        "web",
    ]
    assert (tmp_path / "skills" / "carapace" / "flake.nix").is_file()


def test_every_bundled_skill_is_copied_or_an_input_on_carapace() -> None:
    assets = Path(carapace.__file__).parent / "assets" / "skills"
    flake = (assets / "flake.nix").read_text()
    external = set(re.findall(r'url = "github:thiesgerken/carapace\?dir=src/carapace/assets/skills/([a-z-]+)";', flake))
    bundled = {path.name for path in assets.iterdir() if path.is_dir()}

    assert external.isdisjoint(LOCAL_BUNDLED_SKILLS)
    assert external | set(LOCAL_BUNDLED_SKILLS) == bundled
    # Each external input follows the repo's carapace and nixpkgs, so `nix flake update carapace` moves them all.
    for name in external:
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
