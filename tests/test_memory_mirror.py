from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from carapace.git.store import GitStore
from carapace.knowledge import KnowledgeRepoHandle
from carapace.memory.handlers import MirrorHandler
from carapace.memory.models import (
    DigestRecord,
    ExtractionRecord,
    MemoryTask,
    MirrorResult,
    SpawnedBy,
    TaskKind,
    TaskStatus,
)
from carapace.memory.render import render_mirror
from carapace.skills import SkillRegistry
from tests.memory_fixtures import EXTRACTION, MONTH, WEEK

TASK = MemoryTask(
    id=11,
    user="alice",
    kind=TaskKind.mirror,
    target="alice",
    status=TaskStatus.running,
    spawned_by=SpawnedBy.auto,
    created_at=datetime(2026, 9, 8, tzinfo=UTC),
)


class _Mirror:
    def __init__(self, knowledge_dir: Path) -> None:
        self.knowledge_dir = knowledge_dir
        self.git_store = GitStore(knowledge_dir)
        self.extractions: list[ExtractionRecord] = [EXTRACTION]
        self.digests: list[DigestRecord] = [WEEK, MONTH]
        self.pushes: list[str] = []
        handle = KnowledgeRepoHandle(
            owner="alice",
            knowledge_dir=knowledge_dir,
            git_store=self.git_store,
            skill_registry=SkillRegistry(knowledge_dir / "skills"),
        )
        self.handler = MirrorHandler(
            current_extractions=lambda user: self.extractions,
            current_digests=lambda user, level: [d for d in self.digests if d.level is level],
            knowledge_repo_for_user=lambda user: handle,
            push_if_configured=self._push,
        )

    async def _push(self, user: str) -> None:
        self.pushes.append(user)

    async def run(self) -> str | None:
        outcome = await self.handler.run(TASK, None)
        assert outcome.provenance is None
        assert isinstance(outcome.result, MirrorResult)
        return outcome.result.commit

    def files(self) -> dict[str, str]:
        root = self.knowledge_dir / "memory"
        return {p.relative_to(self.knowledge_dir).as_posix(): p.read_text() for p in root.rglob("*") if p.is_file()}

    async def git(self, *args: str) -> str:
        code, out = await self.git_store._run(*args)
        assert code == 0, out
        return out


@pytest.fixture
def mirror(tmp_path: Path) -> _Mirror:
    return _Mirror(tmp_path / "knowledge")


async def test_first_run_writes_and_commits_everything(mirror: _Mirror) -> None:
    commit = await mirror.run()

    assert mirror.files() == render_mirror([EXTRACTION], [WEEK, MONTH])
    assert commit == await mirror.git("rev-parse", "HEAD")
    assert await mirror.git("status", "--porcelain") == ""
    assert mirror.pushes == ["alice"]


async def test_unchanged_records_make_no_commit(mirror: _Mirror) -> None:
    await mirror.run()

    assert await mirror.run() is None
    assert await mirror.git("rev-list", "--count", "HEAD") == "1"
    assert mirror.pushes == ["alice"]


async def test_removed_records_delete_their_files_in_one_commit(mirror: _Mirror) -> None:
    await mirror.run()
    mirror.extractions = []
    mirror.digests = [WEEK]

    commit = await mirror.run()

    assert commit is not None
    assert sorted(mirror.files()) == ["memory/README.md", "memory/weeks/2026-W36.md"]
    assert not (mirror.knowledge_dir / "memory" / "sessions").exists()
    assert not (mirror.knowledge_dir / "memory" / "months").exists()
    assert await mirror.git("status", "--porcelain") == ""
    changed = await mirror.git("show", "--name-status", "--format=", "HEAD")
    # The week file changes too: its session ref is no longer a link.
    assert sorted(changed.splitlines()) == [
        "D\tmemory/months/2026-09.md",
        "D\tmemory/sessions/2026/09/s-talos.md",
        "M\tmemory/weeks/2026-W36.md",
    ]


async def test_pushed_edits_inside_the_mirror_are_reverted_and_outside_untouched(mirror: _Mirror) -> None:
    await mirror.run()
    (mirror.knowledge_dir / "memory" / "README.md").write_text("edited by the agent")
    (mirror.knowledge_dir / "memory" / "notes.md").write_text("stray")
    await mirror.git("add", "memory")
    await mirror.git("commit", "-m", "agent edit")
    (mirror.knowledge_dir / "USER.md").write_text("not ours")

    assert await mirror.run() is not None

    assert mirror.files() == render_mirror([EXTRACTION], [WEEK, MONTH])
    assert await mirror.git("status", "--porcelain") == "?? USER.md"


async def test_symlinks_in_the_mirror_are_removed_not_followed(mirror: _Mirror, tmp_path: Path) -> None:
    await mirror.run()
    outside = tmp_path / "outside.md"
    outside.write_text("secret")
    session_file = mirror.knowledge_dir / "memory" / "sessions" / "2026" / "09" / "s-talos.md"
    session_file.unlink()
    session_file.symlink_to(outside)
    (mirror.knowledge_dir / "memory" / "weeks-link").symlink_to(tmp_path, target_is_directory=True)

    await mirror.run()

    assert outside.read_text() == "secret"
    assert not session_file.is_symlink()
    assert not (mirror.knowledge_dir / "memory" / "weeks-link").exists()
    assert mirror.files() == render_mirror([EXTRACTION], [WEEK, MONTH])


async def test_mirror_root_symlink_is_replaced(mirror: _Mirror, tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    mirror.knowledge_dir.mkdir(parents=True)
    (mirror.knowledge_dir / "memory").symlink_to(elsewhere, target_is_directory=True)

    await mirror.run()

    assert list(elsewhere.iterdir()) == []
    assert not (mirror.knowledge_dir / "memory").is_symlink()
    assert mirror.files() == render_mirror([EXTRACTION], [WEEK, MONTH])


async def test_mirror_runs_without_model_and_is_never_estimated(mirror: _Mirror) -> None:
    with pytest.raises(ValueError, match="without a model"):
        await mirror.handler.run(TASK, "anthropic:claude-haiku-4-5")
    with pytest.raises(ValueError, match="never estimated"):
        await mirror.handler.estimate("alice", "alice", "anthropic:claude-haiku-4-5")


async def test_uncommitted_edits_are_restored_without_a_commit(mirror: _Mirror) -> None:
    await mirror.run()
    (mirror.knowledge_dir / "memory" / "README.md").write_text("edited")

    assert await mirror.run() is None
    assert await mirror.git("status", "--porcelain") == ""


async def test_files_written_by_a_crashed_run_are_committed_by_the_next(
    mirror: _Mirror, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def crash(*args: object, **kwargs: object) -> str | None:
        raise RuntimeError("git commit failed")

    with monkeypatch.context() as patch:
        patch.setattr(mirror.git_store, "commit_returning_sha", crash)
        with pytest.raises(RuntimeError):
            await mirror.run()
    assert mirror.files() == render_mirror([EXTRACTION], [WEEK, MONTH])

    commit = await mirror.run()

    assert commit == await mirror.git("rev-parse", "HEAD")
    assert await mirror.git("status", "--porcelain") == ""
    assert mirror.pushes == ["alice"]
