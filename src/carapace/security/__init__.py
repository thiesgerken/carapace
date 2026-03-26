from __future__ import annotations

import re
from typing import Any, Literal

from pydantic_ai import ApprovalRequired

from carapace.security.context import (
    ActionLogEntry as ActionLogEntry,
)
from carapace.security.context import (
    AuditEntry,
    GitPushEntry,
    SecurityDeniedError,
    SentinelVerdict,
    SessionSecurity,
    ToolCallEntry,
)
from carapace.security.sentinel import Sentinel
from carapace.usage import UsageTracker

SAFE_TOOLS: frozenset[str] = frozenset(
    {
        "read",
        "write",
        "edit",
        "apply_patch",
        "read_memory",
        "list_skills",
        "use_skill",
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
        entry = ToolCallEntry(tool=tool_name, args=_truncate_args(args), decision="auto_allowed")
        session.append(entry)
        session.write_audit(
            AuditEntry.now(
                kind="tool_call",
                tool=tool_name,
                args_summary=_truncate_args(args),
                final_decision="auto_allowed",
            )
        )
        if verbose:
            _log_tool_call(tool_name, args, "[safe-list] auto-allowed", tool_call_callback)
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
        args=_truncate_args(args),
        decision=decision_str,
        explanation=verdict.explanation,
    )
    session.append(entry)

    detail = f"[sentinel: {verdict.decision}] {verdict.explanation}"
    if verbose:
        _log_tool_call(tool_name, args, detail, tool_call_callback)

    if verdict.decision == "deny":
        session.write_audit(
            AuditEntry.now(
                kind="tool_call",
                tool=tool_name,
                args_summary=_truncate_args(args),
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
                "args_summary": _truncate_args(args),
            }
        )

    # allow
    session.write_audit(
        AuditEntry.now(
            kind="tool_call",
            tool=tool_name,
            args_summary=_truncate_args(args),
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

    session.notify_domain_decision(domain, detail)

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

    await session.notify_push_decision(ref, decision, detail)

    session.write_audit(
        AuditEntry.now(
            kind="git_push",
            sentinel_verdict=verdict,
            final_decision=decision,
            explanation=verdict.explanation,
        )
    )

    return allowed


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


def _truncate_args(args: dict[str, Any], limit: int = 200) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for k, v in args.items():
        v_str = repr(v) if isinstance(v, str) else str(v)
        result[k] = v_str[:limit] if len(v_str) > limit else v_str
    return result


def _log_tool_call(
    tool_name: str,
    args: dict[str, Any],
    detail: str,
    callback: Any = None,
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
        callback(tool_name, args, detail)
    else:
        print(f"  \033[2m{tool_name}({args_str}) {detail}\033[0m")
