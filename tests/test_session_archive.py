from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from carapace.git.store import GitStore
from carapace.models import SessionArchiveConfig
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
        config=SessionArchiveConfig(),
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
        config=SessionArchiveConfig(),
    )

    result = await service.commit_session(state.session_id, trigger="manual")

    assert result.committed is False
    assert result.reason == "Private sessions cannot be committed to knowledge"
