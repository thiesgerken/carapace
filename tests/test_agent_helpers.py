"""Tests for agent helper functions (no LLM tokens needed)."""

from pathlib import Path

from carapace.agent import _resolve_path, build_system_prompt
from carapace.models import Config, Deps, SessionState


def test_resolve_path_normal(tmp_path: Path):
    err, resolved = _resolve_path(tmp_path, "notes/todo.md")
    assert err is None
    assert str(resolved).startswith(str(tmp_path))


def test_resolve_path_traversal(tmp_path: Path):
    err, _ = _resolve_path(tmp_path, "../../etc/passwd")
    assert err is not None
    assert "escapes" in err


def test_build_system_prompt_minimal(tmp_path: Path):
    state = SessionState(session_id="test-123")
    deps = Deps(
        config=Config(),
        data_dir=tmp_path,
        session_state=state,
        rules=[],
    )
    prompt = build_system_prompt(deps)
    assert "test-123" in prompt


def test_build_system_prompt_with_agents_md(tmp_path: Path):
    (tmp_path / "AGENTS.md").write_text("# Agent Instructions\nBe helpful.")
    state = SessionState(session_id="s1")
    deps = Deps(
        config=Config(),
        data_dir=tmp_path,
        session_state=state,
        rules=[],
    )
    prompt = build_system_prompt(deps)
    assert "Agent Instructions" in prompt
    assert "Be helpful" in prompt
