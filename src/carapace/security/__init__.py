from __future__ import annotations

from pathlib import Path
from typing import Any

from loguru import logger
from pydantic_ai import ApprovalRequired

from carapace.models import UsageTracker
from carapace.security.context import (
    ActionLogEntry,
    AuditEntry,
    SecurityDeniedError,
    SentinelVerdict,
    SessionSecurity,
    ToolCallEntry,
)
from carapace.security.sentinel import Sentinel

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

# --- Legacy global dicts (kept for backward compatibility during transition) ---

_sessions: dict[str, SessionSecurity] = {}
_sentinels: dict[str, Sentinel] = {}
_session_refs: dict[str, int] = {}


def get_session(session_id: str) -> SessionSecurity:
    if session_id not in _sessions:
        raise KeyError(f"No security session for {session_id}")
    return _sessions[session_id]


def init_session(
    session_id: str,
    *,
    sentinel_model: str,
    security_md: str,
    skills_dir: Path,
    audit_dir: Path | None = None,
    reset_threshold: int = 20,
) -> SessionSecurity:
    """Create or reuse a security session (refcount-based).

    If the session already exists the existing state is returned and the
    reference count is incremented.  This keeps the sentinel conversation and
    action log intact when multiple WebSocket clients share a session.
    """
    if session_id in _sessions:
        _session_refs[session_id] = _session_refs.get(session_id, 1) + 1
        logger.debug(f"Reusing existing security session {session_id} (refs={_session_refs[session_id]})")
        return _sessions[session_id]

    session = SessionSecurity(session_id, audit_dir=audit_dir)
    _sessions[session_id] = session
    _sentinels[session_id] = Sentinel(
        model=sentinel_model,
        security_md=security_md,
        skills_dir=skills_dir,
        reset_threshold=reset_threshold,
    )
    _session_refs[session_id] = 1
    return session


def cleanup_session(session_id: str) -> None:
    """Decrement the reference count; only remove state when the last ref is released."""
    refs = _session_refs.get(session_id, 0)
    if refs > 1:
        _session_refs[session_id] = refs - 1
        logger.debug(f"Security session {session_id} ref decremented (refs={refs - 1})")
        return
    _sessions.pop(session_id, None)
    _sentinels.pop(session_id, None)
    _session_refs.pop(session_id, None)


def destroy_session(session_id: str) -> None:
    """Unconditionally remove all security state for a session."""
    _sessions.pop(session_id, None)
    _sentinels.pop(session_id, None)
    _session_refs.pop(session_id, None)


def append_log(session_id: str, entry: ActionLogEntry) -> None:
    session = _sessions.get(session_id)
    if session:
        session.append(entry)


def write_audit(session_id: str, entry: AuditEntry) -> None:
    """Write an audit entry for the given session."""
    session = _sessions.get(session_id)
    if session:
        session.write_audit(entry)


async def evaluate(
    session_id: str,
    tool_name: str,
    args: dict[str, Any],
    *,
    usage_tracker: UsageTracker | None = None,
    verbose: bool = True,
    tool_call_callback: Any = None,
) -> None:
    """Main security gate (global-dict lookup). Delegates to evaluate_with."""
    session = _sessions.get(session_id)
    sentinel = _sentinels.get(session_id)
    await evaluate_with(
        session,
        sentinel,
        tool_name,
        args,
        usage_tracker=usage_tracker,
        verbose=verbose,
        tool_call_callback=tool_call_callback,
    )


async def evaluate_with(
    session: SessionSecurity | None,
    sentinel: Sentinel | None,
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
    if session is None:
        logger.warning(f"No security session, auto-allowing {tool_name}")
        return

    if tool_name in SAFE_TOOLS:
        entry = ToolCallEntry(tool=tool_name, args=_truncate_args(args), decision="auto_allowed")
        session.append(entry)
        session.write_audit(
            AuditEntry(
                kind="tool_call",
                tool=tool_name,
                args_summary=_truncate_args(args),
                final_decision="auto_allowed",
            )
        )
        if verbose:
            _log_tool_call(tool_name, args, "[safe-list] auto-allowed", tool_call_callback)
        return

    if sentinel is None:
        logger.warning(f"No sentinel, auto-allowing {tool_name}")
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
            AuditEntry(
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
        AuditEntry(
            kind="tool_call",
            tool=tool_name,
            args_summary=_truncate_args(args),
            sentinel_verdict=verdict,
            final_decision="allowed",
            explanation=verdict.explanation,
        )
    )


async def evaluate_domain(
    session_id: str,
    domain: str,
    command: str,
    *,
    usage_tracker: UsageTracker | None = None,
) -> bool:
    """Evaluate a proxy domain request (global-dict lookup). Delegates to evaluate_domain_with."""
    session = _sessions.get(session_id)
    sentinel = _sentinels.get(session_id)
    return await evaluate_domain_with(
        session,
        sentinel,
        domain,
        command,
        usage_tracker=usage_tracker,
    )


async def evaluate_domain_with(
    session: SessionSecurity | None,
    sentinel: Sentinel | None,
    domain: str,
    command: str,
    *,
    usage_tracker: UsageTracker | None = None,
) -> bool:
    """Evaluate a proxy domain request. Returns True to allow, False to deny.

    If the sentinel escalates, delegates to the session's user escalation callback.
    """
    if session is None:
        logger.warning(f"No security session, denying domain {domain}")
        return False

    if sentinel is None:
        logger.warning(f"No sentinel, denying domain {domain}")
        return False

    verdict = await sentinel.evaluate_domain(
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
            {"command": command, "explanation": verdict.explanation},
        )
        final_decision = "allowed" if allowed else "denied"
        detail = f"[sentinel: escalate \u2192 {final_decision}] {verdict.explanation}"

    session.notify_domain_decision(domain, detail)

    session.write_audit(
        AuditEntry(
            kind="proxy_domain",
            domain=domain,
            sentinel_verdict=verdict,
            final_decision=final_decision,
            explanation=verdict.explanation,
        )
    )

    return allowed


def _verdict_to_decision(verdict: SentinelVerdict) -> str:
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
