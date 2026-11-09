"""Persisted sentinel state: restarts, rewinds, forks and deletion."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path

import pytest
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart
from pydantic_ai.models.test import TestModel
from sqlalchemy import select

from carapace.database.models import SessionActionLogRow, SessionSentinelRow
from carapace.security.context import RewindEntry, SessionSecurity, ToolCallEntry, UserMessageEntry
from carapace.security.sentinel import Sentinel, _action_log_prompt
from carapace.session.manager import SessionManager
from tests.session_helpers import _make_engine, _patch_sentinel


def _sentinel(tmp_path: Path, *, timeout: timedelta = timedelta(seconds=30)) -> Sentinel:
    (tmp_path / "skills").mkdir(exist_ok=True)
    return Sentinel(
        model="test:model",
        user="thies",
        knowledge_dir=tmp_path,
        skills_dir=tmp_path / "skills",
        llm_slots=None,
        timeout=timeout,
        model_factory=lambda _name, *, user: TestModel(call_tools=[]),
    )


def _restarted(session_id: str, db_factory) -> SessionSecurity:
    security = SessionSecurity(session_id, session_factory=db_factory)
    security.load_sentinel_state()
    return security


@pytest.mark.asyncio
async def test_restart_continues_the_shadow_conversation(tmp_path: Path, db_factory) -> None:
    sid = SessionManager(db_factory, tmp_path).create_session(user="thies").session_id
    security = _restarted(sid, db_factory)
    security.append(UserMessageEntry(content="list my files"))
    await _sentinel(tmp_path).evaluate_tool_call(security, "exec", {"command": "ls"})
    security.append(ToolCallEntry(tool="exec", args={"command": "ls"}, decision="allowed"))

    restarted = _restarted(sid, db_factory)

    assert restarted.action_log == security.action_log
    assert restarted.sentinel_messages == security.sentinel_messages
    assert restarted.sentinel_eval_count == 1
    assert _action_log_prompt(restarted) == [
        "New entries since last evaluation:",
        "[tool]: exec(command='ls') → allowed",
    ]

    await _sentinel(tmp_path).evaluate_tool_call(restarted, "exec", {"command": "pwd"})

    continued = _restarted(sid, db_factory).sentinel_messages
    assert continued[: len(security.sentinel_messages)] == security.sentinel_messages
    assert len(continued) > len(security.sentinel_messages)
    assert _action_log_prompt(restarted) == []


@pytest.mark.asyncio
async def test_timed_out_evaluation_keeps_entries_unsynced(
    tmp_path: Path, db_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    sid = SessionManager(db_factory, tmp_path).create_session(user="thies").session_id
    security = _restarted(sid, db_factory)
    security.record_sentinel_evaluation([ModelRequest(parts=[UserPromptPart(content="earlier")])], synced_entries=0)
    security.append(UserMessageEntry(content="hi"))
    sentinel = _sentinel(tmp_path, timeout=timedelta(seconds=0.01))

    async def _hang(*_args: object, **_kwargs: object) -> None:
        await asyncio.sleep(1)

    monkeypatch.setattr(sentinel.agent, "run", _hang)
    verdict = await sentinel.evaluate_tool_call(security, "exec", {"command": "ls"})

    assert verdict.decision == "deny"
    restarted = _restarted(sid, db_factory)
    assert restarted.sentinel_eval_count == 2
    assert restarted.unsynced_entries() == [UserMessageEntry(content="hi")]


def _seed_two_turns(engine) -> str:
    sid = engine.session_mgr.create_session(user="thies").session_id
    active = engine.get_or_activate(sid)
    engine.session_mgr.append_events(
        sid,
        [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "reply one"},
            {"role": "user", "content": "/status"},
            {"role": "user", "content": "second"},
            {"role": "assistant", "content": "reply two"},
        ],
    )
    engine.session_mgr.save_history(
        sid,
        [
            ModelRequest(parts=[UserPromptPart(content="first")]),
            ModelResponse(parts=[TextPart(content="reply one")]),
            ModelRequest(parts=[UserPromptPart(content="second")]),
            ModelResponse(parts=[TextPart(content="reply two")]),
        ],
    )
    active.security.append(UserMessageEntry(content="first"))
    active.security.record_sentinel_evaluation(
        [ModelRequest(parts=[UserPromptPart(content="Session started.")])], synced_entries=1
    )
    active.security.append(UserMessageEntry(content="second"))
    return sid


@pytest.mark.anyio
async def test_rewind_keeps_sentinel_state_and_tells_the_sentinel(tmp_path: Path, db_factory) -> None:
    with _patch_sentinel():
        engine = _make_engine(tmp_path, session_factory=db_factory)
    sid = _seed_two_turns(engine)

    assert await engine.reset_to_turn(sid, 1) is True

    restarted = _restarted(sid, db_factory)
    assert restarted.action_log[:2] == [UserMessageEntry(content="first"), UserMessageEntry(content="second")]
    assert restarted.action_log[2] == RewindEntry(user_message="first", removed_turns=1)
    assert len(restarted.sentinel_messages) == 1
    prompt = "\n".join(_action_log_prompt(restarted))
    assert "[user]: 'second'" in prompt
    assert "[rewind]: user rewound the session to the turn of user message 'first'; everything after" in prompt
    assert "including 1 later turn(s)" in prompt


def test_fork_copies_sentinel_state(tmp_path: Path, db_factory) -> None:
    with _patch_sentinel():
        engine = _make_engine(tmp_path, session_factory=db_factory)
    sid = _seed_two_turns(engine)

    forked = engine.fork_session(sid, event_index=1, channel_type="web")

    source, fork = _restarted(sid, db_factory), _restarted(forked.session_id, db_factory)
    assert fork.action_log == source.action_log
    assert fork.sentinel_messages == source.sentinel_messages
    assert fork.unsynced_entries() == [UserMessageEntry(content="second")]
    assert fork.sentinel_eval_count == 1


def test_deleting_a_session_deletes_its_sentinel_state(tmp_path: Path, db_factory) -> None:
    with _patch_sentinel():
        engine = _make_engine(tmp_path, session_factory=db_factory)
    sid = _seed_two_turns(engine)

    assert engine.session_mgr.delete_session(sid) is True

    with db_factory() as db:
        assert db.get(SessionSentinelRow, sid) is None
        assert db.scalars(select(SessionActionLogRow).where(SessionActionLogRow.session_id == sid)).all() == []
