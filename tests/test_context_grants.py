"""Tests for context-scoped skill allowlists (context grants)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from carapace.models import ContextGrant, SessionState, SkillCredentialDecl
from carapace.sandbox.manager import SandboxManager
from carapace.sandbox.runtime import ContainerRuntime
from carapace.security.context import ApprovalSource, ContextGrantEntry

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
            vault_paths={"dev/token"},
            credential_decls=[decl],
        )
        assert "api.moneydb.io" in grant.domains
        assert "dev/token" in grant.vault_paths
        assert grant.credential_decls[0].env_var == "TOKEN"

    def test_serialization_roundtrip(self):
        grant = ContextGrant(
            skill_name="example",
            domains={"a.com"},
            vault_paths={"dev/key"},
            credential_decls=[SkillCredentialDecl(vault_path="dev/key", file="/tmp/key")],
        )
        data = grant.model_dump()
        restored = ContextGrant.model_validate(data)
        assert restored.skill_name == "example"
        assert restored.domains == {"a.com"}
        assert restored.credential_decls[0].file == "/tmp/key"


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
            vault_paths={"dev/key"},
        )
        data = state.model_dump()
        restored = SessionState.model_validate(data)
        assert "example" in restored.context_grants
        assert restored.context_grants["example"].domains == {"a.com"}


# ── SandboxManager credential cache ─────────────────────────────────


class TestSandboxManagerCredentialCache:
    def _make_manager(self, tmp_path: Path) -> SandboxManager:
        runtime = MagicMock(spec=ContainerRuntime)
        return SandboxManager(runtime=runtime, data_dir=tmp_path, knowledge_dir=tmp_path)

    def test_cache_and_retrieve(self, tmp_path: Path):
        mgr = self._make_manager(tmp_path)
        mgr.cache_credential("sess-1", "dev/token", "secret-value")
        assert mgr.get_cached_credential("sess-1", "dev/token") == "secret-value"

    def test_retrieve_missing_returns_none(self, tmp_path: Path):
        mgr = self._make_manager(tmp_path)
        assert mgr.get_cached_credential("sess-1", "dev/token") is None

    def test_cache_cleared_on_destroy(self, tmp_path: Path):
        mgr = self._make_manager(tmp_path)
        mgr.cache_credential("sess-1", "dev/token", "secret-value")
        # _credential_cache survives _cleanup_tracking (error-path cleanup)
        mgr._cleanup_tracking("sess-1")
        assert mgr.get_cached_credential("sess-1", "dev/token") == "secret-value"
        # but is cleared when the credential cache itself is popped (destroy_session)
        mgr._credential_cache.pop("sess-1", None)
        assert mgr.get_cached_credential("sess-1", "dev/token") is None


# ── SandboxManager context tracking ─────────────────────────────────


class TestSandboxManagerContextTracking:
    def _make_manager(self, tmp_path: Path) -> SandboxManager:
        runtime = MagicMock(spec=ContainerRuntime)
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
