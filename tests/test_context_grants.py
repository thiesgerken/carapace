"""Tests for context-scoped skill allowlists (context grants)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from carapace.models import ContextGrant, SessionState, SkillCredentialDecl, context_grants_session_summary
from carapace.sandbox.manager import SandboxManager
from carapace.sandbox.runtime import ExecResult
from carapace.security.context import ApprovalSource, ContextGrantEntry, CredentialAccessEntry, SessionSecurity
from carapace.security.sentinel import _format_entry
from tests.runtime_mocks import make_runtime_mock

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
    def _make_manager(self, tmp_path: Path) -> SandboxManager:
        runtime = make_runtime_mock()
        return SandboxManager(runtime=runtime, data_dir=tmp_path, knowledge_dir=tmp_path)

    def test_cache_and_retrieve(self, tmp_path: Path):
        mgr = self._make_manager(tmp_path)
        mgr.cache_credential("sess-1", "dev/token", "secret-value")
        assert mgr.get_cached_credential("sess-1", "dev/token") == "secret-value"

    def test_retrieve_missing_returns_none(self, tmp_path: Path):
        mgr = self._make_manager(tmp_path)
        assert mgr.get_cached_credential("sess-1", "dev/token") is None

    def test_credential_cache_survives_cleanup_tracking(self, tmp_path: Path):
        mgr = self._make_manager(tmp_path)
        mgr.cache_credential("sess-1", "dev/token", "secret-value")
        # ensure_session error path: container bookkeeping only, not skill cache
        mgr._cleanup_tracking("sess-1")
        assert mgr.get_cached_credential("sess-1", "dev/token") == "secret-value"

    @pytest.mark.anyio
    async def test_credential_cache_cleared_on_destroy_session(self, tmp_path: Path):
        runtime = make_runtime_mock()
        runtime.destroy_sandbox = AsyncMock()
        mgr = SandboxManager(runtime=runtime, data_dir=tmp_path, knowledge_dir=tmp_path)
        mgr.cache_credential("sess-1", "dev/token", "secret-value")
        mgr._sessions["sess-1"] = MagicMock(container_id="c1", session_env={})
        await mgr.destroy_session("sess-1")
        assert mgr.get_cached_credential("sess-1", "dev/token") is None

    @pytest.mark.anyio
    async def test_reset_session_preserves_token(self, tmp_path: Path):
        runtime = make_runtime_mock()
        runtime.destroy_sandbox = AsyncMock()
        mgr = SandboxManager(runtime=runtime, data_dir=tmp_path, knowledge_dir=tmp_path)
        token = mgr._session_lifecycle.get_or_create_token("sess-1")
        mgr._sessions["sess-1"] = MagicMock(container_id="c1", session_env={})
        workspace = tmp_path / "sessions" / "sess-1" / "workspace"
        workspace.mkdir(parents=True)
        (workspace / "note.txt").write_text("hello")

        await mgr.reset_session("sess-1")

        runtime.destroy_sandbox.assert_awaited_once_with("sess-1", "carapace-sandbox-sess-1", "c1")
        assert mgr.verify_session_token("sess-1", token)
        assert not workspace.exists()

    @pytest.mark.anyio
    async def test_cleanup_session_continues_when_snapshot_refresh_fails(self, tmp_path: Path):
        runtime = make_runtime_mock()
        mgr = SandboxManager(runtime=runtime, data_dir=tmp_path, knowledge_dir=tmp_path)
        mgr._sessions["sess-1"] = MagicMock(container_id="c1", session_env={})
        mgr.refresh_sandbox_snapshot = AsyncMock(side_effect=[RuntimeError("before"), RuntimeError("after")])

        await mgr.cleanup_session("sess-1")

        runtime.suspend_sandbox.assert_awaited_once_with("carapace-sandbox-sess-1", "c1")
        assert "sess-1" not in mgr._sessions

    @pytest.mark.anyio
    async def test_cleanup_idle_delegates_to_lifecycle(self, tmp_path: Path):
        mgr = self._make_manager(tmp_path)
        mgr._session_lifecycle.cleanup_idle = AsyncMock()

        await mgr.cleanup_idle()

        mgr._session_lifecycle.cleanup_idle.assert_awaited_once()
        cleanup_fn = mgr._session_lifecycle.cleanup_idle.await_args.args[0]
        assert cleanup_fn.__self__ is mgr
        assert cleanup_fn.__func__ is SandboxManager.cleanup_session

    @pytest.mark.anyio
    async def test_cleanup_all_delegates_to_lifecycle(self, tmp_path: Path):
        mgr = self._make_manager(tmp_path)
        mgr._session_lifecycle.cleanup_all = AsyncMock()

        await mgr.cleanup_all()

        mgr._session_lifecycle.cleanup_all.assert_awaited_once()
        cleanup_fn = mgr._session_lifecycle.cleanup_all.await_args.args[0]
        assert cleanup_fn.__self__ is mgr
        assert cleanup_fn.__func__ is SandboxManager.cleanup_session


# ── SandboxManager context tracking ─────────────────────────────────


class TestSandboxManagerContextTracking:
    def _make_manager(self, tmp_path: Path) -> SandboxManager:
        runtime = make_runtime_mock()
        return SandboxManager(runtime=runtime, data_dir=tmp_path, knowledge_dir=tmp_path)

    def test_no_contexts_by_default(self, tmp_path: Path):
        mgr = self._make_manager(tmp_path)
        assert mgr.get_current_contexts("sess-1") == []

    def test_set_and_read_contexts(self, tmp_path: Path):
        mgr = self._make_manager(tmp_path)
        mgr._session_current_contexts["sess-1"] = ["moneydb", "example"]
        assert mgr.get_current_contexts("sess-1") == ["moneydb", "example"]

    def test_domain_skill_granted_false_by_default(self, tmp_path: Path):
        mgr = self._make_manager(tmp_path)
        assert mgr.is_domain_skill_granted("sess-1", "api.com") is False

    def test_domain_skill_granted_with_entry(self, tmp_path: Path):
        mgr = self._make_manager(tmp_path)
        mgr._exec_context_skill_domains["sess-1"] = {"api.moneydb.io"}
        assert mgr.is_domain_skill_granted("sess-1", "api.moneydb.io") is True
        assert mgr.is_domain_skill_granted("sess-1", "evil.com") is False

    def test_cleanup_clears_tracking(self, tmp_path: Path):
        mgr = self._make_manager(tmp_path)
        # _exec_context_skill_domains is cleared in _cleanup_tracking
        mgr._exec_context_skill_domains["sess-1"] = {"api.com"}
        mgr._cleanup_tracking("sess-1")
        assert mgr.is_domain_skill_granted("sess-1", "api.com") is False

    def test_current_contexts_per_exec(self, tmp_path: Path):
        """_session_current_contexts is per-exec, set/cleared in _exec's finally."""
        mgr = self._make_manager(tmp_path)
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
    def _make_manager(self, tmp_path: Path) -> SandboxManager:
        runtime = make_runtime_mock()
        return SandboxManager(runtime=runtime, data_dir=tmp_path, knowledge_dir=tmp_path)

    # -- domain dedupe --

    def test_domain_dedupe_outside_exec(self, tmp_path: Path):
        """Without an active exec, domain notifications always fire."""
        mgr = self._make_manager(tmp_path)
        calls: list[tuple] = []
        mgr._domain_notify_cbs["s1"] = lambda *a: calls.append(a)
        mgr._proxy_bypass_sessions.add("s1")
        mgr.notify_domain_access("s1", "a.com", True)
        mgr.notify_domain_access("s1", "a.com", True)
        # No exec → no notified set → both fire
        assert len(calls) == 2

    def test_domain_dedupe_bypass_during_exec(self, tmp_path: Path):
        """During an exec, repeated bypass domain notifications are deduped."""
        mgr = self._make_manager(tmp_path)
        calls: list[tuple] = []
        mgr._domain_notify_cbs["s1"] = lambda *a: calls.append(a)
        mgr._proxy_bypass_sessions.add("s1")
        mgr._exec_notified_domains["s1"] = set()
        mgr.notify_domain_access("s1", "a.com", True)
        mgr.notify_domain_access("s1", "a.com", True)
        mgr.notify_domain_access("s1", "b.com", True)
        assert len(calls) == 2  # a.com once, b.com once

    def test_domain_dedupe_skill_during_exec(self, tmp_path: Path):
        """During an exec, repeated skill-granted domain notifications are deduped."""
        mgr = self._make_manager(tmp_path)
        calls: list[tuple] = []
        mgr._domain_notify_cbs["s1"] = lambda *a: calls.append(a)
        mgr._exec_context_skill_domains["s1"] = {"api.example.com"}
        mgr._exec_notified_domains["s1"] = set()
        mgr.notify_domain_access("s1", "api.example.com", True)
        mgr.notify_domain_access("s1", "api.example.com", True)
        assert len(calls) == 1

    def test_domain_denied_not_deduped(self, tmp_path: Path):
        """Denied domain notifications are never deduped."""
        mgr = self._make_manager(tmp_path)
        calls: list[tuple] = []
        mgr._domain_notify_cbs["s1"] = lambda *a: calls.append(a)
        mgr._exec_notified_domains["s1"] = set()
        mgr.notify_domain_access("s1", "evil.com", False)
        mgr.notify_domain_access("s1", "evil.com", False)
        assert len(calls) == 2

    # -- credential dedupe --

    def test_mark_credential_notified_outside_exec(self, tmp_path: Path):
        """Outside an exec, mark_credential_notified returns False (no-op)."""
        mgr = self._make_manager(tmp_path)
        assert mgr.mark_credential_notified("s1", "dev/token") is False
        assert mgr.mark_credential_notified("s1", "dev/token") is False

    def test_mark_credential_notified_during_exec(self, tmp_path: Path):
        """During an exec, first call returns False, subsequent True."""
        mgr = self._make_manager(tmp_path)
        mgr._exec_notified_credentials["s1"] = set()
        assert mgr.mark_credential_notified("s1", "dev/token") is False
        assert mgr.mark_credential_notified("s1", "dev/token") is True
        # Different path still works
        assert mgr.mark_credential_notified("s1", "dev/other") is False

    def test_record_credential_access_dedupe_skips_action_audit_and_ui(self, tmp_path: Path):
        """Second in-exec record for the same UI key must not touch action log, audit, or UI."""
        mgr = self._make_manager(tmp_path)
        audit_dir = tmp_path / "audit"
        sec = SessionSecurity("s1", audit_dir=audit_dir)
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
        audit_file = audit_dir / "audit.yaml"
        assert audit_file.is_file()
        assert audit_file.read_text().count("---\n") == 1

    def test_cleanup_clears_notified_sets(self, tmp_path: Path):
        mgr = self._make_manager(tmp_path)
        mgr._exec_notified_domains["s1"] = {"a.com"}
        mgr._exec_notified_credentials["s1"] = {"dev/token"}
        mgr._cleanup_tracking("s1")
        assert "s1" not in mgr._exec_notified_domains
        assert "s1" not in mgr._exec_notified_credentials

    @pytest.mark.asyncio
    async def test_after_exec_credential_notify_runs_before_notified_set_cleared(self, tmp_path: Path):
        """Skill injection UI notify must run while per-exec dedupe is still active."""
        mgr = self._make_manager(tmp_path)
        sc = MagicMock()
        sc.container_id = "c1"
        sc.session_id = "s1"
        sc.session_env = {}

        async def fake_ensure(sid: str):
            return sc, False

        async def fake_rebuild(sid: str) -> None:
            return None

        post_calls: list[str] = []

        async def fake_exec_in_container(*_a, **_kw):
            assert mgr._exec_notified_credentials.get("s1") is not None
            mgr.mark_credential_notified("s1", "dev/token")
            return ExecResult(exit_code=0, output="ok")

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
    async def test_after_exec_credential_notify_fires_when_not_pre_notified(self, tmp_path: Path):
        mgr = self._make_manager(tmp_path)
        sc = MagicMock()
        sc.container_id = "c1"
        sc.session_id = "s1"
        sc.session_env = {}

        async def fake_ensure(sid: str):
            return sc, False

        async def fake_rebuild(sid: str) -> None:
            return None

        post_calls: list[str] = []

        async def fake_exec_in_container(*_a, **_kw):
            return ExecResult(exit_code=0, output="ok")

        mgr.ensure_session = fake_ensure
        mgr._rebuild_skill_venvs = fake_rebuild
        mgr._exec_in_container = fake_exec_in_container

        def after_notify() -> None:
            if mgr.mark_credential_notified("s1", "dev/token"):
                return
            post_calls.append("dev/token")

        await mgr._exec("s1", "echo", after_exec_credential_notify=after_notify)
        assert post_calls == ["dev/token"]
