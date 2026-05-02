"""Shared helpers for session tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

from pydantic_ai.models.test import TestModel

from carapace.bootstrap import ensure_data_dir
from carapace.config import load_config
from carapace.credentials import CredentialRegistry
from carapace.git.store import GitStore
from carapace.models import ToolResult
from carapace.sandbox.manager import SandboxManager
from carapace.security.context import ApprovalSource, ApprovalVerdict
from carapace.security.sentinel import Sentinel
from carapace.session import SessionEngine, SessionManager
from carapace.session.types import ActiveSession, SessionSubscriber
from carapace.skills import SkillRegistry
from carapace.usage import LlmRequestState
from carapace.ws_models import ApprovalRequest, TurnUsage


def _patch_sentinel():
    """Patch Sentinel class so its instances pass isinstance checks."""
    mock_cls = MagicMock()
    mock_cls.return_value = MagicMock(spec=Sentinel)
    return patch("carapace.session.engine.Sentinel", mock_cls)


def _without_timestamp(event: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in event.items() if key != "timestamp"}


def _without_timestamps(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_without_timestamp(event) for event in events]


class _FakeSubscriber(SessionSubscriber):
    """Minimal subscriber that records calls."""

    def __init__(self) -> None:
        self.user_messages: list[tuple[str, bool]] = []
        self.token_chunks: list[str] = []
        self.thinking_chunks: list[str] = []
        self.errors: list[str] = []
        self.error_events: list[tuple[str, bool]] = []
        self.cancelled: int = 0
        self.done_messages: list[tuple[str, TurnUsage]] = []
        self.title_updates: list[tuple[str, TurnUsage | None]] = []
        self.llm_activity_updates: list[LlmRequestState | None] = []

    async def on_user_message(self, content: str, *, from_self: bool) -> None:
        self.user_messages.append((content, from_self))

    async def on_tool_call(
        self,
        tool: str,
        args: dict[str, Any],
        detail: str,
        approval_source: ApprovalSource | None = None,
        approval_verdict: ApprovalVerdict | None = None,
        approval_explanation: str | None = None,
        tool_id: str | None = None,
        parent_tool_id: str | None = None,
    ) -> None:
        pass

    async def on_tool_result(self, result: ToolResult) -> None:
        pass

    async def on_token(self, content: str) -> None:
        self.token_chunks.append(content)

    async def on_thinking_token(self, content: str) -> None:
        self.thinking_chunks.append(content)

    async def on_done(self, content: str, usage: TurnUsage, *, thinking: str | None = None) -> None:
        self.done_messages.append((content, usage))

    async def on_error(self, detail: str, *, turn_terminal: bool = False) -> None:
        self.errors.append(detail)
        self.error_events.append((detail, turn_terminal))

    async def on_cancelled(self) -> None:
        self.cancelled += 1

    async def on_approval_request(self, req: ApprovalRequest) -> None:
        pass

    async def on_domain_access_approval_request(self, request_id: str, domain: str, command: str) -> None:
        pass

    async def on_git_push_approval_request(
        self,
        request_id: str,
        ref: str,
        explanation: str,
        changed_files: list[str],
    ) -> None:
        pass

    async def on_title_update(self, title: str, usage: TurnUsage | None = None) -> None:
        self.title_updates.append((title, usage))

    async def on_llm_activity(self, activity: LlmRequestState | None) -> None:
        self.llm_activity_updates.append(activity)

    async def on_domain_info(
        self,
        domain: str,
        detail: str,
        approval_source: ApprovalSource | None = None,
        approval_verdict: ApprovalVerdict | None = None,
        approval_explanation: str | None = None,
        tool_id: str | None = None,
        parent_tool_id: str | None = None,
    ) -> None:
        pass

    async def on_git_push_info(
        self,
        ref: str,
        decision: str,
        detail: str,
        approval_source: ApprovalSource | None = None,
        approval_verdict: ApprovalVerdict | None = None,
        approval_explanation: str | None = None,
        tool_id: str | None = None,
        parent_tool_id: str | None = None,
    ) -> None:
        pass

    async def on_credential_info(
        self,
        vault_path: str,
        name: str,
        detail: str,
        approval_source: ApprovalSource | None = None,
        approval_verdict: ApprovalVerdict | None = None,
        approval_explanation: str | None = None,
        tool_id: str | None = None,
        parent_tool_id: str | None = None,
    ) -> None:
        pass

    async def on_credential_approval_request(
        self,
        request_id: str,
        vault_paths: list[str],
        names: list[str],
        descriptions: list[str],
        skill_name: str | None,
        explanation: str,
    ) -> None:
        pass


def _sandbox_refresh_snapshot_mock(engine: SessionEngine) -> AsyncMock:
    return cast(AsyncMock, cast(Any, engine._sandbox_mgr.refresh_sandbox_snapshot))


def _sandbox_reset_session_mock(engine: SessionEngine) -> AsyncMock:
    return cast(AsyncMock, cast(Any, engine._sandbox_mgr.reset_session))


def _sentinel_set_model_mock(active: ActiveSession) -> MagicMock:
    assert active.sentinel is not None
    return cast(MagicMock, cast(Any, active.sentinel.set_model))


def _make_engine(tmp_path: Path) -> SessionEngine:
    ensure_data_dir(tmp_path)
    config = load_config(tmp_path)
    session_mgr = SessionManager(tmp_path)
    registry = SkillRegistry(tmp_path / "skills")
    skill_catalog = registry.scan()
    sandbox_mgr = MagicMock(spec=SandboxManager)
    sandbox_mgr.refresh_sandbox_snapshot = AsyncMock()
    sandbox_mgr.reset_session = AsyncMock()
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
