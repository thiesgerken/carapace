from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from loguru import logger
from pydantic import BaseModel, Field


class SecurityDeniedError(Exception):
    """Raised when the sentinel denies a tool call."""


@dataclass(frozen=True, slots=True)
class UserEscalationDecision:
    allowed: bool
    message: str | None = None


def normalize_optional_message(message: str | None) -> str | None:
    if message is None:
        return None
    stripped = message.strip()
    return stripped or None


def format_denial_message(source: Literal["sentinel", "user"], message: str | None = None) -> str:
    normalized = normalize_optional_message(message)
    actor = "Sentinel" if source == "sentinel" else "User"
    base = f"{actor} denied this operation."
    if normalized is None:
        return base
    return f"{base} {normalized}"


# --- Action Log Entry Types ---


class UserMessageEntry(BaseModel):
    type: Literal["user_message"] = "user_message"
    content: str


class ToolCallEntry(BaseModel):
    type: Literal["tool_call"] = "tool_call"
    tool: str
    args: dict[str, Any] = {}
    decision: Literal["auto_allowed", "allowed", "escalated", "denied"] = "auto_allowed"
    explanation: str = ""


class ToolResultEntry(BaseModel):
    type: Literal["tool_result"] = "tool_result"
    tool: str
    status: Literal["success", "error"] = "success"


class AgentResponseEntry(BaseModel):
    type: Literal["agent_response"] = "agent_response"
    token_count: int = 0


class ApprovalEntry(BaseModel):
    type: Literal["approval"] = "approval"
    tool: str
    args_summary: str = ""
    decision: Literal["approved", "denied"] = "approved"


class SkillActivatedEntry(BaseModel):
    type: Literal["skill_activated"] = "skill_activated"
    skill_name: str
    description: str = ""
    declared_domains: list[str] = []
    declared_tunnels: list[str] = []


class UserVouchedEntry(BaseModel):
    type: Literal["user_vouched"] = "user_vouched"


class GitPushEntry(BaseModel):
    type: Literal["git_push"] = "git_push"
    ref: str
    decision: Literal["allowed", "escalated", "denied"] = "allowed"
    explanation: str = ""


class CredentialAccessEntry(BaseModel):
    type: Literal["credential_access"] = "credential_access"
    vault_paths: list[str]
    decision: Literal["approved", "escalated", "denied"] = "approved"
    explanation: str = ""


class ContextGrantEntry(BaseModel):
    type: Literal["context_grant"] = "context_grant"
    skill_name: str
    domains: list[str] = []
    tunnels: list[str] = []
    vault_paths: list[str] = []


ActionLogEntry = Annotated[
    UserMessageEntry
    | ToolCallEntry
    | ToolResultEntry
    | AgentResponseEntry
    | ApprovalEntry
    | SkillActivatedEntry
    | UserVouchedEntry
    | GitPushEntry
    | CredentialAccessEntry
    | ContextGrantEntry,
    Field(discriminator="type"),
]


# --- Sentinel Verdict ---


class SentinelVerdict(BaseModel):
    decision: Literal["allow", "escalate", "deny"]
    explanation: str = ""
    risk_level: Literal["low", "medium", "high"] = "medium"


class UnattendedSentinelVerdict(BaseModel):
    decision: Literal["allow", "deny"]
    explanation: str = ""
    risk_level: Literal["low", "medium", "high"] = "medium"


ApprovalSource = Literal["safe-list", "sentinel", "user", "skill", "bypass", "unknown"]
ApprovalVerdict = Literal["allow", "deny", "escalate"]


@dataclass(frozen=True, slots=True)
class CachedDomainApproval:
    allowed: bool
    approval_source: ApprovalSource
    approval_verdict: ApprovalVerdict
    explanation: str | None = None
    detail: str = ""
    final_decision: Literal["allowed", "denied"] = "allowed"
    audit_explanation: str | None = None
    sentinel_verdict: SentinelVerdict | None = None


@dataclass(slots=True)
class PendingDomainRequest:
    command: str
    future: asyncio.Future[CachedDomainApproval]


@dataclass(frozen=True, slots=True)
class DomainBatchSnapshot:
    scope_id: str
    requests: dict[str, PendingDomainRequest]
    can_review: bool
    review_limit: int | None


# --- Audit Log ---


class AuditEntry(BaseModel):
    timestamp: datetime
    kind: Literal["tool_call", "proxy_domain", "git_push", "credential_access"]
    tool: str | None = None
    args_summary: dict[str, Any] = {}
    domain: str | None = None
    sentinel_verdict: SentinelVerdict | None = None
    final_decision: Literal["auto_allowed", "allowed", "escalated", "denied"]
    explanation: str | None = None

    @classmethod
    def now(
        cls,
        *,
        kind: Literal["tool_call", "proxy_domain", "git_push", "credential_access"],
        final_decision: Literal["auto_allowed", "allowed", "escalated", "denied"],
        tool: str | None = None,
        args_summary: dict[str, Any] | None = None,
        domain: str | None = None,
        sentinel_verdict: SentinelVerdict | None = None,
        explanation: str | None = None,
    ) -> AuditEntry:
        return cls(
            timestamp=datetime.now(tz=UTC),
            kind=kind,
            tool=tool,
            args_summary=args_summary or {},
            domain=domain,
            sentinel_verdict=sentinel_verdict,
            final_decision=final_decision,
            explanation=explanation,
        )


# --- Per-Session Security State ---


class SessionSecurity:
    """Mutable per-session security state managed by the security module."""

    def __init__(
        self,
        session_id: str,
        *,
        audit_dir: Path | None = None,
        max_sentinel_calls_per_tool_call: int = 5,
        sentinel_domain_batch_window_ms: int = 100,
        unattended: bool = False,
    ) -> None:
        self.session_id = session_id
        self.unattended = unattended
        self.action_log: list[
            UserMessageEntry
            | ToolCallEntry
            | ToolResultEntry
            | AgentResponseEntry
            | ApprovalEntry
            | SkillActivatedEntry
            | UserVouchedEntry
            | GitPushEntry
            | CredentialAccessEntry
            | ContextGrantEntry
        ] = []
        self.sentinel_eval_count: int = 0
        self.max_sentinel_calls_per_tool_call = max_sentinel_calls_per_tool_call
        self.sentinel_domain_batch_window_ms = sentinel_domain_batch_window_ms
        self._last_synced_idx: int = 0
        self._audit_dir = audit_dir
        self._user_escalation_callback: (
            Callable[[str, str, dict[str, Any]], Awaitable[UserEscalationDecision]] | None
        ) = None
        self._domain_info_callback: (
            Callable[[str, str, ApprovalSource | None, ApprovalVerdict | None, str | None], None] | None
        ) = None
        self._push_info_callback: (
            Callable[[str, str, str, ApprovalSource | None, ApprovalVerdict | None, str | None], Awaitable[None]] | None
        ) = None
        self._credential_info_callback: (
            Callable[[str, str, str, ApprovalSource | None, ApprovalVerdict | None, str | None], None] | None
        ) = None
        self._credential_notify_suppress: Callable[[str], bool] | None = None
        self.current_parent_tool_id: str | None = None
        self._domain_scope_lock = asyncio.Lock()
        self._domain_scope_parent_tool_id: str | None = None
        self._domain_scope_approvals: dict[str, CachedDomainApproval] = {}
        self._domain_scope_sentinel_calls: int = 0
        self._domain_scope_pending_generation: int = 0
        self._domain_scope_pending_requests: dict[str, PendingDomainRequest] = {}
        self._domain_scope_inflight_futures: dict[str, asyncio.Future[CachedDomainApproval]] = {}
        self._domain_scope_worker_task: asyncio.Task[None] | None = None

    def _cancel_domain_future(self, future: asyncio.Future[CachedDomainApproval], message: str) -> None:
        if not future.done():
            future.set_exception(RuntimeError(message))

    def _reset_domain_scope(self) -> None:
        current_task: asyncio.Task[None] | None
        try:
            current_task = asyncio.current_task()
        except RuntimeError:
            current_task = None
        if (
            self._domain_scope_worker_task is not None
            and not self._domain_scope_worker_task.done()
            and self._domain_scope_worker_task is not current_task
        ):
            self._domain_scope_worker_task.cancel()
        for request in self._domain_scope_pending_requests.values():
            self._cancel_domain_future(request.future, "Proxy domain batch was cancelled.")
        for future in self._domain_scope_inflight_futures.values():
            self._cancel_domain_future(future, "Proxy domain batch was cancelled.")
        self._domain_scope_approvals = {}
        self._domain_scope_sentinel_calls = 0
        self._domain_scope_pending_generation = 0
        self._domain_scope_pending_requests = {}
        self._domain_scope_inflight_futures = {}
        self._domain_scope_worker_task = None

    def _sync_domain_scope(self) -> None:
        if self.current_parent_tool_id != self._domain_scope_parent_tool_id:
            self._domain_scope_parent_tool_id = self.current_parent_tool_id
            self._reset_domain_scope()

    def clear_current_parent_tool(self) -> None:
        self.current_parent_tool_id = None
        self._sync_domain_scope()

    async def get_or_enqueue_domain_approval(
        self,
        domain: str,
        command: str,
        worker_factory: Callable[[], asyncio.Task[None]],
    ) -> tuple[CachedDomainApproval | None, asyncio.Future[CachedDomainApproval] | None, bool]:
        async with self._domain_scope_lock:
            self._sync_domain_scope()
            if self.current_parent_tool_id is None:
                return None, None, False

            cached = self._domain_scope_approvals.get(domain)
            if cached is not None:
                return cached, None, False

            inflight = self._domain_scope_inflight_futures.get(domain)
            if inflight is not None:
                return None, inflight, False

            pending = self._domain_scope_pending_requests.get(domain)
            if pending is None:
                future = asyncio.get_running_loop().create_future()
                self._domain_scope_pending_requests[domain] = PendingDomainRequest(command=command, future=future)
                should_notify_queued = True
                self._domain_scope_pending_generation += 1
            else:
                pending.command = command
                future = pending.future
                should_notify_queued = False

            if self._domain_scope_worker_task is None or self._domain_scope_worker_task.done():
                self._domain_scope_worker_task = worker_factory()
            return None, future, should_notify_queued

    async def next_domain_batch(self) -> DomainBatchSnapshot | None:
        while True:
            async with self._domain_scope_lock:
                self._sync_domain_scope()
                if self.current_parent_tool_id is None or not self._domain_scope_pending_requests:
                    self._domain_scope_worker_task = None
                    return None
                generation = self._domain_scope_pending_generation
                wait_seconds = max(self.sentinel_domain_batch_window_ms, 0) / 1000

            if wait_seconds > 0:
                await asyncio.sleep(wait_seconds)

            async with self._domain_scope_lock:
                self._sync_domain_scope()
                if self.current_parent_tool_id is None or not self._domain_scope_pending_requests:
                    self._domain_scope_worker_task = None
                    return None
                if generation != self._domain_scope_pending_generation:
                    continue

                scope_id = self.current_parent_tool_id
                if scope_id is None:
                    self._domain_scope_worker_task = None
                    return None

                requests = self._domain_scope_pending_requests
                self._domain_scope_pending_requests = {}
                for domain, request in requests.items():
                    self._domain_scope_inflight_futures[domain] = request.future

                limit = self.max_sentinel_calls_per_tool_call
                can_review = limit <= 0 or self._domain_scope_sentinel_calls < limit
                if can_review:
                    self._domain_scope_sentinel_calls += 1

                return DomainBatchSnapshot(
                    scope_id=scope_id,
                    requests=requests,
                    can_review=can_review,
                    review_limit=limit if limit > 0 else None,
                )

    async def complete_domain_batch(
        self,
        snapshot: DomainBatchSnapshot,
        results: dict[str, CachedDomainApproval],
    ) -> None:
        async with self._domain_scope_lock:
            self._sync_domain_scope()
            for domain in snapshot.requests:
                self._domain_scope_inflight_futures.pop(domain, None)
            if self.current_parent_tool_id == snapshot.scope_id:
                for domain, result in results.items():
                    self._domain_scope_approvals[domain] = result

    async def fail_domain_batch(self, snapshot: DomainBatchSnapshot) -> None:
        async with self._domain_scope_lock:
            self._sync_domain_scope()
            for domain in snapshot.requests:
                self._domain_scope_inflight_futures.pop(domain, None)
            if (
                snapshot.can_review
                and self.current_parent_tool_id == snapshot.scope_id
                and self._domain_scope_sentinel_calls > 0
            ):
                self._domain_scope_sentinel_calls -= 1

    async def fail_pending_domain_requests(self, snapshot: DomainBatchSnapshot, exc: Exception) -> None:
        async with self._domain_scope_lock:
            self._sync_domain_scope()
            if self.current_parent_tool_id != snapshot.scope_id:
                return

            pending_requests = self._domain_scope_pending_requests
            self._domain_scope_pending_requests = {}
            self._domain_scope_pending_generation += 1

        for request in pending_requests.values():
            self._cancel_domain_future(request.future, str(exc))

    def append(self, entry: ActionLogEntry) -> None:
        self.action_log.append(entry)

    def new_entries_since_sync(
        self,
    ) -> list[
        UserMessageEntry
        | ToolCallEntry
        | ToolResultEntry
        | AgentResponseEntry
        | ApprovalEntry
        | SkillActivatedEntry
        | UserVouchedEntry
        | GitPushEntry
        | CredentialAccessEntry
        | ContextGrantEntry
    ]:
        """Return action log entries added since the last sentinel sync."""
        entries = self.action_log[self._last_synced_idx :]
        self._last_synced_idx = len(self.action_log)
        return entries

    def tool_calls_since_last_user_message(self) -> int:
        count = 0
        for entry in reversed(self.action_log):
            if isinstance(entry, UserMessageEntry):
                break
            if isinstance(entry, ToolCallEntry):
                count += 1
        return count

    def write_audit(self, entry: AuditEntry) -> None:
        if self._audit_dir is None:
            return
        self._audit_dir.mkdir(parents=True, exist_ok=True)
        audit_path = self._audit_dir / "audit.yaml"
        with open(audit_path, "a") as f:
            f.write("---\n")
            yaml.dump(entry.model_dump(mode="json"), f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    def set_user_escalation_callback(
        self,
        callback: Callable[[str, str, dict[str, Any]], Awaitable[UserEscalationDecision]] | None,
    ) -> None:
        self._user_escalation_callback = callback

    def set_domain_info_callback(
        self,
        callback: Callable[[str, str, ApprovalSource | None, ApprovalVerdict | None, str | None], None] | None,
    ) -> None:
        """Set callback to notify the UI about domain access decisions.

        Signature: ``callback(domain, detail, approval_source, approval_verdict, approval_explanation)``.
        """
        self._domain_info_callback = callback

    def notify_domain_decision(
        self,
        domain: str,
        detail: str,
        approval_source: ApprovalSource | None = None,
        approval_verdict: ApprovalVerdict | None = None,
        approval_explanation: str | None = None,
    ) -> None:
        if self._domain_info_callback is not None:
            self._domain_info_callback(domain, detail, approval_source, approval_verdict, approval_explanation)

    def set_push_info_callback(
        self,
        callback: (
            Callable[[str, str, str, ApprovalSource | None, ApprovalVerdict | None, str | None], Awaitable[None]] | None
        ),
    ) -> None:
        """Set callback to notify the UI about push evaluation decisions.

        Signature: ``callback(ref, decision, detail, approval_source, approval_verdict, approval_explanation)``.
        """
        self._push_info_callback = callback

    async def notify_push_decision(
        self,
        ref: str,
        decision: str,
        detail: str,
        approval_source: ApprovalSource | None = None,
        approval_verdict: ApprovalVerdict | None = None,
        approval_explanation: str | None = None,
    ) -> None:
        if self._push_info_callback is not None:
            await self._push_info_callback(
                ref, decision, detail, approval_source, approval_verdict, approval_explanation
            )

    def set_credential_info_callback(
        self,
        callback: Callable[[str, str, str, ApprovalSource | None, ApprovalVerdict | None, str | None], None] | None,
    ) -> None:
        """Set callback to notify the UI about credential access decisions.

        Signature: ``callback(vault_path, name, detail, approval_source, approval_verdict, approval_explanation)``.
        """
        self._credential_info_callback = callback

    def set_credential_notify_suppress(
        self,
        suppress: Callable[[str], bool] | None,
    ) -> None:
        """Set per-exec duplicate suppression for credential UI + logs.

        When set, *suppress* is called with the same vault-path key used for UI
        (single path or ``\"<list>\"`` for batched list operations). If it
        returns True, ``record_credential_access`` and ``notify_credential_decision``
        skip all side effects for that key (action log, audit, session events,
        websocket). Typically wired to ``SandboxManager.mark_credential_notified``.
        """
        self._credential_notify_suppress = suppress

    def _emit_credential_ui(
        self,
        vault_path: str,
        detail: str,
        *,
        name: str = "",
        approval_source: ApprovalSource | None = None,
        approval_verdict: ApprovalVerdict | None = None,
        approval_explanation: str | None = None,
    ) -> None:
        if self._credential_info_callback is not None:
            self._credential_info_callback(
                vault_path,
                name,
                detail,
                approval_source,
                approval_verdict,
                approval_explanation,
            )

    def notify_credential_decision(
        self,
        vault_path: str,
        detail: str,
        *,
        name: str = "",
        approval_source: ApprovalSource | None = None,
        approval_verdict: ApprovalVerdict | None = None,
        approval_explanation: str | None = None,
    ) -> None:
        if self._credential_notify_suppress is not None and self._credential_notify_suppress(vault_path):
            return
        self._emit_credential_ui(
            vault_path,
            detail,
            name=name,
            approval_source=approval_source,
            approval_verdict=approval_verdict,
            approval_explanation=approval_explanation,
        )

    def notify_credential_review(
        self,
        vault_path: str,
        detail: str,
        *,
        name: str = "",
        approval_source: ApprovalSource | None = None,
        approval_verdict: ApprovalVerdict | None = None,
        approval_explanation: str | None = None,
    ) -> None:
        """Emit a provisional credential UI event without triggering duplicate suppression."""
        self._emit_credential_ui(
            vault_path,
            detail,
            name=name,
            approval_source=approval_source,
            approval_verdict=approval_verdict,
            approval_explanation=approval_explanation,
        )

    def record_credential_access(
        self,
        *,
        vault_paths: list[str],
        names: list[str] | None = None,
        decision: Literal["approved", "escalated", "denied"],
        explanation: str,
        ui_label: str,
        approval_source: ApprovalSource,
        approval_verdict: ApprovalVerdict,
        ui_explanation: str | None = None,
        audit_final: Literal["auto_allowed", "allowed", "escalated", "denied"],
        audit_args: dict[str, Any] | None = None,
        sentinel_verdict: SentinelVerdict | None = None,
    ) -> None:
        """Record a credential access in action log, audit log, and UI notification."""
        display_path = vault_paths[0] if len(vault_paths) == 1 else "<list>"
        if self._credential_notify_suppress is not None and self._credential_notify_suppress(display_path):
            return
        self.append(CredentialAccessEntry(vault_paths=vault_paths, decision=decision, explanation=explanation))
        self.write_audit(
            AuditEntry.now(
                kind="credential_access",
                sentinel_verdict=sentinel_verdict,
                final_decision=audit_final,
                args_summary=audit_args or {},
                explanation=explanation,
            ),
        )
        display_name = names[0] if names and len(names) == 1 else ""
        self._emit_credential_ui(
            display_path,
            ui_label,
            name=display_name,
            approval_source=approval_source,
            approval_verdict=approval_verdict,
            approval_explanation=(explanation if approval_source == "sentinel" else ui_explanation),
        )

    async def escalate_to_user(self, subject: str, context: dict[str, Any]) -> UserEscalationDecision:
        if self._user_escalation_callback is None:
            logger.warning(f"No user escalation callback for session {self.session_id}, denying {subject}")
            return UserEscalationDecision(allowed=False)
        return await self._user_escalation_callback(self.session_id, subject, context)

    def reset_sentinel(self) -> None:
        self.sentinel_eval_count = 0
        self._last_synced_idx = 0
