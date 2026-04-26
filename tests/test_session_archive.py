from __future__ import annotations

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
