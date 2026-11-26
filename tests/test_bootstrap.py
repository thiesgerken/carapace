"""Seeding a knowledge repo: a new one gets the bundled skills and the flake that lists them."""

from __future__ import annotations

from pathlib import Path, PurePosixPath

import pytest

from carapace.bootstrap import ensure_knowledge_dir
from carapace.skills import read_skills_flake


def test_a_new_repo_lists_its_bundled_skills_in_skills_flake(tmp_path: Path) -> None:
    created = ensure_knowledge_dir(tmp_path)

    listed = read_skills_flake(tmp_path / "skills")

    assert {"skills/flake.nix", "skills/flake.lock"} <= set(created)
    assert {(skill.name, skill.directory) for skill in listed} == {
        ("carapace-cli", PurePosixPath("carapace")),
        ("wikipedia", PurePosixPath("wikipedia")),
    }
    assert all((tmp_path / "skills" / str(skill.directory) / "flake.nix").is_file() for skill in listed)


def test_an_existing_repo_keeps_its_own_list(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "skills" / "mine").mkdir(parents=True)

    ensure_knowledge_dir(tmp_path)
    assert not (tmp_path / "skills" / "flake.nix").exists()

    (tmp_path / "skills" / "flake.nix").write_text("my own list\n")
    monkeypatch.setenv("CARAPACE_RESET_ASSETS", "true")
    ensure_knowledge_dir(tmp_path)
    assert (tmp_path / "skills" / "flake.nix").read_text() == "my own list\n"
