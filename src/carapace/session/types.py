"""Shared session datatypes and channel-facing protocols.

This module holds the lightweight state containers and subscriber protocol
used across the session package. It intentionally stays free of execution
logic so engine, turns, and channel integrations can share the same types
without creating circular runtime dependencies.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from pydantic_ai.messages import ModelMessage
from pydantic_ai.models import Model

from carapace.models import SessionState, ToolResult
from carapace.security.context import ApprovalSource, ApprovalVerdict, SessionSecurity
from carapace.security.sentinel import Sentinel
from carapace.usage import LlmRequestLog, LlmRequestState, UsageTracker
from carapace.ws_models import ApprovalRequest, ApprovalResponse, EscalationResponse, TurnUsage


@runtime_checkable
class SessionSubscriber(Protocol):
    """Channel callback surface for session events."""

    async def on_user_message(self, content: str, *, from_self: bool) -> None: ...
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
    ) -> None: ...
    async def on_tool_result(self, result: ToolResult) -> None: ...
    async def on_token(self, content: str) -> None: ...
    async def on_thinking_token(self, content: str) -> None: ...
    async def on_llm_activity(self, activity: LlmRequestState | None) -> None: ...
    async def on_done(self, content: str, usage: TurnUsage, *, thinking: str | None = None) -> None: ...
    async def on_error(self, detail: str) -> None: ...
    async def on_cancelled(self) -> None: ...
    async def on_approval_request(self, req: ApprovalRequest) -> None: ...
    async def on_domain_access_approval_request(self, request_id: str, domain: str, command: str) -> None: ...
    async def on_git_push_approval_request(
        self, request_id: str, ref: str, explanation: str, changed_files: list[str]
    ) -> None: ...
    async def on_title_update(self, title: str, usage: TurnUsage | None = None) -> None: ...
    async def on_domain_info(
        self,
        domain: str,
        detail: str,
        approval_source: ApprovalSource | None = None,
        approval_verdict: ApprovalVerdict | None = None,
        approval_explanation: str | None = None,
        tool_id: str | None = None,
        parent_tool_id: str | None = None,
    ) -> None: ...
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
    ) -> None: ...
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
    ) -> None: ...
    async def on_credential_approval_request(
        self,
        request_id: str,
        vault_paths: list[str],
        names: list[str],
        descriptions: list[str],
        skill_name: str | None,
        explanation: str,
    ) -> None: ...


@dataclass
class ActiveSession:
    """In-memory state for a currently active session."""

    state: SessionState
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    security: SessionSecurity | None = None
    sentinel: Sentinel | None = None
    agent_task: asyncio.Task[None] | None = None
    subscribers: list[SessionSubscriber] = field(default_factory=list)
    tool_approval_queue: asyncio.Queue[ApprovalResponse | None] = field(default_factory=asyncio.Queue)
    escalation_queue: asyncio.Queue[EscalationResponse | None] = field(default_factory=asyncio.Queue)
    usage_tracker: UsageTracker = field(default_factory=UsageTracker)
    llm_request_log: LlmRequestLog = field(default_factory=LlmRequestLog)
    llm_request_state: LlmRequestState | None = None
    llm_request_thinking: dict[str, str] = field(default_factory=dict)
    verbose: bool = True
    agent_model: Model | None = None
    agent_model_name: str | None = None
    sentinel_model_name: str | None = None
    title_model_name: str | None = None
    pending_approval_requests: list[dict[str, Any]] = field(default_factory=list)
    pending_escalations: list[dict[str, Any]] = field(default_factory=list)
    _pending_sends: set[asyncio.Task[Any]] = field(default_factory=set)


@dataclass
class TurnExecutionResult:
    """Successful turn output returned by the turn runner."""

    messages: list[ModelMessage]
    output: str
    thinking: str
