from __future__ import annotations

import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from carapace.git.store import GitStore
from carapace.models.git import SessionArtifactChange


def _git(repo: Path, *args: str, env: dict[str, str] | None = None) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        env={**os.environ, **(env or {})},
    )


def _commit(repo: Path, message: str, at: int, session: str | None) -> None:
    trailer = ["-m", f"carapace-session: {session}"] if session else []
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", message, *trailer, env={"GIT_COMMITTER_DATE": f"@{at} +0000"})


def _write(repo: Path, path: str) -> None:
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f"<title>{path}</title>", encoding="utf-8")


@pytest.mark.anyio
async def test_lists_the_artifacts_the_session_committed_newest_first(tmp_path: Path) -> None:
    repo = tmp_path
    _git(repo, "init", "-b", "main")
    _write(repo, "artifacts/old/index.html")
    _commit(repo, "Someone else's artifact", 100, "other")
    _write(repo, "artifacts/draft/index.html")
    _write(repo, "artifacts/draft/notes.txt")
    _commit(repo, "Add draft", 200, "s1")
    _git(repo, "mv", "artifacts/draft", "artifacts/report")
    (repo / "artifacts/old/index.html").write_text("<title>changed</title>", encoding="utf-8")
    _commit(repo, "Rename draft, touch old", 300, "s1")
    _write(repo, "artifacts/longer-session/index.html")
    _commit(repo, "A session whose ID starts with s1", 400, "s1-2")
    _write(repo, "notes/s1.md")
    _commit(repo, "Not an artifact", 500, "s1")

    changes = await GitStore(repo).session_artifact_changes("s1")

    at = lambda seconds: datetime.fromtimestamp(seconds, tz=UTC)  # noqa: E731
    # Renames count as a deletion plus a creation; only index.html makes an artifact change.
    assert changes == [
        SessionArtifactChange(slug="draft", created=True, last_changed=at(300)),
        SessionArtifactChange(slug="old", created=False, last_changed=at(300)),
        SessionArtifactChange(slug="report", created=True, last_changed=at(300)),
    ]


@pytest.mark.anyio
async def test_an_empty_repo_has_no_session_artifacts(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-b", "main")

    assert await GitStore(tmp_path).session_artifact_changes("s1") == []
