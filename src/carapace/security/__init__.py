from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

from pydantic_ai import ApprovalRequired

from carapace.security.context import (
    ActionLogEntry as ActionLogEntry,
)
from carapace.security.context import (
    ApprovalSource,
    ApprovalVerdict,
    AuditEntry,
    GitPushEntry,
    SecurityDeniedError,
    SentinelVerdict,
    SessionSecurity,
    ToolCallEntry,
)
from carapace.security.context import (
    CredentialAccessEntry as CredentialAccessEntry,
)
from carapace.security.sentinel import Sentinel
from carapace.usage import UsageTracker

SAFE_TOOLS: frozenset[str] = frozenset(
    {
        "read",
        "write",
        "str_replace",
        "list_skills",
    }
)


async def evaluate_with(
    session: SessionSecurity,
    sentinel: Sentinel,
    tool_name: str,
    args: dict[str, Any],
    *,
    usage_tracker: UsageTracker | None = None,
    verbose: bool = True,
    tool_call_callback: Any = None,
) -> None:
    """Main security gate. Auto-allows safe tools; asks the sentinel for everything else.

    Raises ApprovalRequired if the sentinel escalates, or SecurityDeniedError if denied.
    """
    if tool_name in SAFE_TOOLS:
        entry = ToolCallEntry(tool=tool_name, args=args, decision="auto_allowed")
        session.append(entry)
        session.write_audit(
            AuditEntry.now(
                kind="tool_call",
                tool=tool_name,
                args_summary=args,
                final_decision="auto_allowed",
            )
        )
        if verbose:
            _log_tool_call(
                tool_name,
                args,
                "[safe-list] auto-allowed",
                tool_call_callback,
                approval_source="safe-list",
                approval_verdict="allow",
                approval_explanation="auto-allowed",
            )
        return

    verdict = await sentinel.evaluate_tool_call(
        session,
        tool_name,
        args,
        usage_tracker=usage_tracker,
    )

    decision_str = _verdict_to_decision(verdict)

    entry = ToolCallEntry(
        tool=tool_name,
        args=args,
        decision=decision_str,
        explanation=verdict.explanation,
    )
    session.append(entry)

    detail = f"[sentinel: {verdict.decision}] {verdict.explanation}"
    if verbose:
        _log_tool_call(
            tool_name,
            args,
            detail,
            tool_call_callback,
            approval_source="sentinel",
            approval_verdict=verdict.decision,
            approval_explanation=verdict.explanation,
        )

    if verdict.decision == "deny":
        session.write_audit(
            AuditEntry.now(
                kind="tool_call",
                tool=tool_name,
                args_summary=args,
                sentinel_verdict=verdict,
                final_decision="denied",
                explanation=verdict.explanation,
            )
        )
        raise SecurityDeniedError(verdict.explanation)

    if verdict.decision == "escalate":
        raise ApprovalRequired(
            metadata={
                "tool": tool_name,
                "args": args,
                "explanation": verdict.explanation,
                "risk_level": verdict.risk_level,
                "sentinel_verdict": verdict,
                "args_summary": args,
            }
        )

    # allow
    session.write_audit(
        AuditEntry.now(
            kind="tool_call",
            tool=tool_name,
            args_summary=args,
            sentinel_verdict=verdict,
            final_decision="allowed",
            explanation=verdict.explanation,
        )
    )


async def evaluate_domain_with(
    session: SessionSecurity,
    sentinel: Sentinel,
    domain: str,
    command: str,
    *,
    usage_tracker: UsageTracker | None = None,
) -> bool:
    """Evaluate a proxy domain request. Returns True to allow, False to deny.

    If the sentinel escalates, delegates to the session's user escalation callback.
    """

    verdict = await sentinel.evaluate_domain_access(
        session,
        domain,
        command,
        usage_tracker=usage_tracker,
    )

    allowed: bool
    final_decision: str

    if verdict.decision == "allow":
        allowed = True
        final_decision = "allowed"
        detail = f"[sentinel: allow] {verdict.explanation}"
    elif verdict.decision == "deny":
        allowed = False
        final_decision = "denied"
        detail = f"[sentinel: deny] {verdict.explanation}"
    else:
        allowed = await session.escalate_to_user(
            domain,
            {"command": command, "explanation": verdict.explanation, "kind": "domain_access"},
        )
        final_decision = "allowed" if allowed else "denied"
        detail = f"[sentinel: escalate \u2192 {final_decision}] {verdict.explanation}"

    source: ApprovalSource = "sentinel" if verdict.decision != "escalate" else "user"
    approval_verdict: ApprovalVerdict = "allow" if allowed else "deny"
    session.notify_domain_decision(
        domain,
        detail,
        approval_source=source,
        approval_verdict=approval_verdict,
        approval_explanation=verdict.explanation,
    )

    session.write_audit(
        AuditEntry.now(
            kind="proxy_domain",
            domain=domain,
            sentinel_verdict=verdict,
            final_decision=final_decision,
            explanation=verdict.explanation,
        )
    )

    return allowed


async def evaluate_push_with(
    session: SessionSecurity,
    sentinel: Sentinel,
    ref: str,
    is_default_branch: bool,
    commits: str,
    diff: str,
    *,
    usage_tracker: UsageTracker | None = None,
) -> bool:
    """Evaluate a Git push. Returns True to allow, False to deny.

    If the sentinel escalates, delegates to the session's user escalation callback.
    """
    verdict = await sentinel.evaluate_push(
        session,
        ref,
        is_default_branch,
        commits,
        diff,
        usage_tracker=usage_tracker,
    )

    decision = _verdict_to_decision(verdict)

    if verdict.decision == "allow":
        allowed = True
        detail = f"[sentinel: allow] {verdict.explanation}"
    elif verdict.decision == "deny":
        allowed = False
        detail = f"[sentinel: deny] {verdict.explanation}"
    else:
        # Extract changed file names from unified diff headers
        changed_files = sorted(
            {m.group(1) for m in re.finditer(r"^\+\+\+ b/(.+)$", diff, re.MULTILINE) if m.group(1) != "/dev/null"}
        )
        allowed = await session.escalate_to_user(
            f"git push {ref}",
            {
                "command": f"git push ({ref})",
                "explanation": verdict.explanation,
                "kind": "git_push",
                "ref": ref,
                "changed_files": changed_files,
            },
        )
        decision = "allowed" if allowed else "denied"
        detail = f"[sentinel: escalate \u2192 {decision}] {verdict.explanation}"

    entry = GitPushEntry(ref=ref, decision=decision, explanation=verdict.explanation)
    session.append(entry)

    source: ApprovalSource = "sentinel" if verdict.decision != "escalate" else "user"
    approval_verdict: ApprovalVerdict = "allow" if allowed else "deny"
    await session.notify_push_decision(
        ref,
        decision,
        detail,
        approval_source=source,
        approval_verdict=approval_verdict,
        approval_explanation=verdict.explanation,
    )

    session.write_audit(
        AuditEntry.now(
            kind="git_push",
            sentinel_verdict=verdict,
            final_decision=decision,
            explanation=verdict.explanation,
        )
    )

    return allowed


@dataclass(frozen=True, slots=True)
class CredentialAccessEvaluation:
    """Outcome of ``evaluate_credential_with`` for callers that need audit or UI parity."""

    allowed: bool
    """True if access was granted."""

    user_was_prompted: bool
    """True when the sentinel escalated and the user escalation callback ran."""

    explanation: str
    """Sentinel explanation text (same as stored on the audit entry)."""


async def evaluate_credential_with(
    session: SessionSecurity,
    sentinel: Sentinel,
    vault_path: str,
    name: str,
    description: str,
    trigger: str,
    *,
    usage_tracker: UsageTracker | None = None,
) -> CredentialAccessEvaluation:
    """Evaluate a credential access request.

    If the sentinel escalates, delegates to the session's user escalation callback.
    ``user_was_prompted`` is False when the sentinel allowed or denied without escalation
    (the engine's escalation callback already persists UI events when escalation runs).
    """
    verdict = await sentinel.evaluate_credential_access(
        session,
        vault_path,
        name,
        description,
        trigger,
        usage_tracker=usage_tracker,
    )

    decision = _verdict_to_decision(verdict)
    user_was_prompted = verdict.decision == "escalate"

    if verdict.decision == "allow":
        allowed = True
        detail = f"[sentinel: allow] {verdict.explanation}"
    elif verdict.decision == "deny":
        allowed = False
        detail = f"[sentinel: deny] {verdict.explanation}"
    else:
        allowed = await session.escalate_to_user(
            vault_path,
            {
                "kind": "credential_access",
                "vault_path": vault_path,
                "name": name,
                "description": description,
                "explanation": verdict.explanation,
                "trigger": trigger,
            },
        )
        decision = "allowed" if allowed else "denied"
        detail = f"[sentinel: escalate → {decision}] {verdict.explanation}"

    cred_decision: Literal["approved", "escalated", "denied"] = (
        "approved" if decision == "allowed" else "denied" if decision == "denied" else "escalated"
    )
    source: ApprovalSource = "sentinel" if verdict.decision != "escalate" else "user"
    approval_verdict: ApprovalVerdict = "allow" if allowed else "deny"

    session.record_credential_access(
        vault_paths=[vault_path],
        decision=cred_decision,
        explanation=verdict.explanation,
        ui_label=detail,
        approval_source=source,
        approval_verdict=approval_verdict,
        audit_final=decision,
        sentinel_verdict=verdict,
    )

    return CredentialAccessEvaluation(
        allowed=allowed,
        user_was_prompted=user_was_prompted,
        explanation=verdict.explanation,
    )


def _verdict_to_decision(verdict: SentinelVerdict) -> Literal["allowed", "escalated", "denied"]:
    match verdict.decision:
        case "allow":
            return "allowed"
        case "escalate":
            return "escalated"
        case "deny":
            return "denied"
        case _:
            return "denied"


def _log_tool_call(
    tool_name: str,
    args: dict[str, Any],
    detail: str,
    callback: Any = None,
    approval_source: ApprovalSource | None = None,
    approval_verdict: ApprovalVerdict | None = None,
    approval_explanation: str | None = None,
) -> None:
    args_parts = []
    for k, v in args.items():
        v_str = repr(v) if isinstance(v, str) else str(v)
        if len(v_str) > 60:
            v_str = v_str[:57] + "..."
        args_parts.append(f"{k}={v_str}")
    args_str = ", ".join(args_parts)
    if len(args_str) > 200:
        args_str = args_str[:197] + "..."

    if callback:
        callback(tool_name, args, detail, approval_source, approval_verdict, approval_explanation)
    else:
        print(f"  \033[2m{tool_name}({args_str}) {detail}\033[0m")
