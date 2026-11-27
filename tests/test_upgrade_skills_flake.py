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
# carapace, web and ferret as the last release shipped them, configuration lines and all.
_RELEASE = Path(__file__).parent / "fixtures" / "release-v0.199.0"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True, env=os.environ | _ENV
    ).stdout


def _released(repo: Path, name: str) -> None:
    directory = repo / "skills" / name
    directory.mkdir(parents=True)
    for source in (_RELEASE / name).iterdir():
        (directory / source.name).write_text(source.read_text())


def _edit(repo: Path, path: str, old: str, new: str) -> None:
    file = repo / "skills" / path
    text = file.read_text()
    assert old in text
    file.write_text(text.replace(old, new))


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
    for name in ("carapace", "web", "ferret"):
        _released(repo, name)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", BOOTSTRAP)
    # Configured in its flake, as the release asked; nothing else changed.
    _edit(repo, "carapace/flake.nix", '"carapace.example.com"', '"carapace.home.test"')
    _edit(repo, "carapace/flake.nix", '"<backend>/<your-carapace-api-key-id>"', '"bw/carapace-key"')
    # Set up as SETUP.md said: endpoint in the flake, turned on, and the sources in the description.
    _edit(repo, "ferret/flake.nix", "ferret.example.invalid", "ferret.home.test")
    _edit(repo, "ferret/SKILL.md", "X, Y, Z", "mail and notes")
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
    assert "skills/ferret: stays a local skill, because you changed more than its configuration." in result.stdout
    # Its flake declares no settings yet, so config.json only turns it off; the values are printed instead.
    assert (
        '"ferret": {"credentials": {"FERRET_API_KEY": "vault/ferret-api-key"}, "settings": {"FERRET_URL": "https://ferret.home.test/mcp"}}'
        in result.stdout
    )
    assert flake.count('inputs.carapace.follows = "carapace";') == 8
    # Skills without a flake get one; a flake without src gets it.
    assert 'name = "notes";\n          src = ./.;' in (repo / "skills" / "notes" / "flake.nix").read_text()
    assert (repo / "skills" / "mermaid" / "flake.nix").is_file()
    assert "src = ./.;" in (repo / "skills" / "ferret" / "flake.nix").read_text()
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
        "ferret": {"enable": False},
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


def _bootstrapped(tmp_path: Path) -> Path:
    """Only the three configured skills, as the last release seeded them."""
    repo = tmp_path / "knowledge"
    repo.mkdir()
    _git(repo, "init", "-q")
    for name in ("carapace", "web", "ferret"):
        _released(repo, name)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", BOOTSTRAP)
    return repo


def _config(repo: Path) -> dict[str, object]:
    return json.loads((repo / "skills" / "config.json").read_text())


def test_a_bundled_copy_left_at_its_placeholders_is_off(tmp_path: Path) -> None:
    repo = _bootstrapped(tmp_path)

    result = _run(repo, tmp_path)

    assert result.returncode == 0, result.stderr
    assert _config(repo)["carapace-cli"] == {"enable": False}
    assert "skills/carapace: not configured yet (missing: CARAPACE_HOST CARAPACE_API_KEY)" in result.stdout


def test_ferret_configured_in_its_flake_becomes_an_input_with_its_endpoint(tmp_path: Path) -> None:
    repo = _bootstrapped(tmp_path)
    # The first `url =` of its flake is the carapace input's; the endpoint is the second.
    _edit(repo, "ferret/flake.nix", "ferret.example.invalid", "ferret.home.test")
    _edit(repo, "ferret/SKILL.md", "metadata:\n  carapace:\n    disabled: true\n", "")
    _git(repo, "commit", "-qam", "set up ferret")

    result = _run(repo, tmp_path)

    assert result.returncode == 0, result.stderr
    assert not (repo / "skills" / "ferret").exists()
    assert _config(repo)["ferret"] == {
        "credentials": {"FERRET_API_KEY": "vault/ferret-api-key"},
        "enable": True,
        "settings": {"FERRET_URL": "https://ferret.home.test/mcp"},
    }


def test_a_value_it_cannot_read_keeps_the_copy(tmp_path: Path) -> None:
    repo = _bootstrapped(tmp_path)
    _edit(repo, "carapace/flake.nix", 'server = "carapace.example.com";', 'server = "carapace" + ".home.test";')
    _git(repo, "commit", "-qam", "computed server")

    result = _run(repo, tmp_path)

    assert result.returncode == 0, result.stderr
    assert (repo / "skills" / "carapace" / "flake.nix").is_file()
    assert _config(repo)["carapace-cli"] == {"enable": False}
    assert "flake.nix does not have these lines as shipped: server." in result.stdout


def test_changes_that_a_reset_undid_do_not_count(tmp_path: Path) -> None:
    repo = _bootstrapped(tmp_path)
    original = (repo / "skills" / "web" / "SKILL.md").read_text()
    _edit(repo, "web/SKILL.md", "Search the web", "Search the whole web")
    _git(repo, "commit", "-qam", "my wording")
    (repo / "skills" / "web" / "SKILL.md").write_text(original)
    _git(repo, "commit", "-qam", BOOTSTRAP)

    result = _run(repo, tmp_path)

    assert result.returncode == 0, result.stderr
    assert not (repo / "skills" / "web").exists()
    assert _config(repo)["web"] == {"credentials": {"BRAVE_API_KEY": "vault/brave-api-key"}, "enable": False}


def test_a_copy_from_before_skill_flakes_becomes_the_input(tmp_path: Path) -> None:
    repo = _bootstrapped(tmp_path)
    (repo / "skills" / "carapace" / "flake.nix").unlink()
    _git(repo, "commit", "-qam", "a pre-flake copy has no flake")

    result = _run(repo, tmp_path)

    assert result.returncode == 0, result.stderr
    assert not (repo / "skills" / "carapace").exists()
    assert _config(repo)["carapace-cli"] == {"enable": False}
    assert not list((repo / "skills").glob("**/*.new"))
