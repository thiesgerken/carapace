"""Closing approval requests that no turn can answer anymore."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from carapace.session.manager import SessionManager
from carapace.session.open_approvals import ORPHANED_APPROVAL_MESSAGE, closing_events_for_open_approvals
from tests.session_helpers import _make_engine, _patch_sentinel, _without_timestamps

_OPEN_REQUESTS: list[dict[str, Any]] = [
    {"role": "approval_request", "tool_call_id": "call-open", "tool": "exec", "args": {"command": "rm -rf /"}},
    {"role": "domain_access_approval", "request_id": "dom-open", "domain": "evil.example", "command": "curl"},
    {"role": "proxy_approval", "request_id": "proxy-open", "domain": "old.example", "command": "wget"},
    {
        "role": "git_push_approval",
        "request_id": "push-open",
        "ref": "refs/heads/main",
        "explanation": "changes SECURITY.md",
        "changed_files": ["SECURITY.md"],
    },
    {
        "role": "credential_approval",
        "request_id": "cred-open",
        "vault_paths": ["vault/item"],
        "names": ["Item"],
        "descriptions": [""],
        "explanation": "needs it",
    },
]

_ANSWERED_REQUESTS: list[dict[str, Any]] = [
    {"role": "approval_request", "tool_call_id": "call-done", "tool": "exec", "args": {"command": "ls"}},
    {"role": "approval_response", "tool_call_id": "call-done", "decision": "approved", "decision_source": "user"},
    {"role": "domain_access_approval", "request_id": "dom-done", "domain": "ok.example", "command": "curl"},
    {
        "role": "domain_access_approval",
        "request_id": "dom-done",
        "domain": "ok.example",
        "command": "curl",
        "decision": "allow",
        "decision_source": "user",
        "message": None,
    },
    {"role": "credential_approval", "request_id": "cred-done", "vault_paths": ["vault/other"]},
    {
        "role": "credential_approval",
        "request_id": "cred-done",
        "vault_paths": ["vault/other"],
        "decision": "deny",
        "decision_source": "user",
        "message": "no",
    },
]


def _system_denial(fields: dict[str, Any], *, decision: str) -> dict[str, Any]:
    return {**fields, "decision": decision, "decision_source": "system", "message": ORPHANED_APPROVAL_MESSAGE}


_EXPECTED_CLOSING = [
    _system_denial({"role": "approval_response", "tool_call_id": "call-open"}, decision="denied"),
    _system_denial(
        {"role": "domain_access_approval", "request_id": "dom-open", "domain": "evil.example", "command": "curl"},
        decision="deny",
    ),
    _system_denial(
        {"role": "proxy_approval", "request_id": "proxy-open", "domain": "old.example", "command": "wget"},
        decision="deny",
    ),
    _system_denial({"role": "git_push_approval", "request_id": "push-open", "ref": "refs/heads/main"}, decision="deny"),
    _system_denial(
        {"role": "credential_approval", "request_id": "cred-open", "vault_paths": ["vault/item"]}, decision="deny"
    ),
]


def test_closing_events_deny_every_open_request_kind() -> None:
    events = [{"role": "user", "content": "go"}, *_ANSWERED_REQUESTS, *_OPEN_REQUESTS]

    assert closing_events_for_open_approvals(events) == _EXPECTED_CLOSING


def test_closing_events_leave_answered_requests_alone() -> None:
    assert closing_events_for_open_approvals(_ANSWERED_REQUESTS) == []


def test_closing_events_close_nothing_twice() -> None:
    events = [*_OPEN_REQUESTS, *closing_events_for_open_approvals(_OPEN_REQUESTS)]

    assert closing_events_for_open_approvals(events) == []


def _session_with_events(session_mgr: SessionManager, events: list[dict[str, Any]]) -> str:
    session_id = session_mgr.create_session(user="thies").session_id
    if events:
        session_mgr.append_events(session_id, events)
    return session_id


def test_session_ids_with_open_approval_requests_skips_answered_sessions(tmp_path: Path, db_factory) -> None:
    session_mgr = SessionManager(db_factory, tmp_path)
    open_sid = _session_with_events(session_mgr, [*_ANSWERED_REQUESTS, *_OPEN_REQUESTS[3:4]])
    _session_with_events(session_mgr, _ANSWERED_REQUESTS)
    _session_with_events(session_mgr, [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "yo"}])

    assert session_mgr.session_ids_with_open_approval_requests() == [open_sid]


def test_close_orphaned_approval_requests_closes_only_open_requests(tmp_path: Path, db_factory) -> None:
    engine = _make_engine(tmp_path, session_factory=db_factory)
    open_sid = _session_with_events(engine.session_mgr, [*_ANSWERED_REQUESTS, *_OPEN_REQUESTS])
    answered_sid = _session_with_events(engine.session_mgr, _ANSWERED_REQUESTS)

    engine.close_orphaned_approval_requests()

    open_events = _without_timestamps(engine.session_mgr.load_events(open_sid))
    assert open_events == [*_ANSWERED_REQUESTS, *_OPEN_REQUESTS, *_EXPECTED_CLOSING]
    assert _without_timestamps(engine.session_mgr.load_events(answered_sid)) == _ANSWERED_REQUESTS
    assert engine.session_mgr.session_ids_with_open_approval_requests() == []


def test_close_orphaned_approval_requests_refuses_with_active_sessions(tmp_path: Path, db_factory) -> None:
    with _patch_sentinel():
        engine = _make_engine(tmp_path, session_factory=db_factory)
        sid = _session_with_events(engine.session_mgr, _OPEN_REQUESTS)
        engine.get_or_activate(sid)

        with pytest.raises(RuntimeError, match="before any session is active"):
            engine.close_orphaned_approval_requests()
