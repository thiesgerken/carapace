from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from carapace.git.store import GitStore
from carapace.models import SessionCommitConfig
from carapace.session.archive import SessionArchiveService
from carapace.session.manager import SessionManager


def test_append_events_stamps_timestamp(tmp_path) -> None:
    mgr = SessionManager(tmp_path)
    state = mgr.create_session()

    mgr.append_events(state.session_id, [{"role": "user", "content": "hello"}])

    events = mgr.load_events(state.session_id)
    assert len(events) == 1
    assert isinstance(events[0].get("timestamp"), str)


@pytest.mark.asyncio
async def test_archive_service_commits_snapshot(tmp_path) -> None:
    mgr = SessionManager(tmp_path)
    state = mgr.create_session(private=False)
    mgr.append_events(
        state.session_id,
        [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "world"},
        ],
    )
    git_store = MagicMock(spec=GitStore)
    git_store.commit = AsyncMock(return_value=True)
    service = SessionArchiveService(
        knowledge_dir=tmp_path,
        git_store=git_store,
        session_mgr=mgr,
        config=SessionCommitConfig(),
    )

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
async def test_archive_service_skips_private_sessions(tmp_path) -> None:
    mgr = SessionManager(tmp_path)
    state = mgr.create_session(private=True)
    mgr.append_events(state.session_id, [{"role": "user", "content": "hello"}])
    git_store = MagicMock(spec=GitStore)
    git_store.commit = AsyncMock(return_value=True)
    service = SessionArchiveService(
        knowledge_dir=tmp_path,
        git_store=git_store,
        session_mgr=mgr,
        config=SessionCommitConfig(),
    )

    result = await service.commit_session(state.session_id, trigger="manual")

    assert result.committed is False
    assert result.reason == "Private sessions cannot be committed to knowledge"


@pytest.mark.asyncio
async def test_archive_service_empty_history_returns_no_archive_path(tmp_path) -> None:
    mgr = SessionManager(tmp_path)
    state = mgr.create_session(private=False)
    git_store = MagicMock(spec=GitStore)
    git_store.commit = AsyncMock(return_value=True)
    service = SessionArchiveService(
        knowledge_dir=tmp_path,
        git_store=git_store,
        session_mgr=mgr,
        config=SessionCommitConfig(),
    )

    result = await service.commit_session(state.session_id, trigger="manual")

    assert result.committed is False
    assert result.archive_path is None
    assert result.reason == "Session has no history to archive yet"


@pytest.mark.asyncio
async def test_archive_service_skips_unchanged_snapshot_for_different_trigger(tmp_path) -> None:
    mgr = SessionManager(tmp_path)
    state = mgr.create_session(private=False)
    mgr.append_events(
        state.session_id,
        [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "world"},
        ],
    )
    git_store = MagicMock(spec=GitStore)
    git_store.commit = AsyncMock(return_value=True)
    service = SessionArchiveService(
        knowledge_dir=tmp_path,
        git_store=git_store,
        session_mgr=mgr,
        config=SessionCommitConfig(),
    )

    first = await service.commit_session(state.session_id, trigger="autosave")
    second = await service.commit_session(state.session_id, trigger="manual")

    assert first.committed is True
    assert second.committed is False
    assert second.reason == "No archive changes to commit"
    assert git_store.commit.await_count == 1


@pytest.mark.asyncio
async def test_archive_service_preserves_concurrent_privacy_update(tmp_path) -> None:
    mgr = SessionManager(tmp_path)
    state = mgr.create_session(private=False)
    mgr.append_events(state.session_id, [{"role": "user", "content": "hello"}])
    git_store = MagicMock(spec=GitStore)

    async def commit_with_concurrent_privacy_flip(*args, **kwargs) -> bool:
        current = mgr.load_state(state.session_id)
        assert current is not None
        current.private = True
        mgr.save_state(current)
        return True

    git_store.commit = AsyncMock(side_effect=commit_with_concurrent_privacy_flip)
    service = SessionArchiveService(
        knowledge_dir=tmp_path,
        git_store=git_store,
        session_mgr=mgr,
        config=SessionCommitConfig(),
    )

    result = await service.commit_session(state.session_id, trigger="manual")
    final_state = mgr.load_state(state.session_id)

    assert result.committed is True
    assert final_state is not None
    assert final_state.private is True
    assert final_state.knowledge_last_committed_at is not None


@pytest.mark.asyncio
async def test_archive_service_serializes_same_session_commits(tmp_path) -> None:
    mgr = SessionManager(tmp_path)
    state = mgr.create_session(private=False)
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
    service = SessionArchiveService(
        knowledge_dir=tmp_path,
        git_store=git_store,
        session_mgr=mgr,
        config=SessionCommitConfig(),
    )

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
async def test_archive_service_does_not_persist_export_hash_on_commit_failure(tmp_path) -> None:
    mgr = SessionManager(tmp_path)
    state = mgr.create_session(private=False)
    mgr.append_events(state.session_id, [{"role": "user", "content": "hello"}])
    git_store = MagicMock(spec=GitStore)
    git_store.commit = AsyncMock(side_effect=RuntimeError("git commit failed: boom"))
    service = SessionArchiveService(
        knowledge_dir=tmp_path,
        git_store=git_store,
        session_mgr=mgr,
        config=SessionCommitConfig(),
    )

    with pytest.raises(RuntimeError, match="git commit failed: boom"):
        await service.commit_session(state.session_id, trigger="manual")

    final_state = mgr.load_state(state.session_id)

    assert final_state is not None
    assert final_state.knowledge_last_export_hash is None
    assert final_state.knowledge_last_archive_path is None
    assert final_state.knowledge_last_committed_at is None
    assert service._session_locks == {}


@pytest.mark.asyncio
async def test_archive_service_removes_written_file_after_commit_failure(tmp_path) -> None:
    mgr = SessionManager(tmp_path)
    state = mgr.create_session(private=False)
    mgr.append_events(state.session_id, [{"role": "user", "content": "hello"}])
    git_store = MagicMock(spec=GitStore)
    git_store.commit = AsyncMock(side_effect=RuntimeError("git commit failed: boom"))
    service = SessionArchiveService(
        knowledge_dir=tmp_path,
        git_store=git_store,
        session_mgr=mgr,
        config=SessionCommitConfig(),
    )
    archive_file = service.archive_absolute_path_for_state(state)

    with pytest.raises(RuntimeError, match="git commit failed: boom"):
        await service.commit_session(state.session_id, trigger="manual")

    assert not archive_file.exists()
    assert not archive_file.parent.exists()


@pytest.mark.asyncio
async def test_archive_service_cleans_up_lock_after_archive_delete(tmp_path) -> None:
    mgr = SessionManager(tmp_path)
    state = mgr.create_session(private=False)
    mgr.append_events(state.session_id, [{"role": "user", "content": "hello"}])
    git_store = MagicMock(spec=GitStore)
    git_store.commit = AsyncMock(return_value=True)
    git_store.commit_removals = AsyncMock(return_value=True)
    service = SessionArchiveService(
        knowledge_dir=tmp_path,
        git_store=git_store,
        session_mgr=mgr,
        config=SessionCommitConfig(),
    )

    await service.commit_session(state.session_id, trigger="manual")
    archived_state = mgr.load_state(state.session_id)

    assert archived_state is not None
    assert await service.delete_session_archive(archived_state) is True
    assert service._session_locks == {}
    assert service._session_lock_refs == {}


@pytest.mark.asyncio
async def test_archive_service_uses_update_title_after_first_commit(tmp_path) -> None:
    mgr = SessionManager(tmp_path)
    state = mgr.create_session(private=False)
    mgr.append_events(state.session_id, [{"role": "user", "content": "hello"}])
    git_store = MagicMock(spec=GitStore)
    git_store.commit = AsyncMock(return_value=True)
    service = SessionArchiveService(
        knowledge_dir=tmp_path,
        git_store=git_store,
        session_mgr=mgr,
        config=SessionCommitConfig(),
    )

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
