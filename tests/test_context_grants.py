"""Tests for context-scoped skill allowlists (context grants)."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select

from carapace.database.models import SessionAuditRow
from carapace.git.store import GitStore
from carapace.knowledge import KnowledgeRepoHandle
from carapace.models.session import SessionState
from carapace.models.skills import ContextGrant, SkillCredentialDecl, context_grants_session_summary
from carapace.sandbox.manager import SandboxManager
from carapace.sandbox.runtime import DuplicateSandboxError, ExecResult, PoolSandbox
from carapace.sandbox.session_lifecycle import SessionContainer
from carapace.sandbox.state import load_sandbox_snapshot
from carapace.security.context import ApprovalSource, ContextGrantEntry, CredentialAccessEntry, SessionSecurity
from carapace.security.sentinel import _format_entry
from carapace.session.manager import SessionManager, SessionMeta
from carapace.skills import SkillRegistry
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
            skill_registry=SkillRegistry(knowledge_dir / "skills"),
        )

        def knowledge_repo_for_session(_session_id: str) -> KnowledgeRepoHandle:
            return handle

    return SandboxManager(
        runtime=runtime,
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


# ── ContextGrant model ──────────────────────────────────────────────


class TestContextGrantModel:
    def test_defaults(self):
        grant = ContextGrant(skill_name="moneydb")
        assert grant.skill_name == "moneydb"
        assert grant.domains == set()
        assert grant.vault_paths == set()
        assert grant.credential_decls == []

    def test_with_domains_and_creds(self):
        decl = SkillCredentialDecl(vault_path="dev/token", env_var="TOKEN")
        grant = ContextGrant(
            skill_name="moneydb",
            domains={"api.moneydb.io", "*.storage.googleapis.com"},
            credential_decls=[decl],
        )
        assert "api.moneydb.io" in grant.domains
        assert "dev/token" in grant.vault_paths
        assert grant.credential_decls[0].env_var == "TOKEN"

    def test_serialization_roundtrip(self):
        grant = ContextGrant(
            skill_name="example",
            domains={"a.com"},
            credential_decls=[SkillCredentialDecl(vault_path="dev/key", file="/tmp/key")],
        )
        data = grant.model_dump()
        restored = ContextGrant.model_validate(data)
        assert restored.skill_name == "example"
        assert restored.domains == {"a.com"}
        assert restored.vault_paths == {"dev/key"}
        assert restored.credential_decls[0].file == "/tmp/key"

    def test_base64_flag_defaults_false(self):
        decl = SkillCredentialDecl(vault_path="dev/key", file="kube.yaml")
        assert decl.base64 is False

    def test_base64_flag_roundtrip(self):
        decl = SkillCredentialDecl(vault_path="dev/key", file="kube.yaml", base64=True)
        grant = ContextGrant(skill_name="k3s", credential_decls=[decl])
        data = grant.model_dump()
        restored = ContextGrant.model_validate(data)
        assert restored.credential_decls[0].base64 is True


def test_context_grants_session_summary():
    grants = {
        "moneydb": ContextGrant(
            skill_name="moneydb",
            domains={"b.com", "a.com"},
            credential_decls=[
                SkillCredentialDecl(vault_path="v/p2"),
                SkillCredentialDecl(vault_path="v/p1"),
            ],
        ),
    }
    cached = {"v/p1"}

    def get_cached(session_id: str, vault_path: str) -> str | None:
        assert session_id == "sess-x"
        return "secret" if vault_path in cached else None

    summary = context_grants_session_summary("sess-x", grants, get_cached)
    assert summary["moneydb"]["domains"] == ["a.com", "b.com"]
    assert summary["moneydb"]["vault_paths"] == ["v/p1", "v/p2"]
    assert summary["moneydb"]["cached_credentials"] == 1


# ── ContextGrantEntry (action log) ──────────────────────────────────


class TestContextGrantEntry:
    def test_defaults(self):
        entry = ContextGrantEntry(skill_name="moneydb")
        assert entry.type == "context_grant"
        assert entry.domains == []
        assert entry.vault_paths == []

    def test_with_data(self):
        entry = ContextGrantEntry(
            skill_name="moneydb",
            domains=["api.moneydb.io"],
            vault_paths=["dev/token"],
        )
        assert entry.skill_name == "moneydb"
        assert "api.moneydb.io" in entry.domains

    def test_sentinel_action_log_format(self):
        line = _format_entry(
            ContextGrantEntry(
                skill_name="moneydb",
                domains=["z.io", "a.io"],
                vault_paths=["b/v", "a/v"],
            ),
        )
        assert line.startswith("[context_grant]: moneydb")
        assert "domains=['a.io', 'z.io']" in line
        assert "credentials=['a/v', 'b/v']" in line


# ── SessionState context_grants field ────────────────────────────────


class TestSessionStateContextGrants:
    def _state(self) -> SessionState:
        return SessionState.now(session_id="test-session")

    def test_empty_by_default(self):
        state = self._state()
        assert state.context_grants == {}

    def test_add_and_retrieve(self):
        state = self._state()
        grant = ContextGrant(skill_name="moneydb", domains={"api.moneydb.io"})
        state.context_grants["moneydb"] = grant
        assert "moneydb" in state.context_grants
        assert state.context_grants["moneydb"].domains == {"api.moneydb.io"}

    def test_survives_serialization(self):
        state = self._state()
        state.context_grants["example"] = ContextGrant(
            skill_name="example",
            domains={"a.com"},
            credential_decls=[SkillCredentialDecl(vault_path="dev/key")],
        )
        data = state.model_dump()
        restored = SessionState.model_validate(data)
        assert "example" in restored.context_grants
        assert restored.context_grants["example"].domains == {"a.com"}


# ── SandboxManager credential cache ─────────────────────────────────


class TestSandboxManagerCredentialCache:
    def _make_manager(self, tmp_path: Path, db_factory) -> SandboxManager:
        runtime = make_runtime_mock()
        return _sandbox_manager(runtime=runtime, data_dir=tmp_path, knowledge_dir=tmp_path, session_factory=db_factory)

    def test_cache_and_retrieve(self, tmp_path: Path, db_factory):
        mgr = self._make_manager(tmp_path, db_factory)
        mgr.cache_credential("sess-1", "dev/token", "secret-value")
        assert mgr.get_cached_credential("sess-1", "dev/token") == "secret-value"

    def test_retrieve_missing_returns_none(self, tmp_path: Path, db_factory):
        mgr = self._make_manager(tmp_path, db_factory)
        assert mgr.get_cached_credential("sess-1", "dev/token") is None

    def test_credential_cache_survives_cleanup_tracking(self, tmp_path: Path, db_factory):
        mgr = self._make_manager(tmp_path, db_factory)
        mgr.cache_credential("sess-1", "dev/token", "secret-value")
        # ensure_session error path: container bookkeeping only, not skill cache
        mgr._cleanup_tracking("sess-1")
        assert mgr.get_cached_credential("sess-1", "dev/token") == "secret-value"

    @pytest.mark.anyio
    async def test_credential_cache_cleared_on_destroy_session(self, tmp_path: Path, db_factory):
        runtime = make_runtime_mock()
        runtime.destroy_sandbox = AsyncMock()
        mgr = _sandbox_manager(runtime=runtime, data_dir=tmp_path, knowledge_dir=tmp_path, session_factory=db_factory)
        mgr.cache_credential("sess-1", "dev/token", "secret-value")
        mgr._sessions["sess-1"] = MagicMock(container_id="c1", session_env={})
        await mgr.destroy_session("sess-1")
        assert mgr.get_cached_credential("sess-1", "dev/token") is None

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
    async def test_ensure_session_reruns_skill_setup_after_resume(self, tmp_path: Path, db_factory):
        runtime = make_runtime_mock()
        runtime.is_running = AsyncMock(return_value=False)
        runtime.logs = AsyncMock(return_value="carapace sandbox ready")
        mgr = _sandbox_manager(runtime=runtime, data_dir=tmp_path, knowledge_dir=tmp_path, session_factory=db_factory)
        mgr._sessions["sess-1"] = SessionContainer(
            container_id="container-1",
            session_id="sess-1",
            ip_address="172.18.0.22",
            created_at=1.0,
            last_used=1.0,
        )
        mgr._rerun_activated_skill_setup = AsyncMock()

        await mgr.ensure_session("sess-1")

        mgr._rerun_activated_skill_setup.assert_awaited_once_with("sess-1")
        runtime.resume_sandbox.assert_awaited_once_with("carapace-sandbox-sess-1", _BASE_IMAGE)
        runtime.write_stdout_log.assert_awaited_once()
        assert runtime.write_stdout_log.await_args.args[0] == "container-1"
        assert "event=resume" in runtime.write_stdout_log.await_args.args[1]
        assert "sandbox_id=sess-1" in runtime.write_stdout_log.await_args.args[1]
        assert "session_id=sess-1" in runtime.write_stdout_log.await_args.args[1]

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
        mgr._rerun_activated_skill_setup = AsyncMock()

        sc = await mgr.ensure_session("sess-1")
        await _drain_warm_refill(mgr)

        mgr._rerun_activated_skill_setup.assert_awaited_once_with("sess-1")
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
        mgr._rerun_activated_skill_setup = AsyncMock()

        sc = await mgr.ensure_session("sess-1")
        await _drain_warm_refill(mgr)

        mgr._rerun_activated_skill_setup.assert_awaited_once_with("sess-1")
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
        mgr._rerun_activated_skill_setup = AsyncMock()

        sc = await mgr.ensure_session("sess-1")
        await _drain_warm_refill(mgr)

        mgr._rerun_activated_skill_setup.assert_awaited_once_with("sess-1")
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
            runtime=runtime, data_dir=tmp_path, knowledge_dir=tmp_path, warm_pool_size=1, session_factory=db_factory
        )
        mgr._rerun_activated_skill_setup = AsyncMock()

        sc = await mgr.ensure_session("sess-1")

        mgr._rerun_activated_skill_setup.assert_not_awaited()
        assert sc.container_id == "carapace-sandbox-warm-1-0"
        assert sc.sandbox_id == "warm-1"
        runtime.claim_warm_sandbox.assert_not_awaited()
        runtime.create_sandbox.assert_not_awaited()

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
        mgr._rerun_activated_skill_setup = AsyncMock()
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
        mgr._rerun_activated_skill_setup.assert_awaited_once_with("sess-1")

    @pytest.mark.anyio
    async def test_activate_skill_resume_reruns_setup_for_activated_skills(self, tmp_path: Path, db_factory):
        runtime = make_runtime_mock()
        runtime.is_running = AsyncMock(return_value=False)
        runtime.logs = AsyncMock(return_value="carapace sandbox ready")
        mgr = _sandbox_manager(runtime=runtime, data_dir=tmp_path, knowledge_dir=tmp_path, session_factory=db_factory)
        mgr._sessions["sess-1"] = SessionContainer(
            container_id="container-1",
            session_id="sess-1",
            created_at=1.0,
            last_used=1.0,
        )
        mgr.set_activated_skills_callback(lambda _sid: ["email"])
        mgr.rerun_skill_setup = AsyncMock()
        _seed_session_row(db_factory, tmp_path, "sess-1")

        # The new skill doesn't exist, so activation stops right after the sandbox is up.
        await mgr.activate_skill("sess-1", "moneta")

        runtime.resume_sandbox.assert_awaited_once_with("carapace-sandbox-sess-1", _BASE_IMAGE)
        mgr.rerun_skill_setup.assert_awaited_once_with("sess-1", ["email"])

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


# ── SandboxManager context tracking ─────────────────────────────────


class TestSandboxManagerContextTracking:
    def _make_manager(self, tmp_path: Path, db_factory) -> SandboxManager:
        runtime = make_runtime_mock()
        return _sandbox_manager(runtime=runtime, data_dir=tmp_path, knowledge_dir=tmp_path, session_factory=db_factory)

    def test_no_contexts_by_default(self, tmp_path: Path, db_factory):
        mgr = self._make_manager(tmp_path, db_factory)
        assert mgr.get_current_contexts("sess-1") == []

    def test_set_and_read_contexts(self, tmp_path: Path, db_factory):
        mgr = self._make_manager(tmp_path, db_factory)
        mgr._session_current_contexts["sess-1"] = ["moneydb", "example"]
        assert mgr.get_current_contexts("sess-1") == ["moneydb", "example"]

    def test_domain_skill_granted_false_by_default(self, tmp_path: Path, db_factory):
        mgr = self._make_manager(tmp_path, db_factory)
        assert mgr.is_domain_skill_granted("sess-1", "api.com") is False

    def test_domain_skill_granted_with_entry(self, tmp_path: Path, db_factory):
        mgr = self._make_manager(tmp_path, db_factory)
        mgr._exec_context_skill_domains["sess-1"] = {"api.moneydb.io"}
        assert mgr.is_domain_skill_granted("sess-1", "api.moneydb.io") is True
        assert mgr.is_domain_skill_granted("sess-1", "evil.com") is False

    def test_cleanup_clears_tracking(self, tmp_path: Path, db_factory):
        mgr = self._make_manager(tmp_path, db_factory)
        # _exec_context_skill_domains is cleared in _cleanup_tracking
        mgr._exec_context_skill_domains["sess-1"] = {"api.com"}
        mgr._cleanup_tracking("sess-1")
        assert mgr.is_domain_skill_granted("sess-1", "api.com") is False

    def test_current_contexts_per_exec(self, tmp_path: Path, db_factory):
        """_session_current_contexts is per-exec, set/cleared in _exec's finally."""
        mgr = self._make_manager(tmp_path, db_factory)
        mgr._session_current_contexts["sess-1"] = ["moneydb"]
        # Simulating exec finally cleanup
        mgr._session_current_contexts.pop("sess-1", None)
        assert mgr.get_current_contexts("sess-1") == []


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

    def test_domain_dedupe_outside_exec(self, tmp_path: Path, db_factory):
        """Without an active exec, domain notifications always fire."""
        mgr = self._make_manager(tmp_path, db_factory)
        calls: list[tuple] = []
        mgr._domain_notify_cbs["s1"] = lambda *a: calls.append(a)
        mgr._proxy_bypass_sessions.add("s1")
        mgr.notify_domain_access("s1", "a.com", True)
        mgr.notify_domain_access("s1", "a.com", True)
        # No exec → no notified set → both fire
        assert len(calls) == 2

    def test_domain_dedupe_bypass_during_exec(self, tmp_path: Path, db_factory):
        """During an exec, repeated bypass domain notifications are deduped."""
        mgr = self._make_manager(tmp_path, db_factory)
        calls: list[tuple] = []
        mgr._domain_notify_cbs["s1"] = lambda *a: calls.append(a)
        mgr._proxy_bypass_sessions.add("s1")
        mgr._exec_notified_domains["s1"] = set()
        mgr.notify_domain_access("s1", "a.com", True)
        mgr.notify_domain_access("s1", "a.com", True)
        mgr.notify_domain_access("s1", "b.com", True)
        assert len(calls) == 2  # a.com once, b.com once

    def test_domain_dedupe_skill_during_exec(self, tmp_path: Path, db_factory):
        """During an exec, repeated skill-granted domain notifications are deduped."""
        mgr = self._make_manager(tmp_path, db_factory)
        calls: list[tuple] = []
        mgr._domain_notify_cbs["s1"] = lambda *a: calls.append(a)
        mgr._exec_context_skill_domains["s1"] = {"api.example.com"}
        mgr._exec_notified_domains["s1"] = set()
        mgr.notify_domain_access("s1", "api.example.com", True)
        mgr.notify_domain_access("s1", "api.example.com", True)
        assert len(calls) == 1

    def test_domain_denied_not_deduped(self, tmp_path: Path, db_factory):
        """Denied domain notifications are never deduped."""
        mgr = self._make_manager(tmp_path, db_factory)
        calls: list[tuple] = []
        mgr._domain_notify_cbs["s1"] = lambda *a: calls.append(a)
        mgr._exec_notified_domains["s1"] = set()
        mgr.notify_domain_access("s1", "evil.com", False)
        mgr.notify_domain_access("s1", "evil.com", False)
        assert len(calls) == 2

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

    @pytest.mark.asyncio
    async def test_after_exec_credential_notify_runs_before_notified_set_cleared(self, tmp_path: Path, db_factory):
        """Skill injection UI notify must run while per-exec dedupe is still active."""
        mgr = self._make_manager(tmp_path, db_factory)
        sc = MagicMock()
        sc.container_id = "c1"
        sc.session_id = "s1"
        sc.session_env = {}

        async def fake_ensure(sid: str):
            return sc

        async def fake_rebuild(sid: str) -> None:
            return None

        post_calls: list[str] = []

        async def fake_exec_in_container(*_a, **_kw):
            assert mgr._exec_notified_credentials.get("s1") is not None
            mgr.mark_credential_notified("s1", "dev/token")
            return ExecResult(stdout="ok", exit_code=0, output="ok")

        mgr.ensure_session = fake_ensure
        mgr._rebuild_skill_venvs = fake_rebuild
        mgr._exec_in_container = fake_exec_in_container

        def after_notify() -> None:
            if mgr.mark_credential_notified("s1", "dev/token"):
                return
            post_calls.append("dev/token")

        result = await mgr._exec("s1", "echo", after_exec_credential_notify=after_notify)
        assert result.exit_code == 0
        assert post_calls == []
        assert "s1" not in mgr._exec_notified_credentials

    @pytest.mark.asyncio
    async def test_after_exec_credential_notify_fires_when_not_pre_notified(self, tmp_path: Path, db_factory):
        mgr = self._make_manager(tmp_path, db_factory)
        sc = MagicMock()
        sc.container_id = "c1"
        sc.session_id = "s1"
        sc.session_env = {}

        async def fake_ensure(sid: str):
            return sc

        async def fake_rebuild(sid: str) -> None:
            return None

        post_calls: list[str] = []

        async def fake_exec_in_container(*_a, **_kw):
            return ExecResult(stdout="ok", exit_code=0, output="ok")

        mgr.ensure_session = fake_ensure
        mgr._rebuild_skill_venvs = fake_rebuild
        mgr._exec_in_container = fake_exec_in_container

        def after_notify() -> None:
            if mgr.mark_credential_notified("s1", "dev/token"):
                return
            post_calls.append("dev/token")

        await mgr._exec("s1", "echo", after_exec_credential_notify=after_notify)
        assert post_calls == ["dev/token"]
