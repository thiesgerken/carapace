"""SandboxManager: sandbox lifecycle, warm pool and per-exec notification bookkeeping."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select

from carapace.builder.client import BuilderUnavailableError
from carapace.database.models import SessionAuditRow
from carapace.git.store import GitStore
from carapace.knowledge import KnowledgeRepoHandle
from carapace.sandbox.manager import SandboxManager
from carapace.sandbox.runtime import DuplicateSandboxError, ExecResult, PoolSandbox
from carapace.sandbox.session_lifecycle import SessionContainer
from carapace.sandbox.state import load_sandbox_snapshot
from carapace.security.context import ApprovalSource, CredentialAccessEntry, SessionSecurity
from carapace.session.manager import SessionManager, SessionMeta
from tests.runtime_mocks import make_runtime_mock


def _sandbox_manager(
    *,
    runtime,
    data_dir: Path,
    session_factory,
    knowledge_dir: Path | None = None,
    knowledge_repo_for_session=None,
    **kwargs,
) -> SandboxManager:
    if knowledge_repo_for_session is None:
        if knowledge_dir is None:
            raise TypeError("knowledge_dir or knowledge_repo_for_session is required in tests")
        handle = KnowledgeRepoHandle(
            owner="thies",
            knowledge_dir=knowledge_dir,
            git_store=GitStore(knowledge_dir),
        )

        def knowledge_repo_for_session(_session_id: str) -> KnowledgeRepoHandle:
            return handle

    return SandboxManager(
        runtime=runtime,
        server_host="172.18.0.1",
        network_name="carapace-sandbox-default",
        data_dir=data_dir,
        knowledge_repo_for_session=knowledge_repo_for_session,
        session_factory=session_factory,
        **kwargs,
    )


def _seed_session_row(session_factory, data_dir: Path, *session_ids: str) -> None:
    """Create minimal `sessions` rows so snapshot/token FK constraints are satisfied."""
    mgr = SessionManager(session_factory, data_dir)
    for session_id in session_ids:
        mgr.save_meta(session_id, SessionMeta(user="thies"))


_BASE_IMAGE = "carapace-sandbox:latest"


def _pool_member(container_id: str, image: str = _BASE_IMAGE) -> PoolSandbox:
    return PoolSandbox(container_id=container_id, image=image)


async def _drain_warm_refill(mgr: SandboxManager) -> None:
    """Await any background warm-pool refill tasks scheduled by ensure_session."""
    tasks = list(mgr._session_lifecycle._warm_refill_tasks)
    if tasks:
        await asyncio.gather(*tasks)


class TestSandboxManagerLifecycle:
    def _make_manager(self, tmp_path: Path, db_factory) -> SandboxManager:
        runtime = make_runtime_mock()
        return _sandbox_manager(runtime=runtime, data_dir=tmp_path, knowledge_dir=tmp_path, session_factory=db_factory)

    @pytest.mark.anyio
    async def test_reset_session_preserves_token(self, tmp_path: Path, db_factory):
        runtime = make_runtime_mock()
        workspace = tmp_path / "sessions" / "sess-1" / "workspace"

        async def destroy_sandbox(_session_id: str, _name: str, _container_id: str) -> None:
            if workspace.exists():
                shutil.rmtree(workspace)

        runtime.destroy_sandbox = AsyncMock(side_effect=destroy_sandbox)
        mgr = _sandbox_manager(runtime=runtime, data_dir=tmp_path, knowledge_dir=tmp_path, session_factory=db_factory)
        _seed_session_row(db_factory, tmp_path, "sess-1")
        token = mgr._session_lifecycle.get_or_create_token("sess-1")
        mgr._sessions["sess-1"] = MagicMock(container_id="c1", session_env={})
        workspace.mkdir(parents=True)
        (workspace / "note.txt").write_text("hello")

        await mgr.reset_session("sess-1")

        runtime.destroy_sandbox.assert_awaited_once_with("sess-1", "carapace-sandbox-sess-1", "c1")
        assert mgr.verify_session_token("sess-1", token)
        assert not workspace.exists()

    @pytest.mark.anyio
    async def test_reset_session_clears_claimed_sandbox_id(self, tmp_path: Path, db_factory):
        runtime = make_runtime_mock()
        mgr = _sandbox_manager(runtime=runtime, data_dir=tmp_path, knowledge_dir=tmp_path, session_factory=db_factory)
        _seed_session_row(db_factory, tmp_path, "sess-1")
        mgr._sessions["sess-1"] = SessionContainer(
            container_id="warm-pod-1",
            session_id="sess-1",
            sandbox_id="warm-1",
            ip_address="10.1.1.4",
            created_at=1.0,
            last_used=1.0,
        )

        await mgr.reset_session("sess-1")

        runtime.destroy_sandbox.assert_awaited_once_with("sess-1", "carapace-sandbox-warm-1", "warm-pod-1")
        snapshot = load_sandbox_snapshot(db_factory, "sess-1")
        assert snapshot is not None
        assert snapshot.sandbox_id is None

    @pytest.mark.anyio
    async def test_cleanup_session_continues_when_snapshot_refresh_fails(self, tmp_path: Path, db_factory):
        runtime = make_runtime_mock()
        mgr = _sandbox_manager(runtime=runtime, data_dir=tmp_path, knowledge_dir=tmp_path, session_factory=db_factory)
        mgr._sessions["sess-1"] = MagicMock(container_id="c1", session_env={})
        mgr.refresh_sandbox_snapshot = AsyncMock(side_effect=[RuntimeError("before"), RuntimeError("after")])

        await mgr.cleanup_session("sess-1")

        runtime.suspend_sandbox.assert_awaited_once_with("carapace-sandbox-sess-1", "c1")
        assert "sess-1" not in mgr._sessions

    @pytest.mark.anyio
    async def test_cleanup_idle_delegates_to_lifecycle(self, tmp_path: Path, db_factory):
        mgr = self._make_manager(tmp_path, db_factory)
        mgr._session_lifecycle.cleanup_idle = AsyncMock()

        await mgr.cleanup_idle()

        mgr._session_lifecycle.cleanup_idle.assert_awaited_once()
        cleanup_fn = mgr._session_lifecycle.cleanup_idle.await_args.args[0]
        assert cleanup_fn.__self__ is mgr
        assert cleanup_fn.__func__ is SandboxManager.cleanup_session

    @pytest.mark.anyio
    async def test_cleanup_all_delegates_to_lifecycle(self, tmp_path: Path, db_factory):
        mgr = self._make_manager(tmp_path, db_factory)
        mgr._session_lifecycle.cleanup_all = AsyncMock()

        await mgr.cleanup_all()

        mgr._session_lifecycle.cleanup_all.assert_awaited_once()
        cleanup_fn = mgr._session_lifecycle.cleanup_all.await_args.args[0]
        assert cleanup_fn.__self__ is mgr
        assert cleanup_fn.__func__ is SandboxManager.cleanup_session

    @pytest.mark.anyio
    async def test_ensure_session_persists_pending_snapshot_during_startup(self, tmp_path: Path, db_factory):
        mgr = self._make_manager(tmp_path, db_factory)

        async def fake_ensure(session_id: str) -> tuple[SessionContainer, bool]:
            snapshot = load_sandbox_snapshot(db_factory, session_id)
            assert snapshot is not None
            assert snapshot.status == "pending"
            return (
                SessionContainer(
                    container_id="container-1",
                    session_id=session_id,
                    ip_address="172.18.0.22",
                    created_at=1.0,
                    last_used=1.0,
                ),
                True,
            )

        _seed_session_row(db_factory, tmp_path, "sess-1")
        mgr._session_lifecycle.ensure_session = AsyncMock(side_effect=fake_ensure)

        await mgr.ensure_session("sess-1")

        snapshot = load_sandbox_snapshot(db_factory, "sess-1")
        assert snapshot is not None
        assert snapshot.status == "running"
        assert snapshot.runtime == "docker"

    @pytest.mark.anyio
    async def test_ensure_session_clears_pending_snapshot_when_startup_fails(self, tmp_path: Path, db_factory):
        mgr = self._make_manager(tmp_path, db_factory)

        async def fake_ensure(session_id: str) -> tuple[SessionContainer, bool]:
            snapshot = load_sandbox_snapshot(db_factory, session_id)
            assert snapshot is not None
            assert snapshot.status == "pending"
            raise RuntimeError("boom")

        _seed_session_row(db_factory, tmp_path, "sess-1")
        mgr._session_lifecycle.ensure_session = AsyncMock(side_effect=fake_ensure)

        with pytest.raises(RuntimeError, match="boom"):
            await mgr.ensure_session("sess-1")

        snapshot = load_sandbox_snapshot(db_factory, "sess-1")
        assert snapshot is not None
        assert snapshot.status == "missing"

    @pytest.mark.anyio
    async def test_ensure_warm_pool_creates_unattached_sandboxes(self, tmp_path: Path, db_factory):
        runtime = make_runtime_mock()
        runtime.runtime_kind = "kubernetes"
        runtime.list_pool_sandboxes = AsyncMock(side_effect=[{}, {}, {}])
        runtime.sandbox_exists = AsyncMock(return_value=None)
        runtime.create_sandbox = AsyncMock(side_effect=["pool-container-1", "pool-container-2"])
        runtime.logs = AsyncMock(return_value="carapace sandbox ready")
        mgr = _sandbox_manager(runtime=runtime, data_dir=tmp_path, knowledge_dir=tmp_path, session_factory=db_factory)

        warmed = await mgr.ensure_warm_pool(2)

        assert warmed == 2
        assert runtime.create_sandbox.await_count == 2
        first = runtime.create_sandbox.await_args_list[0].args[0]
        second = runtime.create_sandbox.await_args_list[1].args[0]
        # Pool members get unique uuid-based ids, not a recycled sequence.
        assert first.sandbox_id.startswith("pool-")
        assert first.name == f"carapace-sandbox-{first.sandbox_id}"
        assert first.session_id == first.sandbox_id
        assert first.labels["carapace.pool"] == "true"
        assert first.labels["carapace.sandbox"] == first.sandbox_id
        # Pool members have no owning session until claimed.
        assert "carapace.session" not in first.labels
        assert first.environment == {}
        assert "setup-proxy.sh" not in " ".join(first.command)
        assert second.sandbox_id.startswith("pool-")
        assert second.sandbox_id != first.sandbox_id

    @pytest.mark.anyio
    async def test_ensure_warm_pool_shrinks_extra_unattached_sandboxes(self, tmp_path: Path, db_factory):
        runtime = make_runtime_mock()
        runtime.runtime_kind = "kubernetes"
        runtime.list_pool_sandboxes = AsyncMock(
            side_effect=[
                {"warm-1": _pool_member("warm-container-1"), "warm-2": _pool_member("warm-container-2")},
                {"warm-1": _pool_member("warm-container-1"), "warm-2": _pool_member("warm-container-2")},
            ]
        )
        mgr = _sandbox_manager(runtime=runtime, data_dir=tmp_path, knowledge_dir=tmp_path, session_factory=db_factory)
        mgr._session_lifecycle.ensure_warm_sandbox = AsyncMock(side_effect=["warm-container-1", "warm-container-2"])

        warmed = await mgr.ensure_warm_pool(1)

        assert warmed == 1
        runtime.destroy_sandbox.assert_awaited_once_with("warm-2", "carapace-sandbox-warm-2", "warm-container-2")

    @pytest.mark.anyio
    async def test_ensure_warm_pool_keeps_member_with_current_image(self, tmp_path: Path, db_factory):
        runtime = make_runtime_mock()
        runtime.runtime_kind = "kubernetes"
        runtime.list_pool_sandboxes = AsyncMock(return_value={"warm-1": _pool_member("warm-pod-1")})
        mgr = _sandbox_manager(runtime=runtime, data_dir=tmp_path, knowledge_dir=tmp_path, session_factory=db_factory)
        mgr._session_lifecycle.ensure_warm_sandbox = AsyncMock(return_value="warm-pod-1")

        warmed = await mgr.ensure_warm_pool(1)

        assert warmed == 1
        mgr._session_lifecycle.ensure_warm_sandbox.assert_awaited_once_with("warm-1")
        runtime.destroy_sandbox.assert_not_awaited()

    @pytest.mark.anyio
    async def test_ensure_warm_pool_replaces_member_with_stale_image(self, tmp_path: Path, db_factory):
        runtime = make_runtime_mock()
        runtime.runtime_kind = "kubernetes"
        runtime.list_pool_sandboxes = AsyncMock(
            side_effect=[{"warm-1": _pool_member("warm-pod-1", image="carapace-sandbox:old")}, {}]
        )
        runtime.create_sandbox = AsyncMock(return_value="pool-container-1")
        runtime.logs = AsyncMock(return_value="carapace sandbox ready")
        mgr = _sandbox_manager(runtime=runtime, data_dir=tmp_path, knowledge_dir=tmp_path, session_factory=db_factory)

        warmed = await mgr.ensure_warm_pool(1)

        assert warmed == 1
        runtime.destroy_sandbox.assert_awaited_once_with("warm-1", "carapace-sandbox-warm-1", "warm-pod-1")
        replacement = runtime.create_sandbox.await_args.args[0]
        assert replacement.image == _BASE_IMAGE
        assert replacement.labels["carapace.pool"] == "true"

    @pytest.mark.anyio
    async def test_claim_warm_sandbox_skips_member_with_stale_image(self, tmp_path: Path, db_factory):
        runtime = make_runtime_mock()
        runtime.runtime_kind = "kubernetes"
        runtime.list_pool_sandboxes = AsyncMock(
            return_value={
                "warm-1": _pool_member("warm-pod-1", image="carapace-sandbox:old"),
                "warm-2": _pool_member("warm-pod-2"),
            }
        )
        runtime.claim_warm_sandbox = AsyncMock(return_value=True)
        mgr = _sandbox_manager(
            runtime=runtime, data_dir=tmp_path, knowledge_dir=tmp_path, warm_pool_size=1, session_factory=db_factory
        )
        lifecycle = mgr._session_lifecycle
        lifecycle.log_assignment = AsyncMock()
        lifecycle.setup_proxy = AsyncMock()
        lifecycle.clone_knowledge_repo = AsyncMock()

        sc = await lifecycle.claim_warm_sandbox("sess-1", {})

        assert sc is not None
        assert sc.sandbox_id == "warm-2"
        runtime.claim_warm_sandbox.assert_awaited_once_with("carapace-sandbox-warm-2", "sess-1")
        runtime.destroy_sandbox.assert_not_awaited()

    @pytest.mark.anyio
    async def test_ensure_session_claims_k8s_warm_sandbox(self, tmp_path: Path, db_factory):
        runtime = make_runtime_mock()
        runtime.runtime_kind = "kubernetes"
        runtime.sandbox_exists = AsyncMock(return_value=None)
        runtime.list_pool_sandboxes = AsyncMock(return_value={"warm-1": _pool_member("warm-pod-1")})
        runtime.claim_warm_sandbox = AsyncMock(return_value=True)
        runtime.get_ip = AsyncMock(return_value="10.1.1.4")
        runtime.logs = AsyncMock(return_value="carapace sandbox ready")
        runtime.exec = AsyncMock(
            side_effect=[
                ExecResult(stdout="", exit_code=0, output=""),
                ExecResult(stdout="", exit_code=1, output=""),
                ExecResult(stdout="", exit_code=0, output=""),
                ExecResult(stdout="", exit_code=0, output=""),
                ExecResult(stdout="", exit_code=0, output=""),
            ]
        )
        mgr = _sandbox_manager(
            runtime=runtime, data_dir=tmp_path, knowledge_dir=tmp_path, warm_pool_size=1, session_factory=db_factory
        )
        _seed_session_row(db_factory, tmp_path, "sess-1")
        mgr._session_lifecycle.ensure_warm_pool = AsyncMock(return_value=1)

        sc = await mgr.ensure_session("sess-1")
        await _drain_warm_refill(mgr)

        assert sc.sandbox_id == "warm-1"
        assert sc.container_id == "warm-pod-1"
        runtime.create_sandbox.assert_not_awaited()
        runtime.claim_warm_sandbox.assert_awaited_once_with("carapace-sandbox-warm-1", "sess-1")
        runtime.write_stdout_log.assert_awaited_once()
        assert "event=claim" in runtime.write_stdout_log.await_args.args[1]
        assert runtime.exec.await_args_list[0].args[1] == "setup-proxy.sh"
        assert runtime.exec.await_args_list[0].kwargs["env"]["CARAPACE_SESSION_ID"] == "sess-1"

        clone_call = runtime.exec.await_args_list[2]
        assert clone_call.args[1] == "git clone $GIT_REPO_URL /workspace"
        assert clone_call.kwargs["env"]["CARAPACE_SESSION_ID"] == "sess-1"
        assert clone_call.kwargs["env"]["GIT_REPO_URL"].endswith(f"/git/{tmp_path.name}")

        snapshot = load_sandbox_snapshot(db_factory, "sess-1")
        assert snapshot is not None
        assert snapshot.sandbox_id == "warm-1"

    @pytest.mark.anyio
    async def test_ensure_session_falls_back_to_cold_create_after_failed_warm_claim(self, tmp_path: Path, db_factory):
        runtime = make_runtime_mock()
        runtime.runtime_kind = "kubernetes"
        runtime.sandbox_exists = AsyncMock(return_value=None)
        runtime.list_pool_sandboxes = AsyncMock(return_value={"warm-1": _pool_member("warm-pod-1")})
        runtime.claim_warm_sandbox = AsyncMock(return_value=True)
        runtime.get_ip = AsyncMock(side_effect=["10.1.1.4", "10.1.1.9"])
        runtime.create_sandbox = AsyncMock(return_value="cold-pod-1")
        runtime.logs = AsyncMock(return_value="carapace sandbox ready")
        runtime.exec = AsyncMock(
            side_effect=[
                ExecResult(stdout="", exit_code=0, output=""),
                ExecResult(stdout="", exit_code=1, output=""),
                ExecResult(stdout="clone failed", exit_code=1, output="clone failed"),
                ExecResult(stdout="", exit_code=1, output=""),
                ExecResult(stdout="", exit_code=0, output=""),
                ExecResult(stdout="", exit_code=0, output=""),
                ExecResult(stdout="", exit_code=0, output=""),
            ]
        )
        mgr = _sandbox_manager(
            runtime=runtime, data_dir=tmp_path, knowledge_dir=tmp_path, warm_pool_size=1, session_factory=db_factory
        )
        _seed_session_row(db_factory, tmp_path, "sess-1")

        sc = await mgr.ensure_session("sess-1")
        await _drain_warm_refill(mgr)

        assert sc.sandbox_id == "sess-1"
        assert sc.container_id == "cold-pod-1"
        runtime.destroy_sandbox.assert_awaited_once_with("sess-1", "carapace-sandbox-warm-1", "warm-pod-1")
        # First create is the cold-create fallback; the background refill adds a pool member.
        cold_config = runtime.create_sandbox.await_args_list[0].args[0]
        assert cold_config.session_id == "sess-1"
        assert "carapace.pool" not in cold_config.labels
        refill_config = runtime.create_sandbox.await_args_list[1].args[0]
        assert refill_config.labels.get("carapace.pool") == "true"

    @pytest.mark.anyio
    async def test_concurrent_warm_claims_do_not_share_same_sandbox(self, tmp_path: Path, db_factory):
        runtime = make_runtime_mock()
        runtime.runtime_kind = "kubernetes"
        runtime.sandbox_exists = AsyncMock(return_value=None)
        runtime.list_pool_sandboxes = AsyncMock(return_value={"warm-1": _pool_member("warm-pod-1")})
        runtime.claim_warm_sandbox = AsyncMock(return_value=True)
        runtime.get_ip = AsyncMock(side_effect=["10.1.1.4", "10.1.1.9"])
        runtime.create_sandbox = AsyncMock(return_value="cold-pod-2")
        mgr = _sandbox_manager(
            runtime=runtime, data_dir=tmp_path, knowledge_dir=tmp_path, warm_pool_size=1, session_factory=db_factory
        )
        mgr._session_lifecycle.wait_for_ready = AsyncMock()
        mgr._session_lifecycle.log_assignment = AsyncMock()
        mgr._session_lifecycle.setup_proxy = AsyncMock()
        mgr._session_lifecycle.clone_knowledge_repo = AsyncMock()
        mgr._session_lifecycle.ensure_warm_pool = AsyncMock(return_value=1)
        _seed_session_row(db_factory, tmp_path, "sess-1", "sess-2")

        first, second = await asyncio.gather(
            mgr.ensure_session("sess-1"),
            mgr.ensure_session("sess-2"),
        )
        await _drain_warm_refill(mgr)

        assert first.sandbox_id == "warm-1"
        assert second.sandbox_id == "sess-2"
        runtime.claim_warm_sandbox.assert_awaited_once_with("carapace-sandbox-warm-1", "sess-1")
        runtime.create_sandbox.assert_awaited_once()

    @pytest.mark.anyio
    async def test_ensure_session_replenishes_warm_pool_after_claim(self, tmp_path: Path, db_factory):
        runtime = make_runtime_mock()
        runtime.runtime_kind = "kubernetes"
        mgr = _sandbox_manager(
            runtime=runtime, data_dir=tmp_path, knowledge_dir=tmp_path, warm_pool_size=1, session_factory=db_factory
        )
        claimed = SessionContainer(
            container_id="warm-pod-1",
            session_id="sess-1",
            sandbox_id="warm-1",
            ip_address="10.1.1.4",
            created_at=1.0,
            last_used=1.0,
        )
        mgr._session_lifecycle.claim_warm_sandbox = AsyncMock(return_value=claimed)
        mgr._session_lifecycle.ensure_warm_pool = AsyncMock(return_value=1)
        _seed_session_row(db_factory, tmp_path, "sess-1")

        sc = await mgr.ensure_session("sess-1")
        await _drain_warm_refill(mgr)

        assert sc is claimed
        mgr._session_lifecycle.ensure_warm_pool.assert_awaited_once_with(1)

    @pytest.mark.anyio
    async def test_ensure_session_reattaches_claimed_warm_sandbox_after_restart(self, tmp_path: Path, db_factory):
        runtime = make_runtime_mock()
        runtime.runtime_kind = "kubernetes"
        runtime.sandbox_exists = AsyncMock(return_value=None)
        runtime.list_sandboxes = AsyncMock(return_value={"sess-1": ["carapace-sandbox-warm-1-0"]})
        runtime.is_running = AsyncMock(return_value=True)
        runtime.get_ip = AsyncMock(return_value="10.1.1.4")
        mgr = _sandbox_manager(
            runtime=runtime,
            data_dir=tmp_path,
            knowledge_dir=tmp_path,
            warm_pool_size=1,
            session_factory=db_factory,
            nix_config=AsyncMock(return_value="substituters = http://cache.carapace.internal"),
        )
        _seed_session_row(db_factory, tmp_path, "sess-1")

        sc = await mgr.ensure_session("sess-1")

        assert sc.container_id == "carapace-sandbox-warm-1-0"
        assert sc.sandbox_id == "warm-1"
        runtime.claim_warm_sandbox.assert_not_awaited()
        runtime.create_sandbox.assert_not_awaited()
        # The pod spec of a claimed warm sandbox has no env: exec and the profile sync use this one.
        assert sc.session_env["NIX_CONFIG"] == "substituters = http://cache.carapace.internal"
        assert sc.session_env["HTTP_PROXY"].startswith("http://sess-1:")

    @pytest.mark.anyio
    async def test_reattach_fails_when_the_session_env_cannot_be_built(self, tmp_path: Path, db_factory):
        runtime = make_runtime_mock()
        runtime.runtime_kind = "kubernetes"
        runtime.list_sandboxes = AsyncMock(return_value={"sess-1": ["carapace-sandbox-warm-1-0"]})
        mgr = _sandbox_manager(
            runtime=runtime,
            data_dir=tmp_path,
            knowledge_dir=tmp_path,
            warm_pool_size=1,
            session_factory=db_factory,
            nix_config=AsyncMock(side_effect=BuilderUnavailableError("builder unreachable")),
        )
        _seed_session_row(db_factory, tmp_path, "sess-1")

        with pytest.raises(BuilderUnavailableError):
            await mgr.ensure_session("sess-1")

        runtime.create_sandbox.assert_not_awaited()
        runtime.destroy_sandbox.assert_not_awaited()

    @pytest.mark.anyio
    async def test_concurrent_ensure_session_for_one_session_claims_once(self, tmp_path: Path, db_factory):
        runtime = make_runtime_mock()
        runtime.runtime_kind = "kubernetes"
        runtime.list_pool_sandboxes = AsyncMock(return_value={"warm-1": _pool_member("warm-pod-1")})
        runtime.claim_warm_sandbox = AsyncMock(return_value=True)
        mgr = _sandbox_manager(
            runtime=runtime, data_dir=tmp_path, knowledge_dir=tmp_path, warm_pool_size=1, session_factory=db_factory
        )
        mgr._session_lifecycle.wait_for_ready = AsyncMock()
        mgr._session_lifecycle.log_assignment = AsyncMock()
        mgr._session_lifecycle.setup_proxy = AsyncMock()
        mgr._session_lifecycle.ensure_warm_pool = AsyncMock(return_value=1)
        clone_started = asyncio.Event()
        release_clone = asyncio.Event()

        async def slow_clone(*_args, **_kwargs) -> None:
            clone_started.set()
            await release_clone.wait()

        mgr._session_lifecycle.clone_knowledge_repo = AsyncMock(side_effect=slow_clone)
        _seed_session_row(db_factory, tmp_path, "sess-1")

        first = asyncio.create_task(mgr.ensure_session("sess-1"))
        await clone_started.wait()
        second = asyncio.create_task(mgr.ensure_session("sess-1"))
        for _ in range(5):
            await asyncio.sleep(0)
        second_waited_for_first = not second.done()
        release_clone.set()
        first_sc, second_sc = await asyncio.gather(first, second)
        await _drain_warm_refill(mgr)

        # The claimed sandbox is already in _sessions while it clones; the second
        # caller must wait for the clone and skill setup instead of using it.
        assert second_waited_for_first
        assert first_sc is second_sc
        runtime.claim_warm_sandbox.assert_awaited_once_with("carapace-sandbox-warm-1", "sess-1")
        runtime.create_sandbox.assert_not_awaited()

    @pytest.mark.anyio
    async def test_refresh_git_identities_only_touches_owner_sandboxes(self, tmp_path: Path, db_factory):
        runtime = make_runtime_mock()
        runtime.is_running = AsyncMock(return_value=True)
        mgr = _sandbox_manager(runtime=runtime, data_dir=tmp_path, knowledge_dir=tmp_path, session_factory=db_factory)
        sessions = SessionManager(db_factory, tmp_path)
        for session_id, user in [("sess-thies", "thies"), ("sess-ben", "ben")]:
            sessions.save_meta(session_id, SessionMeta(user=user))
            mgr._sessions[session_id] = SessionContainer(
                container_id=f"container-{user}", session_id=session_id, created_at=1.0, last_used=1.0
            )

        await mgr.refresh_git_identities("thies")

        assert [call.args[0] for call in runtime.exec.await_args_list] == ["container-thies"]

    @pytest.mark.anyio
    async def test_ensure_warm_pool_is_noop_for_docker_runtime(self, tmp_path: Path, db_factory):
        runtime = make_runtime_mock()
        mgr = _sandbox_manager(
            runtime=runtime, data_dir=tmp_path, knowledge_dir=tmp_path, warm_pool_size=2, session_factory=db_factory
        )

        warmed = await mgr.ensure_warm_pool(2)

        assert warmed == 0
        runtime.list_pool_sandboxes.assert_not_awaited()
        runtime.create_sandbox.assert_not_awaited()

    @pytest.mark.anyio
    async def test_duplicate_sandboxes_only_block_their_own_session(self, tmp_path: Path, db_factory):
        runtime = make_runtime_mock()
        runtime.runtime_kind = "kubernetes"
        runtime.sandbox_exists = AsyncMock(side_effect=lambda name: f"{name}-0")
        runtime.list_sandboxes = AsyncMock(
            return_value={
                "sess-a": ["carapace-sandbox-sess-a-0", "carapace-sandbox-pool-1-0"],
                "sess-b": ["carapace-sandbox-sess-b-0"],
            }
        )
        mgr = _sandbox_manager(runtime=runtime, data_dir=tmp_path, knowledge_dir=tmp_path, session_factory=db_factory)
        _seed_session_row(db_factory, tmp_path, "sess-a", "sess-b")

        with pytest.raises(DuplicateSandboxError, match="sess-a"):
            await mgr.ensure_session("sess-a")
        sc = await mgr.ensure_session("sess-b")

        assert sc.container_id == "carapace-sandbox-sess-b-0"
        assert "sess-a" not in mgr._sessions

    @pytest.mark.anyio
    async def test_cleanup_orphaned_sandboxes_removes_every_sandbox_of_an_orphan(self, tmp_path: Path, db_factory):
        runtime = make_runtime_mock()
        runtime.runtime_kind = "kubernetes"
        runtime.list_sandboxes = AsyncMock(
            return_value={
                "gone": ["carapace-sandbox-gone-0", "carapace-sandbox-pool-1-0"],
                "known": ["carapace-sandbox-known-0", "carapace-sandbox-pool-2-0"],
            }
        )
        mgr = _sandbox_manager(runtime=runtime, data_dir=tmp_path, knowledge_dir=tmp_path, session_factory=db_factory)

        removed = await mgr.cleanup_orphaned_sandboxes({"known"})

        assert removed == 2
        assert [call.args for call in runtime.destroy_sandbox.await_args_list] == [
            ("gone", "carapace-sandbox-gone", "carapace-sandbox-gone-0"),
            ("gone", "carapace-sandbox-pool-1", "carapace-sandbox-pool-1-0"),
        ]

    @pytest.mark.anyio
    async def test_cleanup_orphaned_sandboxes_uses_live_k8s_resource_name(self, tmp_path: Path, db_factory):
        runtime = make_runtime_mock()
        runtime.runtime_kind = "kubernetes"
        runtime.list_sandboxes = AsyncMock(return_value={"sess-1": ["carapace-sandbox-warm-1-0"]})
        mgr = _sandbox_manager(runtime=runtime, data_dir=tmp_path, knowledge_dir=tmp_path, session_factory=db_factory)

        removed = await mgr.cleanup_orphaned_sandboxes(set())

        assert removed == 1
        runtime.destroy_sandbox.assert_awaited_once_with(
            "sess-1",
            "carapace-sandbox-warm-1",
            "carapace-sandbox-warm-1-0",
        )


# ── ApprovalSource type ─────────────────────────────────────────────


class TestApprovalSource:
    def test_skill_is_valid(self):
        source: ApprovalSource = "skill"
        assert source == "skill"

    def test_bypass_is_valid(self):
        source: ApprovalSource = "bypass"
        assert source == "bypass"

    def test_all_values(self):
        valid: set[str] = {"safe-list", "sentinel", "user", "skill", "bypass", "unknown"}
        for v in valid:
            source: ApprovalSource = v  # type: ignore[assignment]
            assert source in valid


# ── Per-exec notification dedupe ─────────────────────────────────────


class TestExecNotificationDedupe:
    def _make_manager(self, tmp_path: Path, db_factory) -> SandboxManager:
        runtime = make_runtime_mock()
        return _sandbox_manager(runtime=runtime, data_dir=tmp_path, knowledge_dir=tmp_path, session_factory=db_factory)

    # -- domain dedupe --

    def test_domain_denied_not_deduped(self, tmp_path: Path, db_factory):
        """Denied domain notifications are never deduped."""
        mgr = self._make_manager(tmp_path, db_factory)
        calls: list[tuple] = []
        mgr._domain_notify_cbs["s1"] = lambda *a: calls.append(a)
        mgr._exec_notified_domains["s1"] = set()
        mgr.notify_domain_access("s1", "evil.com", False)
        mgr.notify_domain_access("s1", "evil.com", False)
        assert len(calls) == 2

    def test_a_policy_refusal_carries_its_reason(self, tmp_path: Path, db_factory):
        """An internal destination is refused by policy, not by a reviewer; the UI shows why."""
        mgr = self._make_manager(tmp_path, db_factory)
        calls: list[tuple] = []
        mgr._domain_notify_cbs["s1"] = lambda *a: calls.append(a)
        mgr.notify_domain_access("s1", "nas.example", False, "nas.example is internal.")
        assert calls == [("nas.example", "[denied] nas.example", "policy", "deny", "nas.example is internal.")]

    # -- credential dedupe --

    def test_mark_credential_notified_outside_exec(self, tmp_path: Path, db_factory):
        """Outside an exec, mark_credential_notified returns False (no-op)."""
        mgr = self._make_manager(tmp_path, db_factory)
        assert mgr.mark_credential_notified("s1", "dev/token") is False
        assert mgr.mark_credential_notified("s1", "dev/token") is False

    def test_mark_credential_notified_during_exec(self, tmp_path: Path, db_factory):
        """During an exec, first call returns False, subsequent True."""
        mgr = self._make_manager(tmp_path, db_factory)
        mgr._exec_notified_credentials["s1"] = set()
        assert mgr.mark_credential_notified("s1", "dev/token") is False
        assert mgr.mark_credential_notified("s1", "dev/token") is True
        # Different path still works
        assert mgr.mark_credential_notified("s1", "dev/other") is False

    def test_record_credential_access_dedupe_skips_action_audit_and_ui(self, tmp_path: Path, db_factory):
        """Second in-exec record for the same UI key must not touch action log, audit, or UI."""
        mgr = self._make_manager(tmp_path, db_factory)
        SessionManager(db_factory, tmp_path).save_meta("s1", SessionMeta(user="thies"))
        sec = SessionSecurity("s1", session_factory=db_factory)
        mgr._exec_notified_credentials["s1"] = set()
        sec.set_credential_notify_suppress(lambda vp: mgr.mark_credential_notified("s1", vp))
        ui_calls: list[tuple] = []
        sec.set_credential_info_callback(lambda *a: ui_calls.append(a))

        kwargs = {
            "vault_paths": ["dev/token"],
            "decision": "approved",
            "explanation": "e1",
            "ui_label": "l1",
            "approval_source": "skill",
            "approval_verdict": "allow",
            "audit_final": "auto_allowed",
            "audit_args": {"operation": "fetch"},
        }
        sec.record_credential_access(**kwargs)
        sec.record_credential_access(**kwargs)

        assert len(sec.action_log) == 1
        assert isinstance(sec.action_log[0], CredentialAccessEntry)
        assert len(ui_calls) == 1
        with db_factory() as db:
            audit_rows = db.scalars(
                select(SessionAuditRow).where(SessionAuditRow.session_id == "s1").order_by(SessionAuditRow.id)
            ).all()
        assert len(audit_rows) == 1

    def test_cleanup_clears_notified_sets(self, tmp_path: Path, db_factory):
        mgr = self._make_manager(tmp_path, db_factory)
        mgr._exec_notified_domains["s1"] = {"a.com"}
        mgr._exec_notified_credentials["s1"] = {"dev/token"}
        mgr._cleanup_tracking("s1")
        assert "s1" not in mgr._exec_notified_domains
        assert "s1" not in mgr._exec_notified_credentials
