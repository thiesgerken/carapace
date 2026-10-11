"""Security approval callbacks and tool-call event recording for SessionEngine."""

from __future__ import annotations

import asyncio
import secrets
import uuid
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from loguru import logger
from pydantic_ai.exceptions import UsageLimitExceeded

from .. import security as security_mod
from ..models.tooling import normalize_tool_call_args
from ..notifications.router import NotificationRouter, build_escalation_notification_id
from ..security.context import (
    ApprovalSource,
    ApprovalVerdict,
    SessionSecurity,
    UserEscalationDecision,
    normalize_optional_message,
)
from ..security.sentinel import Sentinel
from ..usage import SessionBudgetExceededError
from ..ws_models import EscalationResponse
from .manager import SessionManager
from .types import ActiveSession

if TYPE_CHECKING:
    from contextlib import AbstractContextManager

    from pydantic_ai.usage import UsageLimits


def _escalation_notification_body(subject: str, kind: str) -> str:
    match kind:
        case "git_push":
            return f"Approval needed to push changes to {subject}."
        case "credential_access":
            return f"Approval needed to access credential {subject}."
        case _:
            return f"Approval needed to access {subject}."


class SessionApprovalMixin:
    _notification_router: NotificationRouter | None
    _session_mgr: SessionManager

    if TYPE_CHECKING:

        async def _broadcast(self, active: ActiveSession, method: str, *args: Any, **kwargs: Any) -> None: ...
        async def _clear_pending_notification(self, active: ActiveSession, session_id: str, notif_id: str) -> None: ...
        def llm_request_recording(self, active: ActiveSession) -> AbstractContextManager[Any, bool | None]: ...
        def _assert_llm_budget_available(self, active: ActiveSession) -> None: ...
        def _remaining_aux_usage_limits(self, active: ActiveSession) -> UsageLimits | None: ...

    def _record_tool_call_event(
        self,
        session_id: str,
        *,
        tool: str,
        args: dict[str, Any],
        detail: str,
        approval_source: ApprovalSource | None = None,
        approval_verdict: ApprovalVerdict | None = None,
        approval_explanation: str | None = None,
        parent_tool_id: str | None = None,
        match_args: dict[str, Any] | None = None,
    ) -> str:
        normalized_args = normalize_tool_call_args(tool, args)
        contexts_raw = normalized_args.get("contexts")
        matching_args = normalize_tool_call_args(tool, match_args) if match_args is not None else normalized_args
        event: dict[str, Any] = {
            "role": "tool_call",
            "tool": tool,
            "args": normalized_args,
            "detail": detail,
            "approval_source": approval_source,
            "approval_verdict": approval_verdict,
            "approval_explanation": approval_explanation,
        }
        if parent_tool_id is not None:
            event["parent_tool_id"] = parent_tool_id
        if isinstance(contexts_raw, list):
            event["contexts"] = list(contexts_raw)

        is_pending_sentinel_update = approval_source == "sentinel" and approval_verdict is None
        should_update_existing = approval_source in {"sentinel", "user"} and (
            approval_verdict is not None or (tool == "proxy_domain" and is_pending_sentinel_update)
        )

        def _mutate(events: list[dict[str, Any]]) -> str:
            if should_update_existing:
                for index in range(len(events) - 1, -1, -1):
                    existing = events[index]
                    if existing.get("role") != "tool_call":
                        continue
                    if existing.get("tool") != tool:
                        continue
                    if existing.get("parent_tool_id") != parent_tool_id:
                        continue
                    if existing.get("approval_source") != "sentinel":
                        continue
                    if existing.get("approval_verdict") not in (None, "escalate"):
                        continue
                    existing_args = existing.get("args")
                    if not isinstance(existing_args, dict):
                        continue
                    if any(existing_args.get(key) != value for key, value in matching_args.items()):
                        continue

                    tool_id = str(existing.get("tool_id") or uuid.uuid4())
                    events[index] = {**existing, **event, "tool_id": tool_id}
                    return tool_id

            tool_id = str(uuid.uuid4())
            events.append({**event, "tool_id": tool_id})
            return tool_id

        return self._session_mgr.update_events(session_id, _mutate)

    def _make_escalation_cb(
        self,
        active: ActiveSession,
    ) -> Callable[[str, str, dict[str, Any]], Awaitable[UserEscalationDecision]]:
        """Build a callback that broadcasts sentinel escalations (proxy domain or git push) to subscribers."""

        async def _escalate(session_id: str, subject: str, context: dict[str, Any]) -> UserEscalationDecision:
            request_id = secrets.token_hex(8)
            notif_id = build_escalation_notification_id(session_id, request_id)
            cmd = context.get("command", "")
            kind = context.get("kind", "domain_access")

            # Auto-deny stale pending escalations of the same kind+key.
            # This happens when an exec timeout killed git push but the old
            # escalation callback is still blocked on the queue.
            match_key = {"git_push": "ref", "credential_access": "vault_path"}.get(kind, "domain")
            match_val = context.get(match_key, subject)
            for old in list(active.pending_escalations):
                if old.get("kind") == kind and old.get(match_key) == match_val:
                    logger.info(f"Superseding stale {kind} escalation {old['request_id']} for {match_val}")
                    active.escalation_queue.put_nowait(
                        EscalationResponse(request_id=old["request_id"], decision="deny")
                    )

            if kind == "git_push":
                ref = context.get("ref", subject)
                explanation = context.get("explanation", "")
                changed_files: list[str] = context.get("changed_files", [])
                self._session_mgr.append_events(
                    session_id,
                    [
                        {
                            "role": "git_push_approval",
                            "request_id": request_id,
                            "ref": ref,
                            "explanation": explanation,
                            "changed_files": changed_files,
                        }
                    ],
                )
                active.pending_escalations.append(
                    {
                        "request_id": request_id,
                        "kind": "git_push",
                        "ref": ref,
                        "explanation": explanation,
                        "changed_files": changed_files,
                    }
                )
                await self._broadcast(
                    active, "on_git_push_approval_request", request_id, ref, explanation, changed_files
                )
            elif kind == "credential_access":
                vault_path = context.get("vault_path", subject)
                cred_name = context.get("name", vault_path)
                cred_desc = context.get("description", "")
                explanation = context.get("explanation", "")
                self._session_mgr.append_events(
                    session_id,
                    [
                        {
                            "role": "credential_approval",
                            "request_id": request_id,
                            "vault_paths": [vault_path],
                            "names": [cred_name],
                            "descriptions": [cred_desc],
                            "explanation": explanation,
                        }
                    ],
                )
                active.pending_escalations.append(
                    {
                        "request_id": request_id,
                        "kind": "credential_access",
                        "vault_path": vault_path,
                        "vault_paths": [vault_path],
                        "names": [cred_name],
                        "descriptions": [cred_desc],
                        "explanation": explanation,
                    }
                )
                await self._broadcast(
                    active,
                    "on_credential_approval_request",
                    request_id,
                    [vault_path],
                    [cred_name],
                    [cred_desc],
                    None,
                    explanation,
                )
            else:
                self._session_mgr.append_events(
                    session_id,
                    [{"role": "domain_access_approval", "request_id": request_id, "domain": subject, "command": cmd}],
                )
                active.pending_escalations.append(
                    {"request_id": request_id, "kind": "domain_access", "domain": subject, "command": cmd}
                )
                await self._broadcast(active, "on_domain_access_approval_request", request_id, subject, cmd)

            if self._notification_router is not None:
                delivered = await self._notification_router.dispatch_escalation(
                    session_id=session_id,
                    request_id=request_id,
                    title="Action Required",
                    body=_escalation_notification_body(subject, kind),
                )
                if delivered.delivered_subscription_ids:
                    active.pending_notifications[notif_id] = delivered.delivered_subscription_ids
            # Block until a subscriber responds
            while True:
                msg = await active.escalation_queue.get()
                if msg is None:
                    await self._clear_pending_notification(active, session_id, notif_id)
                    active.pending_escalations = [
                        p for p in active.pending_escalations if p["request_id"] != request_id
                    ]
                    return UserEscalationDecision(allowed=False)
                if msg.request_id == request_id:
                    decision = msg.decision
                    message = normalize_optional_message(msg.message)
                    event_roles = {
                        "git_push": "git_push_approval",
                        "credential_access": "credential_approval",
                    }
                    event_role = event_roles.get(kind, "domain_access_approval")
                    if kind == "credential_access":
                        vp = context.get("vault_path", subject)
                        response_event: dict[str, Any] = {
                            "role": event_role,
                            "request_id": request_id,
                            "vault_paths": [vp],
                            "decision": decision,
                            "decision_source": "user",
                            "message": message,
                        }
                    else:
                        response_event = {
                            "role": event_role,
                            "request_id": request_id,
                            "domain": subject,
                            "command": cmd,
                            "decision": decision,
                            "decision_source": "user",
                            "message": message,
                        }
                    self._session_mgr.append_events(session_id, [response_event])
                    active.pending_escalations = [
                        p for p in active.pending_escalations if p["request_id"] != request_id
                    ]
                    await self._clear_pending_notification(active, session_id, notif_id)
                    return UserEscalationDecision(allowed=decision != "deny", message=message)

        return _escalate

    def _make_domain_info_cb(
        self,
        active: ActiveSession,
    ) -> Callable[
        [
            str,
            str,
            ApprovalSource | None,
            ApprovalVerdict | None,
            str | None,
        ],
        None,
    ]:
        """Build a callback that broadcasts domain access decisions to subscribers."""
        session_id = active.state.session_id

        def _notify(
            domain: str,
            detail: str,
            approval_source: ApprovalSource | None = None,
            approval_verdict: ApprovalVerdict | None = None,
            approval_explanation: str | None = None,
        ) -> None:
            parent_id = active.security.current_parent_tool_id if active.security else None
            tool_id = self._record_tool_call_event(
                session_id,
                tool="proxy_domain",
                args={"domain": domain},
                detail=detail,
                approval_source=approval_source,
                approval_verdict=approval_verdict,
                approval_explanation=approval_explanation,
                parent_tool_id=parent_id,
            )
            task = asyncio.ensure_future(
                self._broadcast(
                    active,
                    "on_domain_info",
                    domain,
                    detail,
                    approval_source,
                    approval_verdict,
                    approval_explanation,
                    tool_id,
                    parent_id,
                )
            )
            active._pending_sends.add(task)
            task.add_done_callback(active._pending_sends.discard)

        return _notify

    def _make_push_info_cb(
        self,
        active: ActiveSession,
    ) -> Callable[
        [
            str,
            str,
            str,
            ApprovalSource | None,
            ApprovalVerdict | None,
            str | None,
        ],
        Awaitable[None],
    ]:
        """Build a callback that broadcasts git push decisions to subscribers."""
        session_id = active.state.session_id

        async def _notify(
            ref: str,
            decision: str,
            detail: str,
            approval_source: ApprovalSource | None = None,
            approval_verdict: ApprovalVerdict | None = None,
            approval_explanation: str | None = None,
        ) -> None:
            parent_id = active.security.current_parent_tool_id if active.security else None
            tool_id = self._record_tool_call_event(
                session_id,
                tool="git_push",
                args={"ref": ref, "decision": decision},
                detail=detail,
                approval_source=approval_source,
                approval_verdict=approval_verdict,
                approval_explanation=approval_explanation,
                parent_tool_id=parent_id,
                match_args={"ref": ref},
            )
            await self._broadcast(
                active,
                "on_git_push_info",
                ref,
                decision,
                detail,
                approval_source,
                approval_verdict,
                approval_explanation,
                tool_id,
                parent_id,
            )

        return _notify

    def _make_credential_info_cb(
        self,
        active: ActiveSession,
    ) -> Callable[
        [
            str,
            str,
            str,
            ApprovalSource | None,
            ApprovalVerdict | None,
            str | None,
        ],
        None,
    ]:
        """Build a callback that broadcasts credential access decisions to subscribers."""
        session_id = active.state.session_id

        def _notify(
            vault_path: str,
            name: str,
            detail: str,
            approval_source: ApprovalSource | None = None,
            approval_verdict: ApprovalVerdict | None = None,
            approval_explanation: str | None = None,
        ) -> None:
            parent_id = active.security.current_parent_tool_id if active.security else None
            tool_id = self._record_tool_call_event(
                session_id,
                tool="credential_access",
                args={"vault_path": vault_path, "name": name},
                detail=detail,
                approval_source=approval_source,
                approval_verdict=approval_verdict,
                approval_explanation=approval_explanation,
                parent_tool_id=parent_id,
                match_args={"vault_path": vault_path},
            )
            task = asyncio.ensure_future(
                self._broadcast(
                    active,
                    "on_credential_info",
                    vault_path,
                    name,
                    detail,
                    approval_source,
                    approval_verdict,
                    approval_explanation,
                    tool_id,
                    parent_id,
                )
            )
            active._pending_sends.add(task)
            task.add_done_callback(active._pending_sends.discard)

        return _notify

    def _make_domain_eval_cb(
        self,
        security: SessionSecurity,
        sentinel: Sentinel,
        active: ActiveSession,
    ) -> Callable[[str, str], Awaitable[bool]]:
        """Build a callback for SandboxManager.request_domain_approval."""

        async def _eval(domain: str, command: str) -> bool:
            with self.llm_request_recording(active):
                try:
                    return await security_mod.evaluate_domain_with(
                        security,
                        sentinel,
                        domain,
                        command,
                        usage_tracker=active.usage_tracker,
                        assert_llm_budget_available=lambda: self._assert_llm_budget_available(active),
                        usage_limits=self._remaining_aux_usage_limits(active),
                    )
                except SessionBudgetExceededError as exc:
                    logger.info(f"Session budget blocked domain evaluation for {active.state.session_id}: {exc}")
                    return False
                except UsageLimitExceeded as exc:
                    logger.info(f"Usage limits blocked domain evaluation for {active.state.session_id}: {exc}")
                    return False

        return _eval
