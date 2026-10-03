"""SessionEngine model, title, truncation, and remaining integration tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai import ApprovalRequired
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

import carapace.security as security_mod
import carapace.usage as usage_mod
from carapace.llm import DisabledModelError
from carapace.models.config import AgentConfig, AvailableModelEntry
from carapace.models.session import SessionBudget
from carapace.security.context import SentinelVerdict, SessionSecurity, ToolCallEntry
from carapace.security.sentinel import Sentinel
from carapace.session.turns import _non_slash_user_message_count
from carapace.usage import LlmRequestRecord, LlmRequestState, ModelUsage, SessionBudgetExceededError
from tests.session_helpers import (
    _FakeSubscriber,
    _make_engine,
    _patch_sentinel,
    _sandbox_reset_session_mock,
    _sentinel_set_model_mock,
)


def test_submit_message_budget_exceeded_persists_history(tmp_path: Path, db_factory):
    async def _run() -> None:
        engine = _make_engine(tmp_path, session_factory=db_factory)
        state = engine.session_mgr.create_session(user="thies", budget=SessionBudget(input_tokens=1_000))
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
        assert isinstance(history[-1], ModelResponse)
        assert any(
            isinstance(part, TextPart) and part.content == "Session budget reached: input 1.0k tokens / 1.0k tokens"
            for part in history[-1].parts
        )

        events = engine.session_mgr.load_events(sid)
        assert "timestamp" in events[-1]
        assert events[-1]["role"] == "assistant"
        assert events[-1]["content"] == "Session budget reached: input 1.0k tokens / 1.0k tokens"
        assert any("Session budget reached" in err for err in sub.errors)
        assert any(
            detail.startswith("Session budget reached") and turn_terminal for detail, turn_terminal in sub.error_events
        )

    with _patch_sentinel():
        asyncio.run(_run())


def test_handle_slash_command_models_returns_available_only(tmp_path: Path, db_factory):
    with _patch_sentinel():
        engine = _make_engine(tmp_path, session_factory=db_factory)
        sid = engine.session_mgr.create_session(user="thies").session_id
        engine.get_or_activate(sid)

        async def _run() -> None:
            result = await engine.handle_slash_command(sid, "/models")
            assert result is not None
            assert result["command"] == "models"
            assert "available" in result["data"]
            assert result["data"]["available"]
            assert "models" not in result["data"]

        asyncio.run(_run())


def test_submit_message_unexpected_output_marks_terminal_error(tmp_path: Path, db_factory):
    async def _run() -> None:
        engine = _make_engine(tmp_path, session_factory=db_factory)
        sid = engine.session_mgr.create_session(user="thies").session_id
        sub = _FakeSubscriber()
        engine.subscribe(sid, sub)

        unexpected = "Unexpected agent output type: {'message': 'bad'}"

        async def _unexpected_run_agent_turn(*_args: Any, **_kwargs: Any):
            return (
                [
                    ModelRequest(parts=[UserPromptPart(content="hello")]),
                    ModelResponse(parts=[TextPart(content="placeholder")]),
                ],
                unexpected,
                "",
                None,
            )

        with patch("carapace.session.engine.run_agent_turn", new=_unexpected_run_agent_turn):
            await engine.submit_message(sid, "hello")
            active = engine.get_active(sid)
            assert active is not None and active.agent_task is not None
            await active.agent_task

        events = engine.session_mgr.load_events(sid)
        assert events[-1]["role"] == "assistant"
        assert events[-1]["content"] == unexpected
        assert sub.done_messages == []
        assert sub.error_events == [(unexpected, True)]

    with _patch_sentinel():
        asyncio.run(_run())


def test_evaluate_with_usage_limit_exceeded_escalates_to_user(tmp_path: Path):
    async def _run() -> None:
        session = SessionSecurity("test-session")
        sentinel = MagicMock(spec=Sentinel)
        sentinel.evaluate_tool_call = AsyncMock(
            side_effect=UsageLimitExceeded("The next request would exceed the request_limit of 5")
        )

        with pytest.raises(ApprovalRequired) as exc_info:
            await security_mod.evaluate_with(
                session,
                sentinel,
                "use_skill",
                {"skill_name": "paperless"},
            )

        metadata = exc_info.value.metadata
        assert metadata is not None
        assert metadata["tool"] == "use_skill"
        assert metadata["args"] == {"skill_name": "paperless"}
        assert metadata["risk_level"] == "high"
        assert isinstance(metadata["sentinel_verdict"], SentinelVerdict)
        assert metadata["sentinel_verdict"].decision == "escalate"
        assert "request limit" in metadata["explanation"].lower()

        entry = session.action_log[-1]
        assert isinstance(entry, ToolCallEntry)
        assert entry.decision == "escalated"
        assert entry.tool == "use_skill"
        assert entry.explanation is not None
        assert "request limit" in entry.explanation.lower()

    asyncio.run(_run())


def test_generate_title_skips_when_budget_exhausted(tmp_path: Path, db_factory):
    async def _run() -> None:
        engine = _make_engine(tmp_path, session_factory=db_factory)
        state = engine.session_mgr.create_session(user="thies", budget=SessionBudget(input_tokens=100))
        active = engine.get_or_activate(state.session_id)
        active.usage_tracker.models["test-model"] = ModelUsage(input_tokens=120)

        with patch("carapace.session.engine.generate_title", new=AsyncMock(return_value="ignored")) as mocked:
            title = await engine._generate_title(active, [{"role": "user", "content": "hello"}])

        assert title == ""
        mocked.assert_not_awaited()

    with _patch_sentinel():
        asyncio.run(_run())


def test_generate_title_persists_usage_and_broadcasts_usage(tmp_path: Path, db_factory):
    async def _run() -> None:
        engine = _make_engine(tmp_path, session_factory=db_factory)
        state = engine.session_mgr.create_session(user="thies", budget=SessionBudget(cost_usd=Decimal("5.00")))
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


def test_generate_title_records_titler_request_log(tmp_path: Path, db_factory):
    async def _run() -> None:
        engine = _make_engine(tmp_path, session_factory=db_factory)
        state = engine.session_mgr.create_session(user="thies")
        sid = state.session_id
        active = engine.get_or_activate(sid)
        started_at = datetime.now(tz=UTC)

        async def _fake_generate_title(*_args: Any, **_kwargs: Any) -> str:
            observer = usage_mod._llm_request_sink.get()
            assert observer is not None

            request_state = LlmRequestState(
                request_id="req-title",
                source="titler",
                model_name="anthropic:claude-haiku-4-5",
                started_at=started_at,
            )
            record = LlmRequestRecord(
                ts=started_at + timedelta(seconds=1),
                request_id="req-title",
                source="titler",
                model_name="anthropic:claude-haiku-4-5",
                started_at=started_at,
                completed_at=started_at + timedelta(seconds=1),
            )

            await observer.on_request_started(request_state)
            await observer.on_request_completed(record)
            return "📌 hello"

        with patch("carapace.session.engine.generate_title", new=AsyncMock(side_effect=_fake_generate_title)):
            title = await engine._generate_title(active, [{"role": "user", "content": "hello"}])

        assert title == "📌 hello"
        assert active.llm_request_log.records[-1].request_id == "req-title"
        assert active.llm_request_log.records[-1].source == "titler"

        stored_log = engine.session_mgr.load_llm_request_log(sid)
        assert stored_log.records[-1].request_id == "req-title"
        assert stored_log.records[-1].source == "titler"

    with _patch_sentinel():
        asyncio.run(_run())


def _emit_titler_request() -> str:
    """Drive the active llm-request sink as the titler would, returning a fixed title."""

    async def _fake(*_args: Any, **_kwargs: Any) -> str:
        observer = usage_mod._llm_request_sink.get()
        assert observer is not None
        started_at = datetime.now(tz=UTC)
        await observer.on_request_started(
            LlmRequestState(
                request_id="req-title",
                source="titler",
                model_name="anthropic:claude-haiku-4-5",
                started_at=started_at,
            )
        )
        await observer.on_request_completed(
            LlmRequestRecord(
                ts=started_at + timedelta(seconds=1),
                request_id="req-title",
                source="titler",
                model_name="anthropic:claude-haiku-4-5",
                started_at=started_at,
                completed_at=started_at + timedelta(seconds=1),
            )
        )
        return "📌 hello"

    return _fake  # type: ignore[return-value]


def test_generate_title_untracked_is_invisible(tmp_path: Path, db_factory):
    """Background auto-title (track_activity=False) never broadcasts llm activity or sets state."""

    async def _run() -> None:
        engine = _make_engine(tmp_path, session_factory=db_factory)
        sid = engine.session_mgr.create_session(user="thies").session_id
        active = engine.get_or_activate(sid)
        sub = _FakeSubscriber()
        engine.subscribe(sid, sub)

        with patch("carapace.session.engine.generate_title", new=AsyncMock(side_effect=_emit_titler_request())):
            title = await engine._generate_title(active, [{"role": "user", "content": "hello"}], track_activity=False)

        assert title == "📌 hello"
        # invisible: no busy signal, no lingering activity state
        assert sub.llm_activity_updates == []
        assert active.llm_request_state is None
        assert engine.session_mgr.load_llm_request_state(sid) is None
        # final title still reaches clients
        assert sub.title_updates and sub.title_updates[0][0] == "📌 hello"
        # audit record is still kept
        assert active.llm_request_log.records[-1].source == "titler"

    with _patch_sentinel():
        asyncio.run(_run())


def test_generate_title_tracked_emits_activity(tmp_path: Path, db_factory):
    """Visible path (slash commands, track_activity default) still broadcasts llm activity."""

    async def _run() -> None:
        engine = _make_engine(tmp_path, session_factory=db_factory)
        sid = engine.session_mgr.create_session(user="thies").session_id
        active = engine.get_or_activate(sid)
        sub = _FakeSubscriber()
        engine.subscribe(sid, sub)

        with patch("carapace.session.engine.generate_title", new=AsyncMock(side_effect=_emit_titler_request())):
            title = await engine._generate_title(active, [{"role": "user", "content": "hello"}])

        assert title == "📌 hello"
        # started -> state set, completed -> cleared to None
        assert sub.llm_activity_updates
        assert sub.llm_activity_updates[0] is not None
        assert sub.llm_activity_updates[-1] is None
        assert active.llm_request_state is None

    with _patch_sentinel():
        asyncio.run(_run())


def test_handle_slash_command_inactive_session(tmp_path: Path, db_factory):
    """handle_slash_command returns None for a session that isn't active."""
    engine = _make_engine(tmp_path, session_factory=db_factory)
    state = engine.session_mgr.create_session(user="thies")

    async def _run() -> None:
        assert await engine.handle_slash_command(state.session_id, "/session") is None

    asyncio.run(_run())


def test_handle_slash_command_reload(tmp_path: Path, db_factory):
    """handle_slash_command /reload calls reset_session and returns success."""
    with _patch_sentinel():
        engine = _make_engine(tmp_path, session_factory=db_factory)
        state = engine.session_mgr.create_session(user="thies")
        sid = state.session_id
        engine.get_or_activate(sid)

        async def _run() -> None:
            result = await engine.handle_slash_command(sid, "/reload")
            assert result is not None
            assert result["command"] == "reload"
            assert "reset" in result["data"]["message"].lower() or "fresh" in result["data"]["message"].lower()
            _sandbox_reset_session_mock(engine).assert_awaited_once_with(sid)

        asyncio.run(_run())


def test_handle_slash_command_model_sets_all_three(tmp_path: Path, db_factory):
    """``/model NAME`` applies the same id to agent, sentinel, and title."""
    with _patch_sentinel():
        engine = _make_engine(tmp_path, session_factory=db_factory)
        state = engine.session_mgr.create_session(user="thies")
        sid = state.session_id
        active = engine.get_or_activate(sid)

        async def _run() -> None:
            result = await engine.handle_slash_command(sid, "/model openai:gpt-4o")
            assert result is not None
            assert result["command"] == "model"
            assert "models" in result["data"]
            for key in ("agent", "sentinel", "title", "compaction"):
                assert result["data"]["models"][key]["current"] == "openai:gpt-4o"
            assert active.agent_model_name == "openai:gpt-4o"
            assert active.sentinel_model_name == "openai:gpt-4o"
            assert active.title_model_name == "openai:gpt-4o"
            assert active.compaction_model_name == "openai:gpt-4o"

        asyncio.run(_run())


def test_handle_slash_command_model_target_sets_only_requested_role(tmp_path: Path, db_factory):
    """``/model sentinel NAME`` mirrors target-first slash commands like ``/budget``."""
    with _patch_sentinel():
        engine = _make_engine(tmp_path, session_factory=db_factory)
        state = engine.session_mgr.create_session(user="thies")
        sid = state.session_id
        active = engine.get_or_activate(sid)

        async def _run() -> None:
            result = await engine.handle_slash_command(sid, "/model sentinel openai:gpt-4o")
            assert result is not None
            assert result["command"] == "model-sentinel"
            assert result["data"]["current"] == "openai:gpt-4o"
            assert active.agent_model_name is None
            assert active.sentinel_model_name == "openai:gpt-4o"
            assert active.title_model_name is None

        asyncio.run(_run())


def test_handle_slash_command_model_compaction_target(tmp_path: Path, db_factory):
    """``/model compaction NAME`` overrides only the compaction model and feeds the engine."""
    with _patch_sentinel():
        engine = _make_engine(tmp_path, session_factory=db_factory)
        state = engine.session_mgr.create_session(user="thies")
        sid = state.session_id
        active = engine.get_or_activate(sid)

        async def _run() -> None:
            result = await engine.handle_slash_command(sid, "/model compaction openai:gpt-4o")
            assert result is not None
            assert result["command"] == "model-compaction"
            assert result["data"]["current"] == "openai:gpt-4o"
            assert active.agent_model_name is None
            assert active.compaction_model_name == "openai:gpt-4o"
            # The compaction engine resolves the per-session override.
            assert engine._compaction_model(active) == "openai:gpt-4o"

        asyncio.run(_run())


def test_handle_slash_command_model_all_alias_sets_all_three(tmp_path: Path, db_factory):
    """``/model all NAME`` explicitly targets the all-model path."""
    with _patch_sentinel():
        engine = _make_engine(tmp_path, session_factory=db_factory)
        state = engine.session_mgr.create_session(user="thies")
        sid = state.session_id
        active = engine.get_or_activate(sid)

        async def _run() -> None:
            result = await engine.handle_slash_command(sid, "/model all openai:gpt-4o")
            assert result is not None
            assert result["command"] == "model"
            for key in ("agent", "sentinel", "title", "compaction"):
                assert result["data"]["models"][key]["current"] == "openai:gpt-4o"
            assert active.agent_model_name == "openai:gpt-4o"
            assert active.sentinel_model_name == "openai:gpt-4o"
            assert active.title_model_name == "openai:gpt-4o"
            assert active.compaction_model_name == "openai:gpt-4o"

        asyncio.run(_run())


def test_handle_slash_command_model_role_fallback_is_not_supported(tmp_path: Path, db_factory):
    """Legacy ``/model-role`` aliases are no longer accepted."""
    with _patch_sentinel():
        engine = _make_engine(tmp_path, session_factory=db_factory)
        state = engine.session_mgr.create_session(user="thies")
        sid = state.session_id
        engine.get_or_activate(sid)

        async def _run() -> None:
            assert await engine.handle_slash_command(sid, "/model-agent openai:gpt-4o") is None
            assert await engine.handle_slash_command(sid, "/model-sentinel openai:gpt-4o") is None
            assert await engine.handle_slash_command(sid, "/model-title openai:gpt-4o") is None

        asyncio.run(_run())


def test_model_overrides_persist_across_restart(tmp_path: Path, db_factory) -> None:
    with _patch_sentinel():
        engine = _make_engine(tmp_path, session_factory=db_factory)
        state = engine.session_mgr.create_session(user="thies")
        sid = state.session_id
        engine.get_or_activate(sid)

        async def _run() -> None:
            result = await engine.handle_slash_command(sid, "/model openai:gpt-4o")
            assert result is not None
            assert result["command"] == "model"

        asyncio.run(_run())

    persisted = engine.session_mgr.load_state(sid)
    assert persisted is not None
    assert persisted.agent_model_name == "openai:gpt-4o"
    assert persisted.sentinel_model_name == "openai:gpt-4o"
    assert persisted.title_model_name == "openai:gpt-4o"

    with _patch_sentinel():
        restarted = _make_engine(tmp_path, session_factory=db_factory)
        active = restarted.get_or_activate(sid)
        deps = restarted._build_deps(active)

    assert active.agent_model_name == "openai:gpt-4o"
    assert active.sentinel_model_name == "openai:gpt-4o"
    assert active.title_model_name == "openai:gpt-4o"
    assert isinstance(deps.agent_model, TestModel)
    assert deps.agent_model_id == "openai:gpt-4o"
    assert active.agent_model is deps.agent_model
    _sentinel_set_model_mock(active).assert_called_once_with("openai:gpt-4o")


def test_default_agent_model_is_built_once_per_session(tmp_path: Path, db_factory) -> None:
    # The platform default is resolved lazily (startup may have no credentials) and must be cached:
    # every build opens its own HTTP client, and _build_deps runs once per turn.
    with _patch_sentinel():
        engine = _make_engine(tmp_path, session_factory=db_factory)
        state = engine.session_mgr.create_session(user="thies")
        active = engine.get_or_activate(state.session_id)
        first = engine._build_deps(active)
        second = engine._build_deps(active)

    assert first.agent_model is second.agent_model


def test_agent_model_is_built_for_the_session_owner(tmp_path: Path, db_factory) -> None:
    # Models can carry per-user provider credentials (ChatGPT subscriptions), so the default
    # agent model must never be shared between sessions of different users.
    built_for: dict[int, str] = {}

    def factory(_name: str, *, user: str) -> TestModel:
        model = TestModel()
        built_for[id(model)] = user
        return model

    with _patch_sentinel():
        engine = _make_engine(tmp_path, session_factory=db_factory)
        engine._model_factory = factory
        thies = engine.get_or_activate(engine.session_mgr.create_session(user="thies").session_id)
        ada = engine.get_or_activate(engine.session_mgr.create_session(user="ada").session_id)
        thies_model = engine._build_deps(thies).agent_model
        ada_model = engine._build_deps(ada).agent_model

    assert built_for[id(thies_model)] == "thies"
    assert built_for[id(ada_model)] == "ada"


def test_reset_user_models_only_drops_that_users_models(tmp_path: Path, db_factory) -> None:
    with _patch_sentinel():
        engine = _make_engine(tmp_path, session_factory=db_factory)
        thies = engine.get_or_activate(engine.session_mgr.create_session(user="thies").session_id)
        ada = engine.get_or_activate(engine.session_mgr.create_session(user="ada").session_id)
        engine._build_deps(thies)
        ada_model = engine._build_deps(ada).agent_model

        engine.reset_user_models("thies")

    assert thies.agent_model is None
    _sentinel_set_model_mock(thies).assert_called_with(engine.config.agent.sentinel_model)
    assert ada.agent_model is ada_model


def test_apply_platform_model_config_invalidates_cached_override_agent_model(tmp_path: Path, db_factory) -> None:
    with _patch_sentinel():
        engine = _make_engine(tmp_path, session_factory=db_factory)
        state = engine.session_mgr.create_session(user="thies")
        active = engine.get_or_activate(state.session_id)
        cached_model = TestModel()
        active.agent_model_name = "openai:gpt-4o"
        active.agent_model = cached_model

        engine.apply_platform_model_config(
            engine.config,
            model_factory=lambda _name, *, user: TestModel(),
        )

    assert active.agent_model_name == "openai:gpt-4o"
    assert active.agent_model is None


def test_apply_platform_model_config_refreshes_active_sentinel_factory(tmp_path: Path, db_factory) -> None:
    engine = _make_engine(tmp_path, session_factory=db_factory)

    def old_factory(name: str, *, user: str) -> TestModel:
        if name == "local:new-model":
            raise ValueError("old catalog")
        return TestModel()

    engine._model_factory = old_factory
    state = engine.session_mgr.create_session(user="thies")
    active = engine.get_or_activate(state.session_id)
    assert active.sentinel is not None

    def new_factory(_name: str, *, user: str) -> TestModel:
        return TestModel()

    config = engine.config.model_copy(deep=True)
    config.agent = AgentConfig(
        model=engine.config.agent.model,
        sentinel_model=engine.config.agent.sentinel_model,
        title_model=engine.config.agent.title_model,
        available_models=[
            *engine.config.agent.available_models,
            {"provider": "openai", "name": "new-model", "id": "local:new-model"},
        ],
    )
    engine.apply_platform_model_config(config, model_factory=new_factory)
    updated = engine.update_session_model_overrides(
        state.session_id,
        agent_model_name="local:new-model",
        sentinel_model_name="local:new-model",
    )

    assert updated.agent_model_name == "local:new-model"
    assert updated.sentinel_model_name == "local:new-model"
    assert active.agent_model_name == "local:new-model"
    assert active.sentinel_model_name == "local:new-model"


def test_apply_platform_model_config_clears_stale_active_sentinel_override(tmp_path: Path, db_factory) -> None:
    with _patch_sentinel() as sentinel_cls, patch("carapace.session.engine.logger.warning") as warning_mock:
        engine = _make_engine(tmp_path, session_factory=db_factory)
        state = engine.session_mgr.create_session(user="thies")
        active = engine.get_or_activate(state.session_id)
        assert active.sentinel is not None

        active.sentinel_model_name = "openai:missing-sentinel"
        active.state.sentinel_model_name = "openai:missing-sentinel"
        engine.session_mgr.save_state(active.state)

        sentinel = sentinel_cls.return_value

        def _set_model_runtime(*, model: str | None = None, **_kwargs: Any) -> None:
            if model == "openai:missing-sentinel":
                raise ValueError("missing sentinel model")

        sentinel.set_model_runtime.side_effect = _set_model_runtime

        engine.apply_platform_model_config(
            engine.config,
            model_factory=lambda _name, *, user: TestModel(),
        )

    assert active.sentinel_model_name is None
    assert active.state.sentinel_model_name is None

    persisted = engine.session_mgr.load_state(state.session_id)
    assert persisted is not None
    assert persisted.sentinel_model_name is None

    assert sentinel.set_model_runtime.call_count == 2
    assert sentinel.set_model_runtime.call_args_list[0].kwargs["model"] == "openai:missing-sentinel"
    assert sentinel.set_model_runtime.call_args_list[1].kwargs["model"] == engine.config.agent.sentinel_model
    warning_mock.assert_called_once()


def test_invalid_model_overrides_fall_back_on_restart(tmp_path: Path, db_factory) -> None:
    with _patch_sentinel():
        engine = _make_engine(tmp_path, session_factory=db_factory)
        state = engine.session_mgr.create_session(user="thies")

    state.agent_model_name = "openai:missing-agent"
    state.sentinel_model_name = "openai:missing-sentinel"
    state.title_model_name = "openai:missing-title"
    engine.session_mgr.save_state(state)

    with _patch_sentinel() as sentinel_cls, patch("carapace.session.engine.logger.warning") as warning_mock:
        sentinel_instance = sentinel_cls.return_value

        def _set_model(name: str) -> None:
            if name == "openai:missing-sentinel":
                raise ValueError("missing sentinel model")

        sentinel_instance.set_model.side_effect = _set_model

        restarted = _make_engine(tmp_path, session_factory=db_factory)
        restarted._resolve_model = MagicMock(
            side_effect=lambda name, _user: (
                TestModel()
                if name == restarted._config.agent.model
                else (_ for _ in ()).throw(ValueError("missing agent model"))
            )
        )

        active = restarted.get_or_activate(state.session_id)
        deps = restarted._build_deps(active)

    assert active.agent_model_name is None
    assert active.sentinel_model_name is None
    assert active.title_model_name is None
    assert isinstance(deps.agent_model, TestModel)
    assert deps.agent_model_id == restarted._config.agent.model

    persisted = restarted.session_mgr.load_state(state.session_id)
    assert persisted is not None
    assert persisted.agent_model_name is None
    assert persisted.sentinel_model_name is None
    assert persisted.title_model_name is None

    sentinel_instance.set_model.assert_any_call("openai:missing-sentinel")
    sentinel_instance.set_model.assert_any_call(restarted._config.agent.sentinel_model)
    assert warning_mock.call_count == 3


def test_non_slash_user_message_count_ignores_slash_lines() -> None:
    events: list[dict[str, Any]] = [
        {"role": "user", "content": "/model openai:gpt-4o"},
        {"role": "command", "command": "model", "data": {}},
        {"role": "user", "content": "hello"},
    ]
    assert _non_slash_user_message_count(events) == 1


def test_non_slash_user_message_count_includes_unknown_slash_lines() -> None:
    events: list[dict[str, Any]] = [
        {"role": "user", "content": "/tmp"},
        {"role": "assistant", "content": "ok"},
        {"role": "user", "content": "hello"},
    ]
    assert _non_slash_user_message_count(events) == 2


def test_non_slash_user_message_count_plain_users() -> None:
    events: list[dict[str, Any]] = [
        {"role": "user", "content": "a"},
        {"role": "user", "content": "b"},
        {"role": "user", "content": "c"},
    ]
    assert _non_slash_user_message_count(events) == 3


def test_truncate_incomplete_model_history_drops_dangling_tool_tail(tmp_path: Path, db_factory) -> None:
    with _patch_sentinel():
        engine = _make_engine(tmp_path, session_factory=db_factory)
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


def test_truncate_incomplete_model_history_keeps_complete_pairs(tmp_path: Path, db_factory) -> None:
    with _patch_sentinel():
        engine = _make_engine(tmp_path, session_factory=db_factory)
        messages = [
            ModelRequest(parts=[UserPromptPart(content="hello")]),
            ModelResponse(parts=[ToolCallPart(tool_name="cmd", args={}, tool_call_id="call-1")]),
            ModelRequest(parts=[ToolReturnPart(tool_name="cmd", content="ok", tool_call_id="call-1")]),
            ModelResponse(parts=[TextPart(content="done")]),
        ]

        truncated = engine._truncate_incomplete_model_history(messages)
        assert truncated == messages


def test_truncate_incomplete_model_history_retry_resolves_tool_call(tmp_path: Path, db_factory) -> None:
    # A tool call answered by a RetryPromptPart (validation retry) is resolved, not pending —
    # otherwise every later turn is stranded and the history collapses to the first turn.
    with _patch_sentinel():
        engine = _make_engine(tmp_path, session_factory=db_factory)
        messages = [
            ModelRequest(parts=[UserPromptPart(content="hello")]),
            ModelResponse(parts=[ToolCallPart(tool_name="cmd", args={}, tool_call_id="call-1")]),
            ModelRequest(parts=[RetryPromptPart(content="bad args", tool_name="cmd", tool_call_id="call-1")]),
            ModelResponse(parts=[TextPart(content="done")]),
            ModelRequest(parts=[UserPromptPart(content="again")]),
            ModelResponse(parts=[TextPart(content="ok")]),
        ]

        truncated = engine._truncate_incomplete_model_history(messages)
        assert truncated == messages


def test_truncate_incomplete_events_drops_dangling_tool_tail(tmp_path: Path, db_factory) -> None:
    with _patch_sentinel():
        engine = _make_engine(tmp_path, session_factory=db_factory)
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


def test_truncate_incomplete_events_keeps_completed_turn_after_resultless_call(tmp_path: Path, db_factory) -> None:
    """A mid-conversation tool call that never emits a paired result (credential_access,
    imported sessions, ...) must not truncate away a later fully completed turn — else fork/reset
    on that turn fails with "Unknown fork target"."""
    with _patch_sentinel():
        engine = _make_engine(tmp_path, session_factory=db_factory)
        events: list[dict[str, Any]] = [
            {"role": "user", "content": "first"},
            {"role": "tool_call", "tool": "exec", "args": {"command": "ls"}, "detail": "run", "tool_id": "c1"},
            {"role": "tool_result", "tool": "exec", "result": "ok", "exit_code": 0, "tool_id": "c1"},
            {"role": "assistant", "content": "done one"},
            {"role": "user", "content": "second"},
            # credential_access is issued but emits no paired tool_result event:
            {"role": "tool_call", "tool": "credential_access", "args": {}, "detail": "grant", "tool_id": "c2"},
            {"role": "assistant", "content": "done two"},
        ]

        truncated = engine._truncate_incomplete_events(events)

        assert len(truncated) == 7
        assert engine._completed_event_turns(truncated)[-1].end_event_index == 6


def test_completed_event_turns_ignores_partial_assistant_events(tmp_path: Path, db_factory) -> None:
    """Intermediate narration (partial assistant events) sits inside a turn — the turn must end at
    its final assistant answer, so reset/fork/compaction stay anchored to real turn boundaries."""
    with _patch_sentinel():
        engine = _make_engine(tmp_path, session_factory=db_factory)
        events: list[dict[str, Any]] = [
            {"role": "user", "content": "do it"},
            {"role": "assistant", "content": "let me check the file", "partial": True},
            {"role": "tool_call", "tool": "exec", "args": {"command": "ls"}, "detail": "run", "tool_id": "c1"},
            {"role": "tool_result", "tool": "exec", "result": "ok", "exit_code": 0, "tool_id": "c1"},
            {"role": "assistant", "content": "all done"},
        ]

        turns = engine._completed_event_turns(events)

        assert len(turns) == 1
        assert turns[0].start_event_index == 0
        assert turns[0].end_event_index == 4  # final assistant, not the partial at index 1


def test_save_user_message_on_failure_appends_cancelled_parallel_tool_returns(tmp_path: Path, db_factory) -> None:
    with _patch_sentinel():
        engine = _make_engine(tmp_path, session_factory=db_factory)

    sid = engine.session_mgr.create_session(user="thies").session_id
    latest_messages = [
        ModelRequest(parts=[UserPromptPart(content="hello")]),
        ModelResponse(
            parts=[
                ToolCallPart(tool_name="shell", args={"command": "sleep 10"}, tool_call_id="call-1"),
                ToolCallPart(tool_name="shell", args={"command": "sleep 20"}, tool_call_id="call-2"),
            ]
        ),
    ]

    engine._save_user_message_on_failure(
        sid,
        "hello",
        latest_messages=latest_messages,
        terminal_message="The previous turn was interrupted before completion.",
    )

    history = engine.session_mgr.load_history(sid)

    assert len(history) == 4
    assert isinstance(history[1], ModelResponse)
    assert isinstance(history[2], ModelRequest)
    assert isinstance(history[3], ModelResponse)

    synthetic_request = history[-2]
    assert isinstance(synthetic_request, ModelRequest)
    assert len(synthetic_request.parts) == 2
    assert all(isinstance(part, ToolReturnPart) for part in synthetic_request.parts)
    assert [part.tool_call_id for part in synthetic_request.parts] == ["call-1", "call-2"]
    assert [part.outcome for part in synthetic_request.parts] == ["failed", "failed"]
    assert all(
        part.content == "Tool call was canceled because the turn ended before it completed."
        for part in synthetic_request.parts
    )

    terminal = history[-1]
    assert any(
        isinstance(part, TextPart) and part.content == "The previous turn was interrupted before completion."
        for part in terminal.parts
    )


def test_save_user_message_on_failure_appends_cancelled_parallel_tool_results(tmp_path: Path, db_factory) -> None:
    with _patch_sentinel():
        engine = _make_engine(tmp_path, session_factory=db_factory)

    sid = engine.session_mgr.create_session(user="thies").session_id
    engine.session_mgr.save_events(
        sid,
        [
            {"role": "user", "content": "hello"},
            {
                "role": "tool_call",
                "tool": "shell",
                "args": {"command": "sleep 10"},
                "detail": "run",
                "tool_id": "tool-1",
            },
            {
                "role": "tool_call",
                "tool": "shell",
                "args": {"command": "sleep 20"},
                "detail": "run",
                "tool_id": "tool-2",
            },
        ],
    )

    engine._save_user_message_on_failure(
        sid,
        "hello",
        latest_messages=[ModelRequest(parts=[UserPromptPart(content="hello")])],
        terminal_message="The previous turn was interrupted before completion.",
    )

    events = engine.session_mgr.load_events(sid)

    assert [event["role"] for event in events] == [
        "user",
        "tool_call",
        "tool_call",
        "tool_result",
        "tool_result",
        "assistant",
    ]
    assert [event.get("tool_id") for event in events[3:5]] == ["tool-1", "tool-2"]
    assert all(event.get("exit_code") == 130 for event in events[3:5])
    assert all(
        event.get("result") == "Tool call was canceled because the turn ended before it completed."
        for event in events[3:5]
    )
    assert events[-1]["content"] == "The previous turn was interrupted before completion."


def test_disabled_model_override_errors_instead_of_falling_back(tmp_path: Path, db_factory) -> None:
    with _patch_sentinel():
        engine = _make_engine(tmp_path, session_factory=db_factory)
        state = engine.session_mgr.create_session(user="thies")

    state.agent_model_name = "openai:gpt-4o"
    engine.session_mgr.save_state(state)

    with _patch_sentinel():
        restarted = _make_engine(tmp_path, session_factory=db_factory)
        restarted.config.agent.available_models.append(
            AvailableModelEntry.model_validate({"provider": "openai", "name": "gpt-4o", "enabled": False})
        )
        restarted._resolve_model = MagicMock(
            side_effect=lambda name, _user: (_ for _ in ()).throw(DisabledModelError(f"Model {name!r} is disabled"))
        )
        active = restarted.get_or_activate(state.session_id)

        assert active.agent_model_name == "openai:gpt-4o"
        with pytest.raises(DisabledModelError, match="agent model 'openai:gpt-4o' is disabled"):
            restarted._build_deps(active)

    persisted = restarted.session_mgr.load_state(state.session_id)
    assert persisted is not None
    assert persisted.agent_model_name == "openai:gpt-4o"
