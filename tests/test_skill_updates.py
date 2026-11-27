"""Update checks: an external skill whose upstream moved has an update, a local one with a stale lock is outdated."""

from __future__ import annotations

import copy
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, cast

import httpx
import pytest

from carapace.builder.client import BuilderClient
from carapace.builder.models import InputUpdate, UpdatedLocks
from carapace.builder.skill_updates import (
    SkillUpdate,
    SkillUpdates,
    UpdateRefusedError,
    _resolved,
    compare,
    describe_source,
    graft,
)
from carapace.git.store import ConcurrentChangeError, GitStore
from carapace.skills import ListedSkill
from tests.skills_flake import write_skills_flake

_OLD_REV, _NEW_REV = "a" * 40, "b" * 40


def _lock() -> dict[str, Any]:
    """A lock with a local skill (its own input followed) and an external one with a transitive input."""
    return {
        "nodes": {
            "root": {"inputs": {"nixpkgs": "nixpkgs", "carapace": "carapace", "notes": "notes", "tracker": "tracker"}},
            "nixpkgs": {"locked": {"type": "github", "owner": "NixOS", "repo": "nixpkgs", "rev": "0" * 40}},
            "carapace": {"locked": {"type": "github", "owner": "thiesgerken", "repo": "carapace", "rev": "1" * 40}},
            "notes": {
                "inputs": {"nixpkgs": ["nixpkgs"], "carapace": ["carapace"]},
                "locked": {"type": "path", "path": "./notes"},
                "original": {"type": "path", "path": "./notes"},
                "parent": [],
            },
            "tracker": {
                "inputs": {"nixpkgs": ["nixpkgs"], "utils": "utils"},
                "locked": {
                    "type": "github",
                    "owner": "someone",
                    "repo": "tracker",
                    "rev": _OLD_REV,
                    "lastModified": 1_790_000_000,
                },
                "original": {"type": "github", "owner": "someone", "repo": "tracker"},
            },
            "utils": {"locked": {"type": "github", "owner": "numtide", "repo": "flake-utils", "rev": "3" * 40}},
        },
        "root": "root",
        "version": 7,
    }


def test_an_unchanged_input_is_current() -> None:
    assert compare("tracker", _lock(), _lock()) == SkillUpdate(state="current")
    assert compare("notes", _lock(), _lock()) == SkillUpdate(state="current")


def test_a_moved_upstream_is_an_available_update() -> None:
    updated = _lock()
    updated["nodes"]["tracker"]["locked"] |= {"rev": _NEW_REV, "lastModified": 1_795_000_000}

    update = compare("tracker", _lock(), updated)

    assert update.state == "available"
    assert (update.available_rev, update.available_at) == (_NEW_REV, datetime.fromtimestamp(1_795_000_000, UTC))
    assert compare("notes", _lock(), updated).state == "current", "only the input that moved"


def test_a_local_skill_with_a_new_input_is_outdated() -> None:
    updated = _lock()
    updated["nodes"]["notes"]["inputs"]["utils"] = "utils_2"
    updated["nodes"]["utils_2"] = {"locked": {"type": "github", "owner": "numtide", "repo": "flake-utils"}}

    update = compare("notes", _lock(), updated)

    assert update.state == "outdated"
    assert "`nix flake update notes --flake ./skills`" in update.detail


def test_renamed_nodes_compare_by_content() -> None:
    updated = copy.deepcopy(_lock())
    nodes = updated["nodes"]
    nodes["utils_2"] = nodes.pop("utils")
    nodes["tracker"]["inputs"]["utils"] = "utils_2"

    assert compare("tracker", _lock(), updated).state == "current"


def test_a_moved_transitive_input_is_an_update_of_its_skill() -> None:
    updated = _lock()
    updated["nodes"]["utils"]["locked"]["rev"] = "4" * 40

    assert compare("tracker", _lock(), updated).state == "available"


def test_a_graft_takes_only_the_one_skill_from_the_updated_lock() -> None:
    updated = _lock()
    # The update moved tracker and its own input, whose node Nix named differently this time ...
    updated["nodes"]["tracker"]["locked"]["rev"] = _NEW_REV
    updated["nodes"]["tracker"]["inputs"]["utils"] = "utils_2"
    updated["nodes"]["utils_2"] = {
        "locked": {"type": "github", "owner": "numtide", "repo": "flake-utils", "rev": "4" * 40}
    }
    del updated["nodes"]["utils"]
    # ... and re-locked notes, whose flake.nix gained an input, along the way.
    updated["nodes"]["notes"]["inputs"]["extra"] = "extra"
    updated["nodes"]["extra"] = {"locked": {"type": "github", "owner": "x", "repo": "extra", "rev": "5" * 40}}

    grafted = graft(_lock(), updated, "tracker")

    assert _resolved(grafted, "tracker") == _resolved(updated, "tracker")
    assert _resolved(grafted, "notes") == _resolved(_lock(), "notes")
    # The old utils node is gone, nothing dangles: every node is reachable from the root.
    assert set(grafted["nodes"]) == {"root", "nixpkgs", "carapace", "notes", "tracker", "utils_2"}


def test_a_graft_keeps_an_id_another_input_still_uses() -> None:
    current = _lock()
    current["nodes"]["notes"]["inputs"]["utils"] = "utils"
    updated = copy.deepcopy(current)
    updated["nodes"]["tracker"]["locked"]["rev"] = _NEW_REV
    updated["nodes"]["utils"]["locked"]["rev"] = "4" * 40

    grafted = graft(current, updated, "tracker")

    assert _resolved(grafted, "tracker") == _resolved(updated, "tracker")
    assert _resolved(grafted, "notes") == _resolved(current, "notes")


def _listed(name: str, *, local: bool) -> ListedSkill:
    if local:
        return ListedSkill(
            name=name, directory=PurePosixPath(name), origin=f"./{name}", locked_rev=None, locked_at=None
        )
    at = datetime(2026, 11, 1, tzinfo=UTC)
    return ListedSkill(name=name, directory=None, origin=f"github:someone/{name}", locked_rev=_OLD_REV, locked_at=at)


def test_the_agent_reads_origin_rev_and_verdict() -> None:
    tracker, notes = _listed("tracker", local=False), _listed("notes", local=True)
    available = SkillUpdate(state="available", available_rev=_NEW_REV, available_at=datetime(2026, 11, 20, tzinfo=UTC))

    assert describe_source(notes, None) == "From ./notes (local)."
    assert describe_source(tracker, None) == "From github:someone/tracker, locked at aaaaaaa (2026-11-01)."
    assert describe_source(tracker, available) == (
        "From github:someone/tracker, locked at aaaaaaa (2026-11-01). An update is available: bbbbbbb (2026-11-20); "
        "`nix flake update tracker --flake ./skills` takes it."
    )
    outdated = SkillUpdate(state="outdated", detail="run it")
    assert describe_source(notes, outdated) == "From ./notes (local). Outdated: run it"
    assert describe_source(notes, SkillUpdate(state="failed", detail="log")).endswith(
        "The last update check failed for it."
    )


class FakeBuilder:
    def __init__(self, answer: dict[str, InputUpdate] | Exception) -> None:
        self.answer = answer
        self.asked: list[list[str]] = []

    async def check_updates(self, archive: bytes, inputs: list[str]) -> UpdatedLocks:
        self.asked.append(inputs)
        if isinstance(self.answer, Exception):
            raise self.answer
        return UpdatedLocks(inputs=self.answer)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    (tmp_path / "skills" / "notes").mkdir(parents=True)
    (tmp_path / "skills" / "notes" / "flake.nix").write_text("{ outputs = _: { }; }\n")
    write_skills_flake(tmp_path / "skills", ["notes"], external=["tracker"])
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", "skills")
    return tmp_path


async def _checked(updates: SkillUpdates, repo: Path) -> None:
    updates.start(repo)
    await updates.wait(repo)


@pytest.mark.anyio
async def test_a_check_asks_the_builder_about_every_skill_and_compares_each(repo: Path) -> None:
    lock = json.loads((repo / "skills" / "flake.lock").read_text())
    moved = copy.deepcopy(lock)
    moved["nodes"]["tracker"]["locked"]["rev"] = _NEW_REV
    builder = FakeBuilder({"notes": InputUpdate(lock=json.dumps(lock)), "tracker": InputUpdate(lock=json.dumps(moved))})
    updates = SkillUpdates(cast(BuilderClient, builder))

    await _checked(updates, repo)

    check = updates.latest(repo)
    assert check is not None and not updates.running(repo)
    assert builder.asked == [["notes", "tracker"]]
    assert check.skills_tree == _git(repo, "rev-parse", "HEAD:skills")
    assert {name: update.state for name, update in check.skills.items()} == {"notes": "current", "tracker": "available"}


@pytest.mark.anyio
async def test_an_input_the_builder_could_not_update_fails_alone(repo: Path) -> None:
    lock = (repo / "skills" / "flake.lock").read_text()
    builder = FakeBuilder({"notes": InputUpdate(lock=lock), "tracker": InputUpdate(log_tail="error: 404")})
    updates = SkillUpdates(cast(BuilderClient, builder))

    await _checked(updates, repo)

    check = updates.latest(repo)
    assert check is not None
    assert check.skills["notes"].state == "current"
    assert check.skills["tracker"] == SkillUpdate(state="failed", detail="error: 404")


@pytest.mark.anyio
async def test_an_unreachable_builder_is_the_checks_error(repo: Path) -> None:
    updates = SkillUpdates(cast(BuilderClient, FakeBuilder(httpx.ConnectError("builder down"))))

    await _checked(updates, repo)

    check = updates.latest(repo)
    assert check is not None and check.skills == {}
    assert "builder down" in check.error


@pytest.mark.anyio
async def test_without_a_builder_the_check_says_so(repo: Path) -> None:
    updates = SkillUpdates(None)

    await _checked(updates, repo)

    check = updates.latest(repo)
    assert check is not None and "CARAPACE_BUILDER_URL" in check.error


@pytest.mark.anyio
async def test_a_repo_without_skills_flake_has_no_check(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-q")
    updates = SkillUpdates(cast(BuilderClient, FakeBuilder({})))

    await _checked(updates, tmp_path)

    assert updates.latest(tmp_path) is None


async def _available(repo: Path) -> SkillUpdates:
    """A check that found tracker moved; the builder's lock also re-locked notes, as Nix does."""
    lock = json.loads((repo / "skills" / "flake.lock").read_text())
    updated = copy.deepcopy(lock)
    updated["nodes"]["tracker"]["locked"]["rev"] = _NEW_REV
    updated["nodes"]["notes"]["inputs"] = {"extra": "extra"}
    updated["nodes"]["extra"] = {"locked": {"type": "github", "owner": "x", "repo": "extra", "rev": "5" * 40}}
    answer = {"notes": InputUpdate(lock=json.dumps(lock)), "tracker": InputUpdate(lock=json.dumps(updated))}
    updates = SkillUpdates(cast(BuilderClient, FakeBuilder(answer)))
    await _checked(updates, repo)
    return updates


@pytest.mark.anyio
async def test_applying_an_update_commits_only_that_skill_as_the_user(repo: Path) -> None:
    _git(repo, "config", "user.name", "carapace")
    _git(repo, "config", "user.email", "carapace@example.com")
    before = json.loads((repo / "skills" / "flake.lock").read_text())
    updates = await _available(repo)

    pending = await updates.pending_update(repo, "tracker")
    await GitStore(repo).commit_replacing(
        "skills/flake.lock",
        pending.lock_text,
        expected_blob=pending.base_lock,
        message=pending.message,
        author="Demo User <demo@example.com>",
    )

    after = json.loads(_git(repo, "show", "HEAD:skills/flake.lock"))
    assert after["nodes"]["tracker"]["locked"]["rev"] == _NEW_REV
    assert {k: v for k, v in after["nodes"].items() if k != "tracker"} == {
        k: v for k, v in before["nodes"].items() if k != "tracker"
    }
    assert (
        _git(repo, "log", "-1", "--format=%an <%ae>|%s")
        == f"Demo User <demo@example.com>|⬆️ skills: update tracker to {_NEW_REV[:7]}"
    )
    assert _git(repo, "status", "--porcelain") == ""


@pytest.mark.anyio
async def test_a_lock_that_changed_after_the_check_is_not_overwritten(repo: Path) -> None:
    updates = await _available(repo)
    pending = await updates.pending_update(repo, "tracker")
    # A push lands between preparing the update and committing it.
    (repo / "skills" / "flake.lock").write_text("{}\n")
    _git(repo, "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qam", "relock")

    with pytest.raises(ConcurrentChangeError):
        await GitStore(repo).commit_replacing(
            "skills/flake.lock",
            pending.lock_text,
            expected_blob=pending.base_lock,
            message=pending.message,
            author="Demo User <demo@example.com>",
        )

    assert _git(repo, "log", "-1", "--format=%s") == "relock"
    assert _git(repo, "status", "--porcelain") == ""
    # And once HEAD's skills/ moved on, the old check no longer offers the update at all.
    with pytest.raises(UpdateRefusedError, match="check for updates again"):
        await updates.pending_update(repo, "tracker")


@pytest.mark.anyio
async def test_only_an_available_update_can_be_applied(repo: Path) -> None:
    updates = await _available(repo)

    with pytest.raises(UpdateRefusedError, match="no update for notes"):
        await updates.pending_update(repo, "notes")
