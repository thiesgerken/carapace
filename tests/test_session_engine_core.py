"""Core session engine tests unrelated to lifecycle retries and slash commands."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    ThinkingPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

import carapace.usage as usage_mod
from carapace.models.credentials import CredentialRegistryProtocol
from carapace.models.session import SessionFork
from carapace.models.skills import ContextGrant, SkillCredentialDecl
from carapace.sandbox.state import SessionSandboxSnapshot
from carapace.usage import InputShapeRatios, LlmRequestLog, LlmRequestRecord, LlmRequestState, ModelUsage
from tests.session_helpers import _FakeSubscriber, _make_engine, _patch_sentinel, _without_timestamps


async def _drain_background_tasks(active: Any) -> None:
    if active.agent_task is not None:
        await asyncio.gather(active.agent_task, return_exceptions=True)
    while active._pending_sends:
        await asyncio.gather(*tuple(active._pending_sends), return_exceptions=True)


@pytest.mark.anyio
async def test_skill_activation_inputs_use_context_grant(tmp_path: Path, db_factory):
    """Automatic skill setup reuses approved env/file credentials from the persisted context grant."""
    skill_name = "reinject-skill"
    skill_dir = tmp_path / "skills" / skill_name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\n"
        f"name: {skill_name}\n"
        "metadata:\n"
        "  carapace:\n"
        "    credentials:\n"
        "      - vault_path: vault/secret\n"
        "        description: API key\n"
        "        env_var: API_KEY\n"
        "        file: .secrets/key.txt\n"
        "---\n"
    )

    mock_reg = AsyncMock(spec=CredentialRegistryProtocol)
    mock_reg.fetch = AsyncMock(return_value="secret-value")

    with _patch_sentinel():
        engine = _make_engine(tmp_path, session_factory=db_factory, credential_registry=mock_reg)

    state = engine.session_mgr.create_session(user="thies")
    sid = state.session_id
    active = engine.get_or_activate(sid)
    active.state.context_grants[skill_name] = ContextGrant(
        skill_name=skill_name,
        credential_decls=[
            SkillCredentialDecl(
                vault_path="vault/secret",
                description="API key",
                env_var="API_KEY",
                file=".secrets/key.txt",
            ),
        ],
    )

    result = await engine._skill_activation_inputs(sid, skill_name)
    assert result.environment == {"API_KEY": "secret-value"}
    assert [(cred.path, cred.value) for cred in result.file_credentials] == [(".secrets/key.txt", "secret-value")]
    mock_reg.fetch.assert_awaited_once_with("vault/secret")

    active.state.context_grants.pop(skill_name, None)
    mock_reg.fetch.reset_mock()
    empty = await engine._skill_activation_inputs(sid, skill_name)
    assert empty.environment == {}
    assert empty.file_credentials == []
    mock_reg.fetch.assert_not_called()

    active.state.context_grants[skill_name] = ContextGrant(
        skill_name=skill_name,
        credential_decls=[
            SkillCredentialDecl(
                vault_path="vault/secret",
                description="API key",
                env_var="API_KEY",
                file=".secrets/key.txt",
            ),
        ],
    )
    engine.session_mgr.save_state(active.state)
    engine.deactivate(sid)
    mock_reg.fetch.reset_mock()
    mock_reg.fetch = AsyncMock(return_value="from-disk")
    result = await engine._skill_activation_inputs(sid, skill_name)
    assert result.environment == {"API_KEY": "from-disk"}
    assert [(cred.path, cred.value) for cred in result.file_credentials] == [(".secrets/key.txt", "from-disk")]


def test_record_tool_call_event_reuses_sentinel_row_for_user_decision(tmp_path: Path, db_factory) -> None:
    with _patch_sentinel():
        engine = _make_engine(tmp_path, session_factory=db_factory)

    sid = engine.session_mgr.create_session(user="thies").session_id

    initial_tool_id = engine._record_tool_call_event(
        sid,
        tool="proxy_domain",
        args={"domain": "example.com", "command": "curl https://example.com"},
        detail="[sentinel] reviewing",
        approval_source="sentinel",
    )
    updated_tool_id = engine._record_tool_call_event(
        sid,
        tool="proxy_domain",
        args={"domain": "example.com", "command": "curl https://example.com"},
        detail="[user: allow]",
        approval_source="user",
        approval_verdict="allow",
    )

    assert updated_tool_id == initial_tool_id
    events = engine.session_mgr.load_events(sid)
    assert all("timestamp" in event for event in events)
    assert _without_timestamps(events) == [
        {
            "role": "tool_call",
            "tool": "proxy_domain",
            "args": {"domain": "example.com", "command": "curl https://example.com"},
            "detail": "[user: allow]",
            "approval_source": "user",
            "approval_verdict": "allow",
            "approval_explanation": None,
            "tool_id": initial_tool_id,
        },
    ]


def test_record_tool_call_event_reuses_proxy_domain_row_for_queued_reviewing_and_final(
    tmp_path: Path, db_factory
) -> None:
    with _patch_sentinel():
        engine = _make_engine(tmp_path, session_factory=db_factory)

    sid = engine.session_mgr.create_session(user="thies").session_id

    queued_tool_id = engine._record_tool_call_event(
        sid,
        tool="proxy_domain",
        args={"domain": "example.com"},
        detail="[sentinel] queued for batched review",
        approval_source="sentinel",
        parent_tool_id="tool-1",
    )
    reviewing_tool_id = engine._record_tool_call_event(
        sid,
        tool="proxy_domain",
        args={"domain": "example.com"},
        detail="[sentinel] reviewing",
        approval_source="sentinel",
        parent_tool_id="tool-1",
    )
    approved_tool_id = engine._record_tool_call_event(
        sid,
        tool="proxy_domain",
        args={"domain": "example.com"},
        detail="[sentinel: allow] looks fine",
        approval_source="sentinel",
        approval_verdict="allow",
        approval_explanation="looks fine",
        parent_tool_id="tool-1",
    )

    assert queued_tool_id == reviewing_tool_id == approved_tool_id
    events = engine.session_mgr.load_events(sid)
    assert all("timestamp" in event for event in events)
    assert _without_timestamps(events) == [
        {
            "role": "tool_call",
            "tool": "proxy_domain",
            "args": {"domain": "example.com"},
            "detail": "[sentinel: allow] looks fine",
            "approval_source": "sentinel",
            "approval_verdict": "allow",
            "approval_explanation": "looks fine",
            "parent_tool_id": "tool-1",
            "tool_id": queued_tool_id,
        },
    ]


def test_fork_session_copies_transcript_and_security_context(tmp_path: Path, db_factory) -> None:
    with _patch_sentinel():
        engine = _make_engine(tmp_path, session_factory=db_factory)

    source = engine.session_mgr.create_session(
        user="thies",
        channel_type="matrix",
        channel_ref="!room:example.com",
        private=True,
    )
    sid = source.session_id
    active = engine.get_or_activate(sid)
    active.state.title = "Original title"
    active.state.attributes.private = True
    active.state.attributes.archived = True
    active.state.attributes.pinned = True
    active.state.attributes.favorite = True
    active.state.approved_operations = ["exec"]
    active.state.activated_skills = ["web"]
    active.state.context_grants["web"] = ContextGrant(skill_name="web", domains={"example.com"})
    active.state.knowledge_last_archive_path = "sessions/archive.json"
    active.state.knowledge_last_commit_trigger = "manual"
    active.state.knowledge_last_committed_at = datetime.now(tz=UTC)
    engine.session_mgr.save_state(active.state)
    engine.session_mgr.save_usage(
        sid,
        usage_mod.UsageTracker(models={"anthropic:test": ModelUsage(input_tokens=11, output_tokens=7)}),
    )
    engine.session_mgr.save_sandbox_snapshot(
        sid,
        SessionSandboxSnapshot(runtime="kubernetes", status="scaled_down", storage_present=True),
    )
    engine.session_mgr.append_events(
        sid,
        [
            {"role": "user", "content": "first"},
            {"role": "tool_call", "tool": "read", "args": {"path": "README.md"}, "detail": "reading"},
            {"role": "assistant", "content": "reply one"},
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

    forked = engine.fork_session(sid, event_index=2, channel_type="web")

    assert forked.session_id != sid
    assert forked.channel_type == "web"
    assert forked.channel_ref is None
    assert forked.title == "Original title (Copy)"
    assert forked.attributes.private is True
    assert forked.attributes.archived is False
    assert forked.attributes.pinned is False
    assert forked.attributes.favorite is False
    assert forked.approved_operations == ["exec"]
    assert forked.activated_skills == ["web"]
    assert forked.context_grants["web"].domains == {"example.com"}
    assert forked.knowledge_last_committed_at is None
    assert forked.knowledge_last_archive_path is None
    assert forked.knowledge_last_commit_trigger is None
    assert forked.forked_from == SessionFork(session_id=sid, event_count=3)
    assert _without_timestamps(engine.session_mgr.load_events(forked.session_id)) == [
        {"role": "user", "content": "first"},
        {"role": "tool_call", "tool": "read", "args": {"path": "README.md"}, "detail": "reading"},
        {"role": "assistant", "content": "reply one"},
    ]
    forked_history = engine.session_mgr.load_history(forked.session_id)
    assert len(forked_history) == 2
    assert isinstance(forked_history[0], ModelRequest)
    assert isinstance(forked_history[1], ModelResponse)
    assert forked_history[0].parts[0].content == "first"
    response_part = forked_history[1].parts[0]
    assert isinstance(response_part, TextPart)
    assert response_part.content == "reply one"
    assert engine.session_mgr.load_meta(forked.session_id).user == "thies"
    assert engine.session_mgr.load_usage(forked.session_id).models == {}
    assert engine.session_mgr.load_sandbox_snapshot(forked.session_id) is None
    assert len(engine.session_mgr.load_events(sid)) == 5


def test_fork_at_partial_assistant_rebuilds_cut_turn(tmp_path: Path, db_factory) -> None:
    """Forking at an intermediate (partial) assistant keeps the turn's events up to the cut and
    rebuilds a model history ending on that narration — the basis for continuing mid-turn."""
    with _patch_sentinel():
        engine = _make_engine(tmp_path, session_factory=db_factory)
    sid = engine.session_mgr.create_session(user="thies").session_id
    engine.get_or_activate(sid)
    engine.session_mgr.append_events(
        sid,
        [
            {"role": "user", "content": "do it"},
            {"role": "tool_call", "tool": "read", "args": {"path": "a.txt"}, "detail": "reading", "tool_id": "c1"},
            {"role": "tool_result", "tool": "read", "result": "contents", "exit_code": 0, "tool_id": "c1"},
            {"role": "assistant", "content": "let me look closer", "partial": True},
            {"role": "tool_call", "tool": "exec", "args": {"command": "ls"}, "detail": "run", "tool_id": "c2"},
            {"role": "tool_result", "tool": "exec", "result": "ok", "exit_code": 0, "tool_id": "c2"},
            {"role": "assistant", "content": "all done"},
        ],
    )
    engine.session_mgr.save_history(
        sid,
        [
            ModelRequest(parts=[UserPromptPart(content="do it")]),
            ModelResponse(parts=[ToolCallPart(tool_name="read", args={"path": "a.txt"}, tool_call_id="c1")]),
            ModelRequest(parts=[ToolReturnPart(tool_name="read", content="contents", tool_call_id="c1")]),
            ModelResponse(parts=[TextPart(content="let me look closer")]),
            ModelResponse(parts=[ToolCallPart(tool_name="exec", args={"command": "ls"}, tool_call_id="c2")]),
            ModelRequest(parts=[ToolReturnPart(tool_name="exec", content="ok", tool_call_id="c2")]),
            ModelResponse(parts=[TextPart(content="all done")]),
        ],
    )

    forked = engine.fork_session(sid, event_index=3, channel_type="web")

    assert _without_timestamps(engine.session_mgr.load_events(forked.session_id)) == [
        {"role": "user", "content": "do it"},
        {"role": "tool_call", "tool": "read", "args": {"path": "a.txt"}, "detail": "reading", "tool_id": "c1"},
        {"role": "tool_result", "tool": "read", "result": "contents", "exit_code": 0, "tool_id": "c1"},
        {"role": "assistant", "content": "let me look closer", "partial": True},
    ]
    history = engine.session_mgr.load_history(forked.session_id)
    # user prompt, the read tool call/return pair, then the intermediate narration — ending here.
    assert len(history) == 4
    assert isinstance(history[0], ModelRequest) and history[0].parts[0].content == "do it"
    last = history[-1]
    assert isinstance(last, ModelResponse)
    assert isinstance(last.parts[0], TextPart) and last.parts[0].content == "let me look closer"


def _seed_two_turn_session(engine: Any) -> str:
    sid = engine.session_mgr.create_session(user="thies").session_id
    engine.get_or_activate(sid)
    engine.session_mgr.append_events(
        sid,
        [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "reply one"},
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
    engine.session_mgr.save_llm_request_log(
        sid,
        LlmRequestLog(
            records=[
                LlmRequestRecord(
                    ts=datetime.now(tz=UTC),
                    source="agent",
                    input_tokens=4321,
                    input_shape=InputShapeRatios(system=0.5, user=0.3, assistant=0.2),
                )
            ]
        ),
    )
    return sid


@pytest.mark.anyio
async def test_reset_to_user_message_cuts_after_prompt(tmp_path: Path, db_factory) -> None:
    """Resetting at a user message keeps the conversation through that prompt (dropping its
    response), so the user can amend and re-run by sending a follow-up."""
    with _patch_sentinel():
        engine = _make_engine(tmp_path, session_factory=db_factory)
    sid = _seed_two_turn_session(engine)

    ok = await engine.reset_to_turn(sid, 2)  # the "second" user prompt

    assert ok is True
    assert _without_timestamps(engine.session_mgr.load_events(sid)) == [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "reply one"},
        {"role": "user", "content": "second"},
    ]
    history = engine.session_mgr.load_history(sid)
    assert len(history) == 3
    last = history[-1]
    assert isinstance(last, ModelRequest)
    assert isinstance(last.parts[0], UserPromptPart)
    assert last.parts[0].content == "second"


def test_fork_of_a_fork_comes_from_its_direct_source(tmp_path: Path, db_factory) -> None:
    with _patch_sentinel():
        engine = _make_engine(tmp_path, session_factory=db_factory)
    sid = _seed_two_turn_session(engine)
    fork = engine.fork_session(sid, event_index=3, channel_type="web")
    engine.get_or_activate(fork.session_id)

    fork_of_fork = engine.fork_session(fork.session_id, event_index=1, channel_type="web")

    assert fork_of_fork.forked_from == SessionFork(session_id=fork.session_id, event_count=2)


@pytest.mark.anyio
async def test_resetting_a_fork_into_its_inherited_events_trims_its_origin(tmp_path: Path, db_factory) -> None:
    with _patch_sentinel():
        engine = _make_engine(tmp_path, session_factory=db_factory)
    sid = _seed_two_turn_session(engine)
    fork_id = engine.fork_session(sid, event_index=3, channel_type="web").session_id

    assert await engine.reset_to_turn(fork_id, 1)

    state = engine.session_mgr.load_state(fork_id)
    assert state is not None
    assert state.forked_from == SessionFork(session_id=sid, event_count=2)


def test_fork_at_tip_copies_context_distribution(tmp_path: Path, db_factory) -> None:
    with _patch_sentinel():
        engine = _make_engine(tmp_path, session_factory=db_factory)
    sid = _seed_two_turn_session(engine)

    forked = engine.fork_session(sid, event_index=3, channel_type="web")

    log = engine.session_mgr.load_llm_request_log(forked.session_id)
    assert [r.input_tokens for r in log.records] == [4321]
    assert log.records[0].input_shape is not None
    # Usage/cost stay empty — only the context shape is inherited.
    assert engine.session_mgr.load_usage(forked.session_id).models == {}


def test_fork_before_tip_leaves_context_distribution_empty(tmp_path: Path, db_factory) -> None:
    with _patch_sentinel():
        engine = _make_engine(tmp_path, session_factory=db_factory)
    sid = _seed_two_turn_session(engine)

    forked = engine.fork_session(sid, event_index=1, channel_type="web")

    assert engine.session_mgr.load_llm_request_log(forked.session_id).records == []


def test_fork_session_normalizes_unattended_history_when_becoming_attended(tmp_path: Path, db_factory) -> None:
    with _patch_sentinel():
        engine = _make_engine(tmp_path, session_factory=db_factory)

    source = engine.session_mgr.create_session(user="thies", unattended=True)
    sid = source.session_id
    engine.get_or_activate(sid)
    engine.session_mgr.append_events(
        sid,
        [
            {"role": "user", "content": "run on your own"},
            {"role": "assistant", "content": "completed"},
        ],
    )
    engine.session_mgr.save_history(
        sid,
        [
            ModelRequest(parts=[UserPromptPart(content="run on your own")]),
            ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="task_done",
                        args={"result": "completed"},
                        tool_call_id="done-1",
                    )
                ]
            ),
            ModelRequest(
                parts=[
                    ToolReturnPart(
                        tool_name="task_done",
                        content="Final result processed.",
                        tool_call_id="done-1",
                    )
                ]
            ),
        ],
    )

    forked = engine.fork_session(sid, event_index=1, channel_type="web", unattended=False)

    assert forked.attributes.unattended is False
    forked_history = engine.session_mgr.load_history(forked.session_id)
    assert len(forked_history) == 2
    assert isinstance(forked_history[1], ModelResponse)
    response_part = forked_history[1].parts[0]
    assert isinstance(response_part, TextPart)
    assert response_part.content == "completed"


def test_fork_session_normalizes_unattended_history_with_thinking_parts(tmp_path: Path, db_factory) -> None:
    with _patch_sentinel():
        engine = _make_engine(tmp_path, session_factory=db_factory)

    source = engine.session_mgr.create_session(user="thies", unattended=True)
    sid = source.session_id
    engine.get_or_activate(sid)
    engine.session_mgr.append_events(
        sid,
        [
            {"role": "user", "content": "run on your own"},
            {"role": "assistant", "content": "completed"},
        ],
    )
    engine.session_mgr.save_history(
        sid,
        [
            ModelRequest(parts=[UserPromptPart(content="run on your own")]),
            ModelResponse(
                parts=[
                    ThinkingPart(content="working through result"),
                    ToolCallPart(
                        tool_name="task_done",
                        args={"result": "completed"},
                        tool_call_id="done-1",
                    ),
                ]
            ),
            ModelRequest(
                parts=[
                    ToolReturnPart(
                        tool_name="task_done",
                        content="Final result processed.",
                        tool_call_id="done-1",
                    )
                ]
            ),
        ],
    )

    forked = engine.fork_session(sid, event_index=1, channel_type="web", unattended=False)

    forked_history = engine.session_mgr.load_history(forked.session_id)
    assert len(forked_history) == 2
    assert isinstance(forked_history[1], ModelResponse)
    response_part = forked_history[1].parts[0]
    assert isinstance(response_part, TextPart)
    assert response_part.content == "completed"


def test_handle_token_chunk_promotes_activity_and_broadcasts(tmp_path: Path, db_factory) -> None:
    async def _run() -> None:
        with _patch_sentinel():
            engine = _make_engine(tmp_path, session_factory=db_factory)

        state = engine.session_mgr.create_session(user="thies")
        sid = state.session_id
        active = engine.get_or_activate(sid)
        subscriber = _FakeSubscriber()
        engine.subscribe(sid, subscriber)

        started_at = datetime.now(tz=UTC)
        llm_state = LlmRequestState(
            request_id="req-token",
            source="agent",
            model_name="anthropic:claude-haiku-4-5",
            started_at=started_at,
            first_text_at=started_at,
            phase="generating",
        )

        with patch("carapace.session.engine.note_llm_request_text", return_value=llm_state):
            await engine._handle_token_chunk(active, "hello")

        assert subscriber.token_chunks == ["hello"]
        assert active.llm_request_state is not None
        assert active.llm_request_state.phase == "generating"
        assert subscriber.llm_activity_updates
        assert subscriber.llm_activity_updates[-1] is not None
        assert subscriber.llm_activity_updates[-1].phase == "generating"
        persisted = engine.session_mgr.load_llm_request_state(sid)
        assert persisted is not None
        assert persisted.phase == "generating"

    asyncio.run(_run())


def test_handle_thinking_token_chunk_updates_buffer_and_broadcasts(tmp_path: Path, db_factory) -> None:
    async def _run() -> None:
        with _patch_sentinel():
            engine = _make_engine(tmp_path, session_factory=db_factory)

        state = engine.session_mgr.create_session(user="thies")
        sid = state.session_id
        active = engine.get_or_activate(sid)
        subscriber = _FakeSubscriber()
        engine.subscribe(sid, subscriber)

        started_at = datetime.now(tz=UTC)
        llm_state = LlmRequestState(
            request_id="req-thinking",
            source="agent",
            model_name="anthropic:claude-haiku-4-5",
            started_at=started_at,
            first_thinking_at=started_at,
            phase="thinking",
        )

        with patch("carapace.session.engine.note_llm_request_thinking", return_value=llm_state):
            await engine._handle_thinking_token_chunk(active, "ponder")

        assert subscriber.thinking_chunks == ["ponder"]
        assert active.llm_request_thinking == {"req-thinking": "ponder"}
        assert active.llm_request_state is not None
        assert active.llm_request_state.phase == "thinking"
        assert subscriber.llm_activity_updates
        assert subscriber.llm_activity_updates[-1] is not None
        assert subscriber.llm_activity_updates[-1].phase == "thinking"
        persisted = engine.session_mgr.load_llm_request_state(sid)
        assert persisted is not None
        assert persisted.phase == "thinking"

    asyncio.run(_run())


def test_truncate_incomplete_events_keeps_completed_user_approved_exec(tmp_path: Path, db_factory) -> None:
    with _patch_sentinel():
        engine = _make_engine(tmp_path, session_factory=db_factory)

    sid = engine.session_mgr.create_session(user="thies").session_id

    reviewing_tool_id = engine._record_tool_call_event(
        sid,
        tool="exec",
        args={"command": "ls"},
        detail="[sentinel] reviewing",
        approval_source="sentinel",
    )
    escalated_tool_id = engine._record_tool_call_event(
        sid,
        tool="exec",
        args={"command": "ls"},
        detail="[sentinel: escalate] needs approval",
        approval_source="sentinel",
        approval_verdict="escalate",
        approval_explanation="needs approval",
    )
    approved_tool_id = engine._record_tool_call_event(
        sid,
        tool="exec",
        args={"command": "ls"},
        detail="[user approved]",
        approval_source="user",
        approval_verdict="allow",
        approval_explanation="user approved",
    )

    assert reviewing_tool_id == escalated_tool_id == approved_tool_id

    engine.session_mgr.append_events(
        sid,
        [
            {
                "role": "tool_result",
                "tool": "exec",
                "result": "ok",
                "exit_code": 0,
                "tool_id": approved_tool_id,
            },
            {
                "role": "tool_call",
                "tool": "exec",
                "args": {"command": "pwd"},
                "detail": "[safe-list] auto-allowed",
                "approval_source": "safe-list",
                "approval_verdict": "allow",
                "approval_explanation": "auto-allowed",
                "tool_id": "later-exec",
            },
        ],
    )

    truncated = engine._truncate_incomplete_events(engine.session_mgr.load_events(sid))

    assert all("timestamp" in event for event in truncated)
    assert _without_timestamps(truncated) == [
        {
            "role": "tool_call",
            "tool": "exec",
            "args": {"command": "ls", "title": None},
            "detail": "[user approved]",
            "approval_source": "user",
            "approval_verdict": "allow",
            "approval_explanation": "user approved",
            "tool_id": approved_tool_id,
        },
        {
            "role": "tool_result",
            "tool": "exec",
            "result": "ok",
            "exit_code": 0,
            "tool_id": approved_tool_id,
        },
    ]


def test_available_model_entries_override_default_with_metadata(tmp_path: Path, db_factory):
    """``available_models`` lists every selectable model; duplicate id keeps last row metadata."""
    from carapace.config import build_config
    from carapace.models.config import AgentConfig, AvailableModelEntry

    agent = AgentConfig(
        model="anthropic:alpha",
        sentinel_model="anthropic:beta",
        title_model="anthropic:gamma",
        available_models=[
            AvailableModelEntry(provider="anthropic", name="alpha", max_input_tokens=424242),
            AvailableModelEntry(provider="anthropic", name="beta"),
            AvailableModelEntry(provider="anthropic", name="gamma"),
        ],
    )
    config = build_config(tmp_path).model_copy(update={"agent": agent})
    engine = _make_engine(tmp_path, session_factory=db_factory, config=config)
    by_id = {e.model_id: e for e in engine.available_model_entries}
    assert by_id["anthropic:alpha"].max_input_tokens == 424242
    ids = [e.model_id for e in engine.available_model_entries]
    assert ids == sorted(ids)


def test_user_message_from_self(tmp_path: Path, db_factory):
    """Origin subscriber gets from_self=True, others get from_self=False."""

    async def _run() -> None:
        engine = _make_engine(tmp_path, session_factory=db_factory)
        state = engine.session_mgr.create_session(user="thies")
        sid = state.session_id
        active = engine.get_or_activate(sid)

        origin = _FakeSubscriber()
        other = _FakeSubscriber()
        engine.subscribe(sid, origin)
        engine.subscribe(sid, other)

        async def _noop_turn(*_a: Any, **_kw: Any) -> tuple[list[Any], str, str, None]:
            return [], "ok", "", None

        with patch("carapace.agent.loop.run_agent_turn", new=_noop_turn):
            await engine.submit_message(sid, "hello", origin=origin)
            await asyncio.sleep(0.1)

        assert origin.user_messages == [("hello", True)]
        assert other.user_messages == [("hello", False)]
        await _drain_background_tasks(active)

    with _patch_sentinel():
        asyncio.run(_run())


def test_user_message_no_origin(tmp_path: Path, db_factory):
    """When origin is None, all subscribers get from_self=False."""

    async def _run() -> None:
        engine = _make_engine(tmp_path, session_factory=db_factory)
        state = engine.session_mgr.create_session(user="thies")
        sid = state.session_id
        active = engine.get_or_activate(sid)

        sub_a = _FakeSubscriber()
        sub_b = _FakeSubscriber()
        engine.subscribe(sid, sub_a)
        engine.subscribe(sid, sub_b)

        async def _noop_turn(*_a: Any, **_kw: Any) -> tuple[list[Any], str, str, None]:
            return [], "ok", "", None

        with patch("carapace.agent.loop.run_agent_turn", new=_noop_turn):
            await engine.submit_message(sid, "hi")
            await asyncio.sleep(0.1)

        assert sub_a.user_messages == [("hi", False)]
        assert sub_b.user_messages == [("hi", False)]
        await _drain_background_tasks(active)

    with _patch_sentinel():
        asyncio.run(_run())


def test_submit_message_clears_pending_turn_notifications(tmp_path: Path, db_factory):
    async def _run() -> None:
        engine = _make_engine(tmp_path, session_factory=db_factory)
        engine._notification_router = AsyncMock()
        engine._notification_router.clear_notifications = AsyncMock(
            return_value=type("Delivery", (), {"delivered_subscription_ids": {"sub-1"}})()
        )
        state = engine.session_mgr.create_session(user="thies")
        sid = state.session_id
        active = engine.get_or_activate(sid)
        active.pending_notifications = {"done:test:1:attended_turn_completed": {"sub-1"}}

        async def _noop_run_turn(*_args: Any, **_kwargs: Any) -> None:
            return None

        engine._run_turn = _noop_run_turn  # type: ignore[method-assign]

        await engine.submit_message(sid, "hello")
        await asyncio.sleep(0)

        engine._notification_router.clear_notifications.assert_awaited_once_with(
            session_id=sid,
            notif_id="done:test:1:attended_turn_completed",
            subscription_ids={"sub-1"},
        )
        assert active.pending_notifications == {}

    with _patch_sentinel():
        asyncio.run(_run())


def test_escalation_callback_dispatches_and_clears_notification(tmp_path: Path, db_factory):
    async def _run() -> None:
        engine = _make_engine(tmp_path, session_factory=db_factory)
        engine._notification_router = AsyncMock()
        engine._notification_router.dispatch_escalation = AsyncMock(
            return_value=type("Delivery", (), {"delivered_subscription_ids": {"sub-1"}})()
        )
        engine._notification_router.clear_notifications = AsyncMock(
            return_value=type("Delivery", (), {"delivered_subscription_ids": {"sub-1"}})()
        )
        sid = engine.session_mgr.create_session(user="thies").session_id
        active = engine.get_or_activate(sid)
        callback = engine._make_escalation_cb(active)

        task = asyncio.create_task(callback(sid, "example.com", {"kind": "domain_access", "command": "curl"}))
        await asyncio.sleep(0)

        engine._notification_router.dispatch_escalation.assert_awaited_once()
        pending = active.pending_escalations[0]
        await engine.submit_approval(
            sid, type("Resp", (), {"request_id": pending["request_id"], "decision": "allow", "message": None})()
        )
        result = await task

        assert result.allowed is True
        engine._notification_router.clear_notifications.assert_awaited_once_with(
            session_id=sid,
            notif_id=f"esc:{sid}:{pending['request_id']}",
            subscription_ids={"sub-1"},
        )
        assert active.pending_notifications == {}

    with _patch_sentinel():
        asyncio.run(_run())


def test_finalize_successful_turn_dispatches_attended_notification(tmp_path: Path, db_factory):
    async def _run() -> None:
        engine = _make_engine(tmp_path, session_factory=db_factory)
        engine._notification_router = AsyncMock()
        engine._notification_router.dispatch_turn_outcome = AsyncMock(
            return_value=type("Delivery", (), {"delivered_subscription_ids": {"sub-1"}})()
        )
        sid = engine.session_mgr.create_session(user="thies").session_id
        active = engine.get_or_activate(sid)
        engine.session_mgr.append_events(sid, [{"role": "user", "content": "hello"}])

        await engine._finalize_successful_turn(active, sid, [], "done", "thinking")

        engine._notification_router.dispatch_turn_outcome.assert_awaited_once_with(
            session_id=sid,
            assistant_event_index=1,
            kind="attended_turn_completed",
            title="Session Update",
            body="done",
        )
        assert active.pending_notifications == {f"done:{sid}:1:attended_turn_completed": {"sub-1"}}
        await _drain_background_tasks(active)

    with _patch_sentinel():
        asyncio.run(_run())


def test_retry_latest_turn_preserves_attachments(tmp_path: Path, db_factory):
    async def _run() -> None:
        engine = _make_engine(tmp_path, session_factory=db_factory)
        sid = engine.session_mgr.create_session(user="thies").session_id
        engine.get_or_activate(sid)
        engine.session_mgr.append_events(
            sid,
            [
                {
                    "role": "user",
                    "content": "look at this",
                    "attachments": [{"name": "abc.png", "path": "/tmp/abc-1a2b.png"}],
                },
                {"role": "assistant", "content": "ok"},
            ],
        )
        engine.submit_message = AsyncMock()
        engine._rewrite_session_transcript = lambda *_a, **_k: None

        await engine.retry_latest_turn(sid)

        engine.submit_message.assert_awaited_once()
        kwargs = engine.submit_message.await_args.kwargs
        assert [a.path for a in kwargs["attachments"]] == ["/tmp/abc-1a2b.png"]

    with _patch_sentinel():
        asyncio.run(_run())


def test_finalize_failed_turn_dispatches_unattended_failure_notification(tmp_path: Path, db_factory):
    async def _run() -> None:
        engine = _make_engine(tmp_path, session_factory=db_factory)
        engine._notification_router = AsyncMock()
        engine._notification_router.dispatch_turn_outcome = AsyncMock(
            return_value=type("Delivery", (), {"delivered_subscription_ids": {"sub-1"}})()
        )
        sid = engine.session_mgr.create_session(user="thies", unattended=True).session_id
        active = engine.get_or_activate(sid)
        engine.session_mgr.append_events(sid, [{"role": "user", "content": "run"}])

        await engine._finalize_failed_turn(
            active,
            sid,
            "run",
            terminal_message="The previous turn failed before completion.",
        )

        engine._notification_router.dispatch_turn_outcome.assert_awaited_once_with(
            session_id=sid,
            assistant_event_index=1,
            kind="unattended_turn_failed",
            title="Job Failed",
            body="The previous turn failed before completion.",
        )
        assert active.pending_notifications == {f"done:{sid}:1:unattended_turn_failed": {"sub-1"}}

    with _patch_sentinel():
        asyncio.run(_run())
