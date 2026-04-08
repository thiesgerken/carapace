"""Tests for agent helper functions (no LLM tokens needed)."""

from pathlib import Path
from unittest.mock import MagicMock

from pydantic_ai.models import Model

from carapace.agent import build_system_prompt
from carapace.credentials import CredentialRegistry
from carapace.git.store import GitStore
from carapace.models import Config, Deps, SessionState
from carapace.sandbox.manager import SandboxManager
from carapace.security.context import SessionSecurity
from carapace.security.sentinel import Sentinel
from carapace.usage import UsageTracker


def test_build_system_prompt_minimal(tmp_path: Path):
    state = SessionState.now(session_id="test-123")
    deps = Deps(
        config=Config(),
        data_dir=tmp_path,
        knowledge_dir=tmp_path,
        session_state=state,
        rules=[],
        sandbox=MagicMock(spec=SandboxManager),
        security=SessionSecurity("test-123"),
        sentinel=MagicMock(spec=Sentinel),
        git_store=MagicMock(spec=GitStore),
        agent_model=MagicMock(spec=Model),
        agent_model_id="anthropic:claude-sonnet-4-6",
        usage_tracker=UsageTracker(),
        credential_registry=CredentialRegistry(),
    )
    prompt = build_system_prompt(deps)
    assert "test-123" in prompt


def test_build_system_prompt_with_agents_md(tmp_path: Path):
    (tmp_path / "AGENTS.md").write_text("# Agent Instructions\nBe helpful.")
    state = SessionState.now(session_id="s1")
    deps = Deps(
        config=Config(),
        data_dir=tmp_path,
        knowledge_dir=tmp_path,
        session_state=state,
        rules=[],
        sandbox=MagicMock(spec=SandboxManager),
        security=SessionSecurity("s1"),
        sentinel=MagicMock(spec=Sentinel),
        git_store=MagicMock(spec=GitStore),
        agent_model=MagicMock(spec=Model),
        agent_model_id="anthropic:claude-sonnet-4-6",
        usage_tracker=UsageTracker(),
        credential_registry=CredentialRegistry(),
    )
    prompt = build_system_prompt(deps)
    assert "Agent Instructions" in prompt
    assert "Be helpful" in prompt
