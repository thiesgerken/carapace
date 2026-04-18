"""Tests for SessionManager (no LLM tokens needed)."""

from __future__ import annotations

import asyncio
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, ToolCallPart, ToolReturnPart, UserPromptPart
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from carapace.bootstrap import ensure_data_dir
from carapace.config import load_config
from carapace.credentials import CredentialRegistry
from carapace.git.store import GitStore
from carapace.models import ContextGrant, CredentialRegistryProtocol, SessionBudget, SkillCredentialDecl, ToolResult
from carapace.sandbox.manager import SandboxManager
from carapace.security.context import UserEscalationDecision, format_denial_message, normalize_optional_message
from carapace.security.sentinel import Sentinel
from carapace.session import SessionEngine, SessionManager
from carapace.session.engine import _non_slash_user_message_count
from carapace.skills import SkillRegistry
from carapace.usage import ModelUsage, SessionBudgetExceededError
from carapace.ws_models import ApprovalRequest, TurnUsage


def _patch_sentinel():
    """Patch Sentinel class so its instances pass isinstance checks."""
    mock_cls = MagicMock()
    mock_cls.return_value = MagicMock(spec=Sentinel)
    return patch("carapace.session.engine.Sentinel", mock_cls)


def test_create_session(tmp_path: Path):
    mgr = SessionManager(tmp_path)
    state = mgr.create_session()
    assert len(state.session_id) == 25  # 2026-03-08-10-22-abcd1234
    assert state.channel_type == "cli"


def test_create_session_persists_budget(tmp_path: Path):
    mgr = SessionManager(tmp_path)
    budget = SessionBudget(input_tokens=1_000, cost_usd=Decimal("5.00"))
    state = mgr.create_session(budget=budget)

    resumed = mgr.resume_session(state.session_id)
    assert resumed is not None
    assert resumed.budget.input_tokens == 1_000
    assert resumed.budget.cost_usd == Decimal("5.00")


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
    from carapace.models import ContextGrant, SkillCredentialDecl

    mgr = SessionManager(tmp_path)
    state = mgr.create_session()
    state.context_grants["my-skill"] = ContextGrant(
        skill_name="my-skill",
        domains={"example.com"},
        credential_decls=[SkillCredentialDecl(vault_path="dev/test", description="test cred")],
    )
    mgr.save_state(state)

    resumed = mgr.resume_session(state.session_id)
    assert resumed is not None
    assert "my-skill" in resumed.context_grants
    assert "dev/test" in resumed.context_grants["my-skill"].vault_paths


def test_normalize_optional_message_strips_blank_values() -> None:
    assert normalize_optional_message(None) is None
    assert normalize_optional_message("   ") is None
    assert normalize_optional_message("  blocked by user  ") == "blocked by user"


def test_format_denial_message_includes_source_and_message() -> None:
    assert format_denial_message("sentinel", "dangerous command") == (
        "Sentinel denied this operation. dangerous command"
    )
    assert format_denial_message("user", None) == "User denied this operation."


def test_missing_user_escalation_callback_denies() -> None:
    from carapace.security.context import SessionSecurity

    security = SessionSecurity("session-1")
    result = asyncio.run(security.escalate_to_user("example.com", {"kind": "domain_access"}))
    assert result == UserEscalationDecision(allowed=False)


@pytest.mark.anyio
async def test_reinject_skill_credentials_uses_context_grant(tmp_path: Path):
    """Venv/container rebuild re-fetches file creds when the skill has a persisted context grant."""
    skill_name = "reinject-skill"
    skill_dir = tmp_path / "skills" / skill_name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(f"---\nname: {skill_name}\n---\n")
    (skill_dir / "carapace.yaml").write_text(
        "credentials:\n  - vault_path: vault/secret\n    description: API key\n    file: .secrets/key.txt\n"
    )

    with _patch_sentinel():
        engine = _make_engine(tmp_path)

    state = engine.session_mgr.create_session()
    sid = state.session_id
    active = engine.get_or_activate(sid)
    active.state.context_grants[skill_name] = ContextGrant(
        skill_name=skill_name,
        credential_decls=[
            SkillCredentialDecl(vault_path="vault/secret", description="API key", file=".secrets/key.txt"),
        ],
    )

    mock_reg = AsyncMock(spec=CredentialRegistryProtocol)
    mock_reg.fetch = AsyncMock(return_value="secret-value")
    engine._credential_registry = mock_reg

    result = await engine._reinject_skill_credentials(sid, skill_name)
    assert result == [(".secrets/key.txt", "secret-value")]
    mock_reg.fetch.assert_awaited_once_with("vault/secret")

    active.state.context_grants.pop(skill_name, None)
    mock_reg.fetch.reset_mock()
    assert await engine._reinject_skill_credentials(sid, skill_name) == []
    mock_reg.fetch.assert_not_called()

    # Reload from disk when session is not active (same path as idle resume + venv sync)
    active.state.context_grants[skill_name] = ContextGrant(
        skill_name=skill_name,
        credential_decls=[
            SkillCredentialDecl(vault_path="vault/secret", description="API key", file=".secrets/key.txt"),
        ],
    )
    engine.session_mgr.save_state(active.state)
    engine.deactivate(sid)
    mock_reg.fetch.reset_mock()
    mock_reg.fetch = AsyncMock(return_value="from-disk")
    assert await engine._reinject_skill_credentials(sid, skill_name) == [(".secrets/key.txt", "from-disk")]


# ---------------------------------------------------------------------------
# SessionEngine: on_user_message from_self tests
# ---------------------------------------------------------------------------


class _FakeSubscriber:
    """Minimal subscriber that records calls."""

    def __init__(self) -> None:
        self.user_messages: list[tuple[str, bool]] = []
        self.errors: list[str] = []
        self.cancelled: int = 0
        self.title_updates: list[tuple[str, TurnUsage | None]] = []

    async def on_user_message(self, content: str, *, from_self: bool) -> None:
        self.user_messages.append((content, from_self))

    async def on_tool_call(self, tool: str, args: dict[str, Any], detail: str) -> None:
        pass

    async def on_tool_result(self, result: ToolResult) -> None:
        pass

    async def on_done(self, content: str, usage: TurnUsage) -> None:
        pass

    async def on_error(self, detail: str) -> None:
        self.errors.append(detail)

    async def on_cancelled(self) -> None:
        self.cancelled += 1

    async def on_approval_request(self, req: ApprovalRequest) -> None:
        pass

    async def on_proxy_approval_request(self, request_id: str, domain: str, command: str) -> None:
        pass

    async def on_title_update(self, title: str, usage: TurnUsage | None = None) -> None:
        self.title_updates.append((title, usage))

    async def on_domain_info(self, domain: str, detail: str) -> None:
        pass


def _make_engine(tmp_path: Path) -> SessionEngine:
    ensure_data_dir(tmp_path)
    config = load_config(tmp_path)
    session_mgr = SessionManager(tmp_path)
    registry = SkillRegistry(tmp_path / "skills")
    skill_catalog = registry.scan()
    sandbox_mgr = MagicMock(spec=SandboxManager)
    sandbox_mgr.get_domain_info.return_value = []
    return SessionEngine(
        config=config,
        data_dir=tmp_path,
        knowledge_dir=tmp_path,
        git_store=MagicMock(spec=GitStore),
        session_mgr=session_mgr,
        skill_catalog=skill_catalog,
        agent_model=None,
        sandbox_mgr=sandbox_mgr,
        credential_registry=CredentialRegistry(),
        model_factory=lambda _name: TestModel(),
    )


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
    ensure_data_dir(tmp_path)
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

        # Mock run_agent_turn to avoid needing LLM
        async def _noop_turn(*_a: Any, **_kw: Any) -> str:
            return "ok"

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

        async def _noop_turn(*_a: Any, **_kw: Any) -> str:
            return "ok"

        with patch("carapace.agent.loop.run_agent_turn", new=_noop_turn):
            await engine.submit_message(sid, "hi")
            await asyncio.sleep(0.1)

        assert sub_a.user_messages == [("hi", False)]
        assert sub_b.user_messages == [("hi", False)]

    with _patch_sentinel():
        asyncio.run(_run())


# ---------------------------------------------------------------------------
# SessionEngine lifecycle tests
# ---------------------------------------------------------------------------


def test_subscribe_duplicate_prevention(tmp_path: Path):
    """Subscribing the same subscriber twice does not duplicate it."""
    with _patch_sentinel():
        engine = _make_engine(tmp_path)
        state = engine.session_mgr.create_session()
        sid = state.session_id

        sub = _FakeSubscriber()
        engine.subscribe(sid, sub)
        engine.subscribe(sid, sub)

        active = engine.get_active(sid)
        assert active is not None
        assert active.subscribers.count(sub) == 1


def test_get_active_returns_none_before_activation(tmp_path: Path):
    """get_active returns None for a session that hasn't been activated."""
    engine = _make_engine(tmp_path)
    state = engine.session_mgr.create_session()
    assert engine.get_active(state.session_id) is None


def test_get_or_activate_loads_session(tmp_path: Path):
    """get_or_activate loads the session from disk and makes it active."""
    with _patch_sentinel():
        engine = _make_engine(tmp_path)
        state = engine.session_mgr.create_session()
        sid = state.session_id

        assert engine.get_active(sid) is None
        active = engine.get_or_activate(sid)
        assert active is not None
        assert active.state.session_id == sid
        assert engine.get_active(sid) is active


def test_get_or_activate_unknown_session_raises(tmp_path: Path):
    """get_or_activate raises KeyError for a nonexistent session."""
    engine = _make_engine(tmp_path)
    with pytest.raises(KeyError):
        engine.get_or_activate("nonexistent")


def test_deactivate_removes_session(tmp_path: Path):
    """deactivate removes the session from active memory."""
    with _patch_sentinel():
        engine = _make_engine(tmp_path)
        state = engine.session_mgr.create_session()
        sid = state.session_id

        engine.get_or_activate(sid)
        assert engine.get_active(sid) is not None

        engine.deactivate(sid)
        assert engine.get_active(sid) is None


def test_deactivate_idempotent(tmp_path: Path):
    """Deactivating an already-deactivated session does not raise."""
    engine = _make_engine(tmp_path)
    engine.deactivate("nonexistent")  # should not raise


def test_unsubscribe_removes_subscriber(tmp_path: Path):
    """unsubscribe removes the subscriber from the list."""
    with _patch_sentinel():
        engine = _make_engine(tmp_path)
        state = engine.session_mgr.create_session()
        sid = state.session_id

        sub = _FakeSubscriber()
        engine.subscribe(sid, sub)
        active = engine.get_active(sid)
        assert sub in active.subscribers

        engine.unsubscribe(sid, sub)
        assert sub not in active.subscribers


def test_unsubscribe_nonexistent_is_safe(tmp_path: Path):
    """Unsubscribing a subscriber that was never added does not raise."""
    with _patch_sentinel():
        engine = _make_engine(tmp_path)
        state = engine.session_mgr.create_session()
        sid = state.session_id

        engine.get_or_activate(sid)
        engine.unsubscribe(sid, _FakeSubscriber())  # should not raise


def test_unsubscribe_saves_usage_when_last(tmp_path: Path):
    """Usage is persisted to disk when the last subscriber disconnects."""
    with _patch_sentinel():
        engine = _make_engine(tmp_path)
        state = engine.session_mgr.create_session()
        sid = state.session_id

        sub = _FakeSubscriber()
        engine.subscribe(sid, sub)

        # Modify usage so we can detect whether it was saved
        active = engine.get_active(sid)
        active.usage_tracker.models["test-model"] = ModelUsage(input_tokens=42)

        engine.unsubscribe(sid, sub)

        # Reload from disk
        reloaded = engine.session_mgr.load_usage(sid)
        assert reloaded.total_input == 42


def test_submit_message_busy_broadcasts_error(tmp_path: Path):
    """submit_message rejects with an error if agent is already running."""

    async def _run() -> None:
        engine = _make_engine(tmp_path)
        state = engine.session_mgr.create_session()
        sid = state.session_id

        sub = _FakeSubscriber()
        engine.subscribe(sid, sub)

        # Simulate a running agent task that never finishes
        active = engine.get_active(sid)
        active.agent_task = asyncio.create_task(asyncio.sleep(999))

        await engine.submit_message(sid, "should fail")

        assert any("busy" in e.lower() for e in sub.errors)

        active.agent_task.cancel()
        with __import__("contextlib").suppress(asyncio.CancelledError):
            await active.agent_task

    with _patch_sentinel():
        asyncio.run(_run())


def test_submit_cancel_stops_task(tmp_path: Path):
    """submit_cancel cancels the running agent task."""

    async def _run() -> None:
        engine = _make_engine(tmp_path)
        state = engine.session_mgr.create_session()
        sid = state.session_id

        engine.subscribe(sid, _FakeSubscriber())
        active = engine.get_active(sid)

        # Simulate a running agent task
        active.agent_task = asyncio.create_task(asyncio.sleep(999))

        await engine.submit_cancel(sid)
        assert active.agent_task is None

    with _patch_sentinel():
        asyncio.run(_run())


def test_submit_cancel_noop_when_inactive(tmp_path: Path):
    """submit_cancel is a no-op when session is not active."""

    async def _run() -> None:
        engine = _make_engine(tmp_path)
        await engine.submit_cancel("nonexistent")  # should not raise

    asyncio.run(_run())


def test_handle_slash_command_session(tmp_path: Path):
    """handle_slash_command /session returns session metadata."""
    with _patch_sentinel():
        engine = _make_engine(tmp_path)
        state = engine.session_mgr.create_session()
        sid = state.session_id
        engine.get_or_activate(sid)

        async def _run() -> None:
            result = await engine.handle_slash_command(sid, "/session")
            assert result is not None
            assert result["command"] == "session"
            assert result["data"]["session_id"] == sid

        asyncio.run(_run())


def test_handle_slash_command_unknown(tmp_path: Path):
    """handle_slash_command returns None for unknown commands."""
    with _patch_sentinel():
        engine = _make_engine(tmp_path)
        state = engine.session_mgr.create_session()
        sid = state.session_id
        engine.get_or_activate(sid)

        async def _run() -> None:
            assert await engine.handle_slash_command(sid, "/nonexistent") is None

        asyncio.run(_run())


def test_handle_slash_command_retitle_sets_title(tmp_path: Path):
    """``/retitle TEXT`` stores the title and returns a message."""
    with _patch_sentinel():
        engine = _make_engine(tmp_path)
        state = engine.session_mgr.create_session()
        sid = state.session_id
        active = engine.get_or_activate(sid)

        async def _run() -> None:
            result = await engine.handle_slash_command(sid, "/retitle Hello world")
            assert result is not None
            assert result["command"] == "retitle"
            assert "Hello world" in result["data"]["message"]
            assert active.state.title == "Hello world"
            reloaded = engine.session_mgr.load_state(sid)
            assert reloaded is not None
            assert reloaded.title == "Hello world"

        asyncio.run(_run())


def test_handle_slash_command_retitle_regenerates(tmp_path: Path):
    """``/retitle`` with no args runs title generation."""
    with _patch_sentinel():
        engine = _make_engine(tmp_path)
        state = engine.session_mgr.create_session()
        sid = state.session_id
        active = engine.get_or_activate(sid)
        engine.session_mgr.append_events(sid, [{"role": "user", "content": "talk about cats"}])

        async def _run() -> None:
            with patch(
                "carapace.session.engine.generate_title",
                new=AsyncMock(return_value="📌 Cats chat"),
            ):
                result = await engine.handle_slash_command(sid, "/retitle")
            assert result is not None
            assert result["command"] == "retitle"
            assert "Cats chat" in result["data"]["message"]
            assert active.state.title == "📌 Cats chat"

        asyncio.run(_run())


def test_handle_slash_command_budget_sets_and_clears(tmp_path: Path):
    with _patch_sentinel():
        engine = _make_engine(tmp_path)
        state = engine.session_mgr.create_session()
        sid = state.session_id
        engine.get_or_activate(sid)

        async def _run() -> None:
            initial = await engine.handle_slash_command(sid, "/budget")
            assert initial is not None
            assert "usage_hint" in initial["data"]
            assert "/budget input N" in initial["data"]["usage_hint"]

            set_result = await engine.handle_slash_command(sid, "/budget input 1000")
            assert set_result is not None
            assert set_result["command"] == "budget"
            assert set_result["data"]["message"] == "Set input token budget to 1,000 tokens."
            assert set_result["data"]["gauges"][0]["key"] == "input"

            cleared = await engine.handle_slash_command(sid, "/budget input 0")
            assert cleared is not None
            assert cleared["data"]["message"] == "Cleared input token budget."
            assert cleared["data"]["gauges"] == []

            reloaded = engine.session_mgr.load_state(sid)
            assert reloaded is not None
            assert reloaded.budget.input_tokens is None

        asyncio.run(_run())


def test_handle_slash_command_budget_accepts_k_and_m_suffixes(tmp_path: Path):
    with _patch_sentinel():
        engine = _make_engine(tmp_path)
        state = engine.session_mgr.create_session()
        sid = state.session_id
        engine.get_or_activate(sid)

        async def _run() -> None:
            input_result = await engine.handle_slash_command(sid, "/budget input 100k")
            assert input_result is not None
            assert input_result["data"]["message"] == "Set input token budget to 100,000 tokens."

            output_result = await engine.handle_slash_command(sid, "/budget output 2M")
            assert output_result is not None
            assert output_result["data"]["message"] == "Set output token budget to 2,000,000 tokens."

            reloaded = engine.session_mgr.load_state(sid)
            assert reloaded is not None
            assert reloaded.budget.input_tokens == 100_000
            assert reloaded.budget.output_tokens == 2_000_000

        asyncio.run(_run())


def test_handle_slash_command_help_lists_budget(tmp_path: Path):
    with _patch_sentinel():
        engine = _make_engine(tmp_path)
        state = engine.session_mgr.create_session()
        sid = state.session_id
        engine.get_or_activate(sid)

        async def _run() -> None:
            result = await engine.handle_slash_command(sid, "/help")
            assert result is not None
            commands = result["data"]["commands"]
            assert any(item["command"] == "/budget" for item in commands)

        asyncio.run(_run())


def test_turn_usage_payload_contains_budget_gauges_without_agent_usage(tmp_path: Path):
    with _patch_sentinel():
        engine = _make_engine(tmp_path)
        state = engine.session_mgr.create_session(budget=SessionBudget(input_tokens=1_000))
        active = engine.get_or_activate(state.session_id)

        payload = engine._turn_usage_payload(active)

        assert payload is not None
        assert payload.budget_gauges[0].key == "input"
        assert payload.budget_gauges[0].current_value == "0 tokens"


def test_submit_message_budget_exhausted_broadcasts_error(tmp_path: Path):
    async def _run() -> None:
        engine = _make_engine(tmp_path)
        state = engine.session_mgr.create_session(budget=SessionBudget(input_tokens=100))
        sid = state.session_id
        sub = _FakeSubscriber()
        engine.subscribe(sid, sub)
        active = engine.get_active(sid)
        assert active is not None
        active.usage_tracker.models["test-model"] = ModelUsage(input_tokens=120)

        with patch("carapace.session.engine.run_agent_turn", new=AsyncMock()) as mocked_turn:
            await engine.submit_message(sid, "hello")
            await asyncio.sleep(0.1)

        mocked_turn.assert_not_awaited()
        assert any("Session budget reached" in err for err in sub.errors)

    with _patch_sentinel():
        asyncio.run(_run())


def test_submit_message_budget_exceeded_persists_history(tmp_path: Path):
    async def _run() -> None:
        engine = _make_engine(tmp_path)
        state = engine.session_mgr.create_session(budget=SessionBudget(input_tokens=1_000))
        sid = state.session_id
        sub = _FakeSubscriber()
        engine.subscribe(sid, sub)

        async def _fail_run_agent_turn(*_args: Any, on_messages_snapshot=None, **_kwargs: Any):
            snapshot = [ModelRequest(parts=[UserPromptPart(content="hello")])]
            if on_messages_snapshot is not None:
                on_messages_snapshot(snapshot)
            raise SessionBudgetExceededError("Session budget reached: input 1.0k tokens / 1.0k tokens", gauges=[])

        with patch("carapace.session.engine.run_agent_turn", new=_fail_run_agent_turn):
            await engine.submit_message(sid, "hello")
            await asyncio.sleep(0.1)

        history = engine.session_mgr.load_history(sid)
        assert history
        assert isinstance(history[0], ModelRequest)
        assert any(isinstance(part, UserPromptPart) and part.content == "hello" for part in history[0].parts)
        assert any("Session budget reached" in err for err in sub.errors)

    with _patch_sentinel():
        asyncio.run(_run())


def test_generate_title_skips_when_budget_exhausted(tmp_path: Path):
    async def _run() -> None:
        engine = _make_engine(tmp_path)
        state = engine.session_mgr.create_session(budget=SessionBudget(input_tokens=100))
        active = engine.get_or_activate(state.session_id)
        active.usage_tracker.models["test-model"] = ModelUsage(input_tokens=120)

        with patch("carapace.session.engine.generate_title", new=AsyncMock(return_value="ignored")) as mocked:
            title = await engine._generate_title(active, [{"role": "user", "content": "hello"}])

        assert title == ""
        mocked.assert_not_awaited()

    with _patch_sentinel():
        asyncio.run(_run())


def test_generate_title_persists_usage_and_broadcasts_usage(tmp_path: Path):
    async def _run() -> None:
        engine = _make_engine(tmp_path)
        state = engine.session_mgr.create_session(budget=SessionBudget(cost_usd=Decimal("5.00")))
        sid = state.session_id
        active = engine.get_or_activate(sid)
        sub = _FakeSubscriber()
        engine.subscribe(sid, sub)

        async def _fake_generate_title(*_args: Any, usage_tracker, **_kwargs: Any) -> str:
            usage_tracker.record(
                "anthropic:claude-haiku-4-5",
                "title",
                RunUsage(input_tokens=10, output_tokens=5, requests=1),
            )
            return "📌 hello"

        with patch("carapace.session.engine.generate_title", new=AsyncMock(side_effect=_fake_generate_title)):
            title = await engine._generate_title(active, [{"role": "user", "content": "hello"}])

        assert title == "📌 hello"
        stored_usage = engine.session_mgr.load_usage(sid)
        assert stored_usage.categories["title"].input_tokens == 10
        assert sub.title_updates
        assert sub.title_updates[0][0] == "📌 hello"
        assert sub.title_updates[0][1] is not None
        assert sub.title_updates[0][1].budget_gauges[0].key == "cost"

    with _patch_sentinel():
        asyncio.run(_run())


def test_handle_slash_command_inactive_session(tmp_path: Path):
    """handle_slash_command returns None for a session that isn't active."""
    engine = _make_engine(tmp_path)
    state = engine.session_mgr.create_session()

    async def _run() -> None:
        assert await engine.handle_slash_command(state.session_id, "/session") is None

    asyncio.run(_run())


def test_handle_slash_command_reload(tmp_path: Path):
    """handle_slash_command /reload calls reset_session and returns success."""
    with _patch_sentinel():
        engine = _make_engine(tmp_path)
        state = engine.session_mgr.create_session()
        sid = state.session_id
        engine.get_or_activate(sid)

        async def _run() -> None:
            result = await engine.handle_slash_command(sid, "/reload")
            assert result is not None
            assert result["command"] == "reload"
            assert "reset" in result["data"]["message"].lower() or "fresh" in result["data"]["message"].lower()
            engine._sandbox_mgr.reset_session.assert_called_once_with(sid)

        asyncio.run(_run())


def test_handle_slash_command_model_sets_all_three(tmp_path: Path):
    """``/model NAME`` applies the same id to agent, sentinel, and title."""
    with _patch_sentinel():
        engine = _make_engine(tmp_path)
        state = engine.session_mgr.create_session()
        sid = state.session_id
        active = engine.get_or_activate(sid)

        async def _run() -> None:
            result = await engine.handle_slash_command(sid, "/model openai:gpt-4o")
            assert result is not None
            assert result["command"] == "model"
            assert "models" in result["data"]
            for key in ("agent", "sentinel", "title"):
                assert result["data"]["models"][key]["current"] == "openai:gpt-4o"
            assert active.agent_model_name == "openai:gpt-4o"
            assert active.sentinel_model_name == "openai:gpt-4o"
            assert active.title_model_name == "openai:gpt-4o"

        asyncio.run(_run())


def test_handle_slash_command_model_agent_only(tmp_path: Path):
    """``/model-agent`` changes only the agent model."""
    with _patch_sentinel():
        engine = _make_engine(tmp_path)
        state = engine.session_mgr.create_session()
        sid = state.session_id
        active = engine.get_or_activate(sid)

        async def _run() -> None:
            result = await engine.handle_slash_command(sid, "/model-agent openai:gpt-4o")
            assert result is not None
            assert result["command"] == "model-agent"
            assert result["data"]["current"] == "openai:gpt-4o"
            assert active.agent_model_name == "openai:gpt-4o"
            assert active.sentinel_model_name is None
            assert active.title_model_name is None

        asyncio.run(_run())


def test_non_slash_user_message_count_ignores_slash_lines() -> None:
    events: list[dict[str, Any]] = [
        {"role": "user", "content": "/model-agent openai:gpt-4o"},
        {"role": "command", "command": "model-agent", "data": {}},
        {"role": "user", "content": "hello"},
    ]
    assert _non_slash_user_message_count(events) == 1


def test_non_slash_user_message_count_plain_users() -> None:
    events: list[dict[str, Any]] = [
        {"role": "user", "content": "a"},
        {"role": "user", "content": "b"},
        {"role": "user", "content": "c"},
    ]
    assert _non_slash_user_message_count(events) == 3


def test_truncate_incomplete_model_history_drops_dangling_tool_tail(tmp_path: Path) -> None:
    with _patch_sentinel():
        engine = _make_engine(tmp_path)
        messages = [
            ModelRequest(parts=[UserPromptPart(content="hello")]),
            ModelResponse(parts=[ToolCallPart(tool_name="cmd", args={}, tool_call_id="call-1")]),
            ModelRequest(parts=[ToolReturnPart(tool_name="cmd", content="ok", tool_call_id="call-1")]),
            ModelResponse(parts=[TextPart(content="done")]),
            ModelResponse(parts=[ToolCallPart(tool_name="cmd", args={}, tool_call_id="call-2")]),
        ]

        truncated = engine._truncate_incomplete_model_history(messages)

        assert len(truncated) == 4
        assert isinstance(truncated[-1], ModelResponse)
        assert truncated[-1].parts[0].part_kind == "text"


def test_truncate_incomplete_model_history_keeps_complete_pairs(tmp_path: Path) -> None:
    with _patch_sentinel():
        engine = _make_engine(tmp_path)
        messages = [
            ModelRequest(parts=[UserPromptPart(content="hello")]),
            ModelResponse(parts=[ToolCallPart(tool_name="cmd", args={}, tool_call_id="call-1")]),
            ModelRequest(parts=[ToolReturnPart(tool_name="cmd", content="ok", tool_call_id="call-1")]),
            ModelResponse(parts=[TextPart(content="done")]),
        ]

        truncated = engine._truncate_incomplete_model_history(messages)
        assert truncated == messages


def test_truncate_incomplete_events_drops_dangling_tool_tail(tmp_path: Path) -> None:
    with _patch_sentinel():
        engine = _make_engine(tmp_path)
        events: list[dict[str, Any]] = [
            {"role": "user", "content": "hello"},
            {"role": "tool_call", "tool": "shell", "args": {"command": "echo ok"}, "detail": "run"},
            {"role": "tool_result", "tool": "shell", "result": "ok", "exit_code": 0},
            {"role": "assistant", "content": "done"},
            {"role": "tool_call", "tool": "shell", "args": {"command": "sleep 10"}, "detail": "run"},
        ]

        truncated = engine._truncate_incomplete_events(events)

        assert len(truncated) == 4
        assert truncated[-1]["role"] == "assistant"
