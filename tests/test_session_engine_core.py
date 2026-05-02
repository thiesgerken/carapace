"""Core session engine tests unrelated to lifecycle retries and slash commands."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart

import carapace.usage as usage_mod
from carapace.models import ContextGrant, CredentialRegistryProtocol, SkillCredentialDecl
from carapace.sandbox.state import SessionSandboxSnapshot
from carapace.usage import LlmRequestState, ModelUsage
from tests.session_helpers import _FakeSubscriber, _make_engine, _patch_sentinel, _without_timestamps


@pytest.mark.anyio
async def test_skill_activation_inputs_use_context_grant(tmp_path: Path):
    """Automatic skill setup reuses approved env/file credentials from the persisted context grant."""
    skill_name = "reinject-skill"
    skill_dir = tmp_path / "skills" / skill_name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(f"---\nname: {skill_name}\n---\n")
    (skill_dir / "carapace.yaml").write_text(
        "credentials:\n"
        "  - vault_path: vault/secret\n"
        "    description: API key\n"
        "    env_var: API_KEY\n"
        "    file: .secrets/key.txt\n"
    )

    with _patch_sentinel():
        engine = _make_engine(tmp_path)

    state = engine.session_mgr.create_session()
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

    mock_reg = AsyncMock(spec=CredentialRegistryProtocol)
    mock_reg.fetch = AsyncMock(return_value="secret-value")
    engine._credential_registry = mock_reg

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


def test_record_tool_call_event_reuses_sentinel_row_for_user_decision(tmp_path: Path) -> None:
    with _patch_sentinel():
        engine = _make_engine(tmp_path)

    sid = engine.session_mgr.create_session().session_id

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


def test_record_tool_call_event_reuses_proxy_domain_row_for_queued_reviewing_and_final(tmp_path: Path) -> None:
    with _patch_sentinel():
        engine = _make_engine(tmp_path)

    sid = engine.session_mgr.create_session().session_id

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


def test_fork_session_copies_transcript_and_security_context(tmp_path: Path) -> None:
    with _patch_sentinel():
        engine = _make_engine(tmp_path)

    source = engine.session_mgr.create_session(channel_type="matrix", channel_ref="!room:example.com", private=True)
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
    assert engine.session_mgr.load_usage(forked.session_id).models == {}
    assert engine.session_mgr.load_sandbox_snapshot(forked.session_id) is None
    assert len(engine.session_mgr.load_events(sid)) == 5


def test_handle_token_chunk_promotes_activity_and_broadcasts(tmp_path: Path) -> None:
    async def _run() -> None:
        with _patch_sentinel():
            engine = _make_engine(tmp_path)

        state = engine.session_mgr.create_session()
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


def test_handle_thinking_token_chunk_updates_buffer_and_broadcasts(tmp_path: Path) -> None:
    async def _run() -> None:
        with _patch_sentinel():
            engine = _make_engine(tmp_path)

        state = engine.session_mgr.create_session()
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


def test_truncate_incomplete_events_keeps_completed_user_approved_exec(tmp_path: Path) -> None:
    with _patch_sentinel():
        engine = _make_engine(tmp_path)

    sid = engine.session_mgr.create_session().session_id

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
            "args": {"command": "ls"},
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


def test_available_model_entries_override_default_with_metadata(tmp_path: Path):
    """``available_models`` lists every selectable model; duplicate id in YAML keeps last row metadata."""
    (tmp_path / "config.yaml").write_text(
        "agent:\n"
        "  model: anthropic:alpha\n"
        "  sentinel_model: anthropic:beta\n"
        "  title_model: anthropic:gamma\n"
        "  available_models:\n"
        "    - provider: anthropic\n"
        "      name: alpha\n"
        "      max_input_tokens: 424242\n"
        "    - provider: anthropic\n"
        "      name: beta\n"
        "    - provider: anthropic\n"
        "      name: gamma\n"
    )
    engine = _make_engine(tmp_path)
    by_id = {e.model_id: e for e in engine.available_model_entries}
    assert by_id["anthropic:alpha"].max_input_tokens == 424242
    ids = [e.model_id for e in engine.available_model_entries]
    assert ids == sorted(ids)


def test_user_message_from_self(tmp_path: Path):
    """Origin subscriber gets from_self=True, others get from_self=False."""

    async def _run() -> None:
        engine = _make_engine(tmp_path)
        state = engine.session_mgr.create_session()
        sid = state.session_id

        origin = _FakeSubscriber()
        other = _FakeSubscriber()
        engine.subscribe(sid, origin)
        engine.subscribe(sid, other)

        async def _noop_turn(*_a: Any, **_kw: Any) -> tuple[list[Any], str, str]:
            return [], "ok", ""

        with patch("carapace.agent.loop.run_agent_turn", new=_noop_turn):
            await engine.submit_message(sid, "hello", origin=origin)
            await asyncio.sleep(0.1)

        assert origin.user_messages == [("hello", True)]
        assert other.user_messages == [("hello", False)]

    with _patch_sentinel():
        asyncio.run(_run())


def test_user_message_no_origin(tmp_path: Path):
    """When origin is None, all subscribers get from_self=False."""

    async def _run() -> None:
        engine = _make_engine(tmp_path)
        state = engine.session_mgr.create_session()
        sid = state.session_id

        sub_a = _FakeSubscriber()
        sub_b = _FakeSubscriber()
        engine.subscribe(sid, sub_a)
        engine.subscribe(sid, sub_b)

        async def _noop_turn(*_a: Any, **_kw: Any) -> tuple[list[Any], str, str]:
            return [], "ok", ""

        with patch("carapace.agent.loop.run_agent_turn", new=_noop_turn):
            await engine.submit_message(sid, "hi")
            await asyncio.sleep(0.1)

        assert sub_a.user_messages == [("hi", False)]
        assert sub_b.user_messages == [("hi", False)]

    with _patch_sentinel():
        asyncio.run(_run())
