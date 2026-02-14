"""Tests for SessionManager (no LLM tokens needed)."""

from pathlib import Path

from carapace.session import SessionManager


def test_create_session(tmp_path: Path):
    mgr = SessionManager(tmp_path)
    state = mgr.create_session()
    assert len(state.session_id) == 12
    assert state.channel_type == "cli"


def test_resume_session(tmp_path: Path):
    mgr = SessionManager(tmp_path)
    state = mgr.create_session()
    resumed = mgr.resume_session(state.session_id)
    assert resumed is not None
    assert resumed.session_id == state.session_id


def test_resume_nonexistent(tmp_path: Path):
    mgr = SessionManager(tmp_path)
    assert mgr.resume_session("doesnotexist") is None


def test_list_sessions(tmp_path: Path):
    mgr = SessionManager(tmp_path)
    s1 = mgr.create_session()
    s2 = mgr.create_session()
    sessions = mgr.list_sessions()
    assert s1.session_id in sessions
    assert s2.session_id in sessions


def test_save_and_resume_state(tmp_path: Path):
    mgr = SessionManager(tmp_path)
    state = mgr.create_session()
    state.activated_rules.append("rule-1")
    state.disabled_rules.append("rule-2")
    mgr.save_state(state)

    resumed = mgr.resume_session(state.session_id)
    assert resumed is not None
    assert "rule-1" in resumed.activated_rules
    assert "rule-2" in resumed.disabled_rules
