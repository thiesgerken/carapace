from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from carapace.git.store import GitStore
from carapace.knowledge import KnowledgeRepoHandle
from carapace.models.config import SessionCommitConfig
from carapace.models.session import SessionFork
from carapace.session.archive import SessionArchiveService
from carapace.session.manager import SessionManager


def _repo_handle(knowledge_dir: Path, *, git_store: GitStore, owner: str = "thies") -> KnowledgeRepoHandle:
    return KnowledgeRepoHandle(
        owner=owner,
        knowledge_dir=knowledge_dir,
        git_store=git_store,
        skill_registry=MagicMock(),
    )


def _archive_service(
    session_mgr: SessionManager,
    *,
    knowledge_dir: Path,
    git_store: GitStore,
    config: SessionCommitConfig | None = None,
    owner: str = "thies",
    repo_handle: KnowledgeRepoHandle | None = None,
) -> SessionArchiveService:
    handle = repo_handle or _repo_handle(knowledge_dir, git_store=git_store, owner=owner)
    return SessionArchiveService(
        session_mgr=session_mgr,
        config=config if config is not None else SessionCommitConfig(),
        knowledge_repo_for_session=lambda _session_id: handle,
    )


def test_append_events_stamps_timestamp(tmp_path, db_factory) -> None:
    mgr = SessionManager(db_factory, tmp_path)
    state = mgr.create_session(user="thies")

    mgr.append_events(state.session_id, [{"role": "user", "content": "hello"}])

    events = mgr.load_events(state.session_id)
    assert len(events) == 1
    assert isinstance(events[0].get("timestamp"), str)


@pytest.mark.asyncio
async def test_archive_service_commits_snapshot(tmp_path, db_factory) -> None:
    mgr = SessionManager(db_factory, tmp_path)
    state = mgr.create_session(user="thies", private=False)
    mgr.append_events(
        state.session_id,
        [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "world"},
        ],
    )
    git_store = MagicMock(spec=GitStore)
    git_store.commit = AsyncMock(return_value=True)
    service = _archive_service(mgr, knowledge_dir=tmp_path, git_store=git_store)

    result = await service.commit_session(state.session_id, trigger="manual")

    assert result.committed is True
    assert result.archive_path is not None
    archive_file = tmp_path / result.archive_path
    assert archive_file.is_file()
    payload = json.loads(archive_file.read_text())
    assert payload["session"]["session_id"] == state.session_id
    assert payload["history"][0]["role"] == "user"
    assert "timestamp" in payload["history"][0]
    git_store.commit.assert_awaited_once_with(
        [result.archive_path],
        f"💾 session: add {state.session_id}",
        session_id=state.session_id,
    )


@pytest.mark.asyncio
async def test_archive_records_fork_origin_only_for_forks(tmp_path, db_factory) -> None:
    mgr = SessionManager(db_factory, tmp_path)
    source = mgr.create_session(user="thies")
    fork = mgr.create_session(user="thies")
    fork.forked_from = SessionFork(session_id=source.session_id, event_count=2)
    mgr.save_state(fork)
    for state in (source, fork):
        mgr.append_events(
            state.session_id,
            [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "world"}],
        )
    git_store = MagicMock(spec=GitStore)
    git_store.commit = AsyncMock(return_value=True)
    service = _archive_service(mgr, knowledge_dir=tmp_path, git_store=git_store)

    source_result = await service.commit_session(source.session_id, trigger="manual")
    fork_result = await service.commit_session(fork.session_id, trigger="manual")

    assert source_result.archive_path is not None and fork_result.archive_path is not None
    source_payload = json.loads((tmp_path / source_result.archive_path).read_text())
    fork_payload = json.loads((tmp_path / fork_result.archive_path).read_text())
    assert "forked_from" not in source_payload["session"]
    assert fork_payload["session"]["forked_from"] == {"session_id": source.session_id, "event_count": 2}


@pytest.mark.asyncio
async def test_archive_service_routes_snapshot_to_owner_specific_repo(tmp_path, db_factory) -> None:
    mgr = SessionManager(db_factory, tmp_path)
    state = mgr.create_session(user="ada", private=False)
    mgr.append_events(
        state.session_id,
        [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "world"},
        ],
    )
    owner_git_store = MagicMock(spec=GitStore)
    owner_git_store.commit = AsyncMock(return_value=True)
    owner_handle = KnowledgeRepoHandle(
        owner="ada",
        knowledge_dir=tmp_path / "knowledges" / "ada",
        git_store=owner_git_store,
        skill_registry=MagicMock(),
    )
    service = _archive_service(
        mgr,
        knowledge_dir=owner_handle.knowledge_dir,
        git_store=owner_git_store,
        repo_handle=owner_handle,
    )
    legacy_knowledge_dir = tmp_path / "legacy-knowledge"

    result = await service.commit_session(state.session_id, trigger="manual")

    assert result.committed is True
    assert result.archive_path is not None
    assert (owner_handle.knowledge_dir / result.archive_path).is_file()
    assert not (legacy_knowledge_dir / result.archive_path).exists()
    owner_git_store.commit.assert_awaited_once_with(
        [result.archive_path],
        f"💾 session: add {state.session_id}",
        session_id=state.session_id,
    )


@pytest.mark.asyncio
async def test_archive_service_skips_private_sessions(tmp_path, db_factory) -> None:
    mgr = SessionManager(db_factory, tmp_path)
    state = mgr.create_session(user="thies", private=True)
    mgr.append_events(state.session_id, [{"role": "user", "content": "hello"}])
    git_store = MagicMock(spec=GitStore)
    git_store.commit = AsyncMock(return_value=True)
    service = _archive_service(mgr, knowledge_dir=tmp_path, git_store=git_store)

    result = await service.commit_session(state.session_id, trigger="manual")

    assert result.committed is False
    assert result.reason == "Private sessions cannot be committed to knowledge"


@pytest.mark.asyncio
async def test_archive_service_empty_history_returns_no_archive_path(tmp_path, db_factory) -> None:
    mgr = SessionManager(db_factory, tmp_path)
    state = mgr.create_session(user="thies", private=False)
    git_store = MagicMock(spec=GitStore)
    git_store.commit = AsyncMock(return_value=True)
    service = _archive_service(mgr, knowledge_dir=tmp_path, git_store=git_store)

    result = await service.commit_session(state.session_id, trigger="manual")

    assert result.committed is False
    assert result.archive_path is None
    assert result.reason == "Session has no history to archive yet"


@pytest.mark.asyncio
async def test_archive_service_skips_unchanged_snapshot_for_different_trigger(tmp_path, db_factory) -> None:
    mgr = SessionManager(db_factory, tmp_path)
    state = mgr.create_session(user="thies", private=False)
    mgr.append_events(
        state.session_id,
        [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "world"},
        ],
    )
    git_store = MagicMock(spec=GitStore)
    git_store.commit = AsyncMock(return_value=True)
    service = _archive_service(mgr, knowledge_dir=tmp_path, git_store=git_store)

    first = await service.commit_session(state.session_id, trigger="autosave")
    second = await service.commit_session(state.session_id, trigger="manual")

    assert first.committed is True
    assert second.committed is False
    assert second.reason == "No archive changes to commit"
    assert git_store.commit.await_count == 1


@pytest.mark.asyncio
async def test_archive_service_preserves_concurrent_privacy_update(tmp_path, db_factory) -> None:
    mgr = SessionManager(db_factory, tmp_path)
    state = mgr.create_session(user="thies", private=False)
    mgr.append_events(state.session_id, [{"role": "user", "content": "hello"}])
    git_store = MagicMock(spec=GitStore)

    async def commit_with_concurrent_privacy_flip(*args, **kwargs) -> bool:
        current = mgr.load_state(state.session_id)
        assert current is not None
        current.attributes.private = True
        mgr.save_state(current)
        return True

    git_store.commit = AsyncMock(side_effect=commit_with_concurrent_privacy_flip)
    service = _archive_service(mgr, knowledge_dir=tmp_path, git_store=git_store)

    result = await service.commit_session(state.session_id, trigger="manual")
    final_state = mgr.load_state(state.session_id)

    assert result.committed is True
    assert final_state is not None
    assert final_state.attributes.private is True
    assert final_state.knowledge_last_committed_at is not None


@pytest.mark.asyncio
async def test_archive_service_serializes_same_session_commits(tmp_path, db_factory) -> None:
    mgr = SessionManager(db_factory, tmp_path)
    state = mgr.create_session(user="thies", private=False)
    mgr.append_events(
        state.session_id,
        [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "world"},
        ],
    )
    git_store = MagicMock(spec=GitStore)
    release_commit = asyncio.Event()

    async def delayed_commit(*args, **kwargs) -> bool:
        await release_commit.wait()
        return True

    git_store.commit = AsyncMock(side_effect=delayed_commit)
    service = _archive_service(mgr, knowledge_dir=tmp_path, git_store=git_store)

    first_task = asyncio.create_task(service.commit_session(state.session_id, trigger="manual"))
    await asyncio.sleep(0)
    second_task = asyncio.create_task(service.commit_session(state.session_id, trigger="autosave"))
    await asyncio.sleep(0)
    release_commit.set()

    first = await first_task
    second = await second_task

    assert first.committed is True
    assert second.committed is False
    assert second.reason == "No archive changes to commit"
    assert git_store.commit.await_count == 1


@pytest.mark.asyncio
async def test_archive_service_does_not_persist_export_hash_on_commit_failure(tmp_path, db_factory) -> None:
    mgr = SessionManager(db_factory, tmp_path)
    state = mgr.create_session(user="thies", private=False)
    mgr.append_events(state.session_id, [{"role": "user", "content": "hello"}])
    git_store = MagicMock(spec=GitStore)
    git_store.commit = AsyncMock(side_effect=RuntimeError("git commit failed: boom"))
    service = _archive_service(mgr, knowledge_dir=tmp_path, git_store=git_store)

    with pytest.raises(RuntimeError, match="git commit failed: boom"):
        await service.commit_session(state.session_id, trigger="manual")

    final_state = mgr.load_state(state.session_id)

    assert final_state is not None
    assert final_state.knowledge_last_export_hash is None
    assert final_state.knowledge_last_archive_path is None
    assert final_state.knowledge_last_committed_at is None
    assert service._session_locks == {}


@pytest.mark.asyncio
async def test_archive_service_removes_written_file_after_commit_failure(tmp_path, db_factory) -> None:
    mgr = SessionManager(db_factory, tmp_path)
    state = mgr.create_session(user="thies", private=False)
    mgr.append_events(state.session_id, [{"role": "user", "content": "hello"}])
    git_store = MagicMock(spec=GitStore)
    git_store.commit = AsyncMock(side_effect=RuntimeError("git commit failed: boom"))
    service = _archive_service(mgr, knowledge_dir=tmp_path, git_store=git_store)
    archive_file = service.archive_absolute_path_for_state(state)

    with pytest.raises(RuntimeError, match="git commit failed: boom"):
        await service.commit_session(state.session_id, trigger="manual")

    assert not archive_file.exists()
    assert not archive_file.parent.exists()


@pytest.mark.asyncio
async def test_archive_service_cleans_up_lock_after_archive_delete(tmp_path, db_factory) -> None:
    mgr = SessionManager(db_factory, tmp_path)
    state = mgr.create_session(user="thies", private=False)
    mgr.append_events(state.session_id, [{"role": "user", "content": "hello"}])
    git_store = MagicMock(spec=GitStore)
    git_store.commit = AsyncMock(return_value=True)
    git_store.commit_removals = AsyncMock(return_value=True)
    service = _archive_service(mgr, knowledge_dir=tmp_path, git_store=git_store)

    await service.commit_session(state.session_id, trigger="manual")
    archived_state = mgr.load_state(state.session_id)

    assert archived_state is not None
    assert await service.delete_session_archive(archived_state) is True
    assert service._session_locks == {}
    assert service._session_lock_refs == {}


@pytest.mark.asyncio
async def test_archive_service_uses_update_title_after_first_commit(tmp_path, db_factory) -> None:
    mgr = SessionManager(db_factory, tmp_path)
    state = mgr.create_session(user="thies", private=False)
    mgr.append_events(state.session_id, [{"role": "user", "content": "hello"}])
    git_store = MagicMock(spec=GitStore)
    git_store.commit = AsyncMock(return_value=True)
    service = _archive_service(mgr, knowledge_dir=tmp_path, git_store=git_store)

    first = await service.commit_session(state.session_id, trigger="manual")
    mgr.append_events(state.session_id, [{"role": "assistant", "content": "world"}])
    second = await service.commit_session(state.session_id, trigger="manual")

    assert first.committed is True
    assert second.committed is True
    assert first.archive_path is not None
    assert second.archive_path == first.archive_path
    assert git_store.commit.await_args_list[1].args == (
        [first.archive_path],
        f"💾 session: update {state.session_id}",
    )
    assert git_store.commit.await_args_list[1].kwargs == {"session_id": state.session_id}
