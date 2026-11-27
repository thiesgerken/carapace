"""scripts/upgrade-skills-flake.sh: an existing knowledge repo gets a skills/flake.nix (no Nix needed here)."""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "scripts" / "upgrade-skills-flake.sh"
BOOTSTRAP = "🔧 bootstrap: seed default files"
_ENV = {"GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "T"}
_ENV |= {"GIT_COMMITTER_EMAIL": "t@example.com", "GIT_CONFIG_GLOBAL": os.devnull}
_OLD_FLAKE = """{
  outputs = { nixpkgs, carapace, ... }: {
    packages = carapace.lib.forSkillSystems (system: {
      default = (carapace.lib.skill nixpkgs.legacyPackages.${system}).mkSkill {
        name = "carapace";
        commands = { };
      };
    });
  };
}
"""
# The configuration lines of the release's bundled flakes, as bootstrap seeded them.
_RELEASE_CONFIG = {
    "carapace": '      server = "carapace.example.com";\n      apiKey = "<backend>/<your-carapace-api-key-id>";\n',
    "web": '                  credentials.BRAVE_API_KEY = "vault/brave-api-key";\n',
    "ferret": (
        '                url = "https://ferret.example.invalid/mcp";\n'
        '                bearer = "vault/ferret-api-key";\n'
    ),
}
_DISABLED = "metadata:\n  carapace:\n    disabled: true\n"


def _bundled_flake(name: str) -> str:
    return _OLD_FLAKE.replace('name = "carapace";', f'name = "{name}";\n{_RELEASE_CONFIG[name]}')


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True, env=os.environ | _ENV
    ).stdout


def _skill(repo: Path, name: str, frontmatter: str = "", flake: str | None = None) -> None:
    directory = repo / "skills" / name
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text(f"---\nname: {name}\n{frontmatter}---\nBody\n")
    if flake is not None:
        (directory / "flake.nix").write_text(flake)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repo as the last release bootstrapped it, with a user skill and a changed bundled one."""
    repo = tmp_path / "knowledge"
    repo.mkdir()
    _git(repo, "init", "-q")
    _skill(repo, "artifacts")
    _skill(repo, "mermaid")
    _skill(repo, "carapace", flake=_bundled_flake("carapace"))
    _skill(repo, "web", _DISABLED, flake=_bundled_flake("web"))
    _skill(repo, "ferret", _DISABLED, flake=_bundled_flake("ferret"))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", BOOTSTRAP)
    # Configured in its flake, as the release asked; nothing else changed.
    carapace_flake = repo / "skills" / "carapace" / "flake.nix"
    carapace_flake.write_text(
        carapace_flake.read_text()
        .replace("carapace.example.com", "carapace.home.test")
        .replace("<backend>/<your-carapace-api-key-id>", "bw/carapace-key")
    )
    # Set up as SETUP.md said: endpoint in the flake, turned on, and the sources in the description.
    ferret_flake = repo / "skills" / "ferret" / "flake.nix"
    ferret_flake.write_text(ferret_flake.read_text().replace("ferret.example.invalid", "ferret.home.test"))
    (repo / "skills" / "ferret" / "SKILL.md").write_text("---\nname: ferret\ndescription: Mail and notes\n---\nBody\n")
    _skill(repo, "notes")
    _skill(repo, "drafts", "metadata:\n  carapace:\n    disabled: true # later\n")
    # A package of its own takes a `src`; mkSkill still lacks one.
    _skill(
        repo,
        "tool",
        flake=_OLD_FLAKE.replace('name = "carapace";', 'name = "tool";\n        app = build { src = ./app; };'),
    )
    (repo / "skills" / "mermaid" / "SKILL.md").write_text("---\nname: mermaid\n---\nMy way.\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "my changes")
    return repo


def _run(repo: Path, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    """Run the script with a `nix` that only records the call and writes a lock."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    nix = bin_dir / "nix"
    nix.write_text('#!/bin/sh\necho "$*" > "$NIX_CALLS"\necho "{}" > skills/flake.lock\n')
    nix.chmod(0o755)
    env = os.environ | _ENV | {"PATH": f"{bin_dir}:{os.environ['PATH']}", "NIX_CALLS": str(tmp_path / "calls")}
    return subprocess.run(["sh", str(SCRIPT)], cwd=repo / "skills", capture_output=True, text=True, env=env)


def test_an_existing_repo_gets_its_skills_listed(repo: Path, tmp_path: Path) -> None:
    result = _run(repo, tmp_path)

    assert result.returncode == 0, result.stderr
    flake = (repo / "skills" / "flake.nix").read_text()
    # The untouched bundled copy becomes an input on carapace; the changed one stays.
    assert 'artifacts = {\n      url = "github:thiesgerken/carapace?dir=src/carapace/assets/skills/artifacts";' in flake
    assert not (repo / "skills" / "artifacts").exists()
    assert 'mermaid = {\n      url = "path:./mermaid";' in flake
    assert 'notes = {\n      url = "path:./notes";' in flake
    assert '# drafts = {\n    #   url = "path:./drafts";' in flake
    # Copies changed only in their configuration become inputs; ferret's description changed too, so it stays.
    bundled = 'url = "github:thiesgerken/carapace?dir=src/carapace/assets/skills'
    assert f'carapace-cli = {{\n      {bundled}/carapace";' in flake
    assert f'web = {{\n      {bundled}/web";' in flake
    assert 'ferret = {\n      url = "path:./ferret";' in flake
    assert not (repo / "skills" / "carapace").exists() and not (repo / "skills" / "web").exists()
    assert "skills/ferret: you changed more than its configuration" in result.stdout
    assert flake.count('inputs.carapace.follows = "carapace";') == 8
    # Skills without a flake get one; a flake without src gets it.
    assert 'name = "notes";\n          src = ./.;' in (repo / "skills" / "notes" / "flake.nix").read_text()
    assert (repo / "skills" / "mermaid" / "flake.nix").is_file()
    assert 'name = "ferret";\n        src = ./.;' in (repo / "skills" / "ferret" / "flake.nix").read_text()
    assert 'name = "tool";\n        src = ./.;' in (repo / "skills" / "tool" / "flake.nix").read_text()
    assert (tmp_path / "calls").read_text() == "flake lock ./skills\n"
    staged = _git(repo, "diff", "--cached", "--name-status")
    assert "D\tskills/artifacts/SKILL.md" in staged and "A\tskills/flake.lock" in staged
    assert "A\tskills/config.json" in staged
    # Their configuration moved from the flakes; web was disabled, so it stays off with its binding.
    assert json.loads((repo / "skills" / "config.json").read_text()) == {
        "carapace-cli": {
            "credentials": {"CARAPACE_API_KEY": "bw/carapace-key"},
            "enable": True,
            "settings": {"CARAPACE_HOST": "carapace.home.test"},
        },
        "ferret": {
            "credentials": {"FERRET_API_KEY": "vault/ferret-api-key"},
            "enable": True,
            "settings": {"FERRET_URL": "https://ferret.home.test/mcp"},
        },
        "web": {"credentials": {"BRAVE_API_KEY": "vault/brave-api-key"}, "enable": False},
    }
    assert "carapace.lib.skillsFlake {" in flake


def test_a_repo_that_has_a_skills_flake_is_left_alone(repo: Path, tmp_path: Path) -> None:
    (repo / "skills" / "flake.nix").write_text("mine\n")

    result = _run(repo, tmp_path)

    assert result.returncode == 1
    assert "exists already" in result.stderr
    assert (repo / "skills" / "flake.nix").read_text() == "mine\n"


def test_a_directory_that_cannot_be_an_attribute_stops_it_before_any_change(repo: Path, tmp_path: Path) -> None:
    _skill(repo, "nixpkgs")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "a skill named nixpkgs")

    result = _run(repo, tmp_path)

    assert result.returncode == 1
    assert "nixpkgs is reserved" in result.stderr
    assert _git(repo, "status", "--porcelain") == ""


def test_uncommitted_changes_under_skills_stop_it(repo: Path, tmp_path: Path) -> None:
    (repo / "skills" / "notes" / "SKILL.md").write_text("work in progress\n")

    result = _run(repo, tmp_path)

    assert result.returncode == 1
    assert "uncommitted changes" in result.stderr
    assert not (repo / "skills" / "flake.nix").exists()


def test_the_bundled_skills_it_replaces_are_the_inputs_of_the_seeded_flake() -> None:
    script = SCRIPT.read_text()
    seeded = (ROOT / "src" / "carapace" / "assets" / "skills" / "flake.nix").read_text()

    # Together the two lists are what the seed takes from carapace.
    lists = [re.search(rf'^{name}="([^"]*)"$', script, re.M) for name in ("FROM_CARAPACE", "CONFIGURED")]
    names = " ".join(found.group(1) for found in lists if found).split()
    assert all(lists)
    assert sorted(names) == sorted(
        re.findall(r'url = "github:thiesgerken/carapace\?dir=src/carapace/assets/skills/([a-z-]+)";', seeded)
    )


def test_a_bundled_copy_left_at_its_placeholders_is_off(repo: Path, tmp_path: Path) -> None:
    carapace_flake = repo / "skills" / "carapace" / "flake.nix"
    carapace_flake.write_text(_bundled_flake("carapace"))
    _git(repo, "commit", "-qam", "back to the placeholders")

    result = _run(repo, tmp_path)

    assert result.returncode == 0, result.stderr
    assert json.loads((repo / "skills" / "config.json").read_text())["carapace-cli"] == {"enable": False}
    assert "skills/carapace: not configured yet" in result.stdout
