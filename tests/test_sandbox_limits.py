"""Per-user sandbox limit: counting and enforcement on sandbox start."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from carapace.git.store import GitStore
from carapace.knowledge import KnowledgeRepoHandle
from carapace.sandbox.manager import SandboxLimitError, SandboxManager
from carapace.sandbox.state import load_sandbox_snapshot
from carapace.session.manager import SessionManager, SessionMeta
from carapace.skills import SkillRegistry
from tests.runtime_mocks import make_runtime_mock


def _manager(tmp_path: Path, db_factory, *, retained: set[str], max_per_user: int) -> SandboxManager:
    runtime = make_runtime_mock()
    runtime.retained_sandbox_session_ids = AsyncMock(return_value=retained)
    runtime.logs = AsyncMock(return_value="carapace sandbox ready")
    handle = KnowledgeRepoHandle(
        owner="thies",
        knowledge_dir=tmp_path,
        git_store=GitStore(tmp_path),
        skill_registry=SkillRegistry(tmp_path / "skills"),
    )
    mgr = SandboxManager(
        runtime=runtime,
        data_dir=tmp_path,
        knowledge_repo_for_session=lambda _session_id: handle,
        session_factory=db_factory,
        max_sandboxes_per_user=max_per_user,
    )
    mgr._rerun_activated_skill_setup = AsyncMock()
    return mgr


@pytest.fixture
def seeded_sessions(tmp_path: Path, db_factory) -> None:
    sessions = SessionManager(db_factory, tmp_path)
    for session_id in ("thies-1", "thies-2", "thies-new"):
        sessions.save_meta(session_id, SessionMeta(user="thies"))
    sessions.save_meta("other-1", SessionMeta(user="other"))


# Retained: two of thies' sessions, another user's, and an unclaimed warm-pool member.
_RETAINED = {"thies-1", "thies-2", "other-1", "pool-0123456789ab"}


@pytest.mark.anyio
@pytest.mark.usefixtures("seeded_sessions")
async def test_count_excludes_other_users_and_warm_pool(tmp_path: Path, db_factory) -> None:
    mgr = _manager(tmp_path, db_factory, retained=_RETAINED, max_per_user=2)

    assert await mgr.count_user_sandboxes("thies") == 2
    assert await mgr.count_user_sandboxes("other") == 1


@pytest.mark.anyio
@pytest.mark.usefixtures("seeded_sessions")
async def test_new_sandbox_refused_at_limit(tmp_path: Path, db_factory) -> None:
    mgr = _manager(tmp_path, db_factory, retained=_RETAINED, max_per_user=2)

    with pytest.raises(SandboxLimitError, match="You have 2/2 sandboxes"):
        await mgr.ensure_session("thies-new")

    mgr._runtime.create_sandbox.assert_not_awaited()
    mgr._runtime.claim_warm_sandbox.assert_not_awaited()
    assert load_sandbox_snapshot(db_factory, "thies-new") is None


@pytest.mark.anyio
@pytest.mark.usefixtures("seeded_sessions")
async def test_resuming_retained_sandbox_allowed_at_limit(tmp_path: Path, db_factory) -> None:
    mgr = _manager(tmp_path, db_factory, retained=_RETAINED, max_per_user=2)

    # Docker resumes a suspended sandbox by recreating its container.
    sc = await mgr.ensure_session("thies-1")

    assert sc.session_id == "thies-1"
    mgr._runtime.create_sandbox.assert_awaited_once()


@pytest.mark.anyio
@pytest.mark.usefixtures("seeded_sessions")
@pytest.mark.parametrize("max_per_user", [3, 0])
async def test_new_sandbox_allowed_below_limit_or_when_off(tmp_path: Path, db_factory, max_per_user: int) -> None:
    mgr = _manager(tmp_path, db_factory, retained=_RETAINED, max_per_user=max_per_user)

    sc = await mgr.ensure_session("thies-new")

    assert sc.session_id == "thies-new"
