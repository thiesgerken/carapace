from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from loguru import logger
from pydantic import BaseModel, Field


class SecurityDeniedError(Exception):
    """Raised when the sentinel denies a tool call."""


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


ActionLogEntry = Annotated[
    UserMessageEntry
    | ToolCallEntry
    | ToolResultEntry
    | AgentResponseEntry
    | ApprovalEntry
    | SkillActivatedEntry
    | UserVouchedEntry
    | GitPushEntry
    | CredentialAccessEntry,
    Field(discriminator="type"),
]


# --- Sentinel Verdict ---


class SentinelVerdict(BaseModel):
    decision: Literal["allow", "escalate", "deny"]
    explanation: str = ""
    risk_level: Literal["low", "medium", "high"] = "medium"


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

    def __init__(self, session_id: str, *, audit_dir: Path | None = None) -> None:
        self.session_id = session_id
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
        ] = []
        self.sentinel_eval_count: int = 0
        self._last_synced_idx: int = 0
        self._audit_dir = audit_dir
        self._user_escalation_callback: Callable[[str, str, dict[str, Any]], Awaitable[bool]] | None = None
        self._domain_info_callback: Callable[[str, str], None] | None = None
        self._push_info_callback: Callable[[str, str, str], Awaitable[None]] | None = None
        self._credential_info_callback: Callable[[str, str], None] | None = None

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
        callback: Callable[[str, str, dict[str, Any]], Awaitable[bool]] | None,
    ) -> None:
        self._user_escalation_callback = callback

    def set_domain_info_callback(
        self,
        callback: Callable[[str, str], None] | None,
    ) -> None:
        """Set callback to notify the UI about domain access decisions.

        Signature: ``callback(domain, detail)``.
        """
        self._domain_info_callback = callback

    def notify_domain_decision(self, domain: str, detail: str) -> None:
        if self._domain_info_callback is not None:
            self._domain_info_callback(domain, detail)

    def set_push_info_callback(
        self,
        callback: Callable[[str, str, str], Awaitable[None]] | None,
    ) -> None:
        """Set callback to notify the UI about push evaluation decisions.

        Signature: ``callback(ref, decision, detail)``.
        """
        self._push_info_callback = callback

    async def notify_push_decision(self, ref: str, decision: str, detail: str) -> None:
        if self._push_info_callback is not None:
            await self._push_info_callback(ref, decision, detail)

    def set_credential_info_callback(
        self,
        callback: Callable[[str, str], None] | None,
    ) -> None:
        """Set callback to notify the UI about credential access decisions.

        Signature: ``callback(vault_path, detail)``.
        """
        self._credential_info_callback = callback

    def notify_credential_decision(self, vault_path: str, detail: str) -> None:
        if self._credential_info_callback is not None:
            self._credential_info_callback(vault_path, detail)

    async def escalate_to_user(self, subject: str, context: dict[str, Any]) -> bool:
        if self._user_escalation_callback is None:
            logger.warning(f"No user escalation callback for session {self.session_id}, denying {subject}")
            return False
        return await self._user_escalation_callback(self.session_id, subject, context)

    def reset_sentinel(self) -> None:
        self.sentinel_eval_count = 0
        self._last_synced_idx = 0
