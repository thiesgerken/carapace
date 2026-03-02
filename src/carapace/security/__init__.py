from __future__ import annotations

from pathlib import Path
from typing import Any

from loguru import logger
from pydantic_ai import ApprovalRequired

from carapace.models import UsageTracker
from carapace.security.bouncer import Bouncer
from carapace.security.context import (
    ActionLogEntry,
    AuditEntry,
    BouncerVerdict,
    SessionSecurity,
    ToolCallEntry,
)

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

_sessions: dict[str, SessionSecurity] = {}
_bouncers: dict[str, Bouncer] = {}


def get_session(session_id: str) -> SessionSecurity:
    if session_id not in _sessions:
        raise KeyError(f"No security session for {session_id}")
    return _sessions[session_id]


def init_session(
    session_id: str,
    *,
    bouncer_model: str,
    security_md: str,
    skills_dir: Path,
    audit_dir: Path | None = None,
    reset_threshold: int = 20,
) -> SessionSecurity:
    session = SessionSecurity(session_id, audit_dir=audit_dir)
    _sessions[session_id] = session
    _bouncers[session_id] = Bouncer(
        model=bouncer_model,
        security_md=security_md,
        skills_dir=skills_dir,
        reset_threshold=reset_threshold,
    )
    return session


def cleanup_session(session_id: str) -> None:
    _sessions.pop(session_id, None)
    _bouncers.pop(session_id, None)


def append_log(session_id: str, entry: ActionLogEntry) -> None:
    session = _sessions.get(session_id)
    if session:
        session.append(entry)


async def evaluate(
    session_id: str,
    tool_name: str,
    args: dict[str, Any],
    *,
    usage_tracker: UsageTracker | None = None,
    verbose: bool = True,
    tool_call_callback: Any = None,
) -> None:
    """Main security gate. Auto-allows safe tools; asks the bouncer for everything else.

    Raises ApprovalRequired if the bouncer escalates, or ToolDenied if denied.
    """
    session = _sessions.get(session_id)
    if session is None:
        logger.warning(f"No security session for {session_id}, auto-allowing {tool_name}")
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

    bouncer = _bouncers.get(session_id)
    if bouncer is None:
        logger.warning(f"No bouncer for session {session_id}, auto-allowing {tool_name}")
        return

    verdict = await bouncer.evaluate_tool_call(
        session,
        tool_name,
        args,
        usage_tracker=usage_tracker,
    )

    entry = ToolCallEntry(
        tool=tool_name,
        args=_truncate_args(args),
        decision=_verdict_to_decision(verdict),
        explanation=verdict.explanation,
    )
    session.append(entry)

    session.write_audit(
        AuditEntry(
            kind="tool_call",
            tool=tool_name,
            args_summary=_truncate_args(args),
            bouncer_verdict=verdict,
            final_decision=_verdict_to_decision(verdict),
            explanation=verdict.explanation,
        )
    )

    detail = f"[bouncer: {verdict.decision}] {verdict.explanation}"
    if verbose:
        _log_tool_call(tool_name, args, detail, tool_call_callback)

    if verdict.decision == "deny":
        from pydantic_ai import ToolDenied

        raise ToolDenied(verdict.explanation)

    if verdict.decision == "escalate":
        raise ApprovalRequired(
            metadata={
                "tool": tool_name,
                "args": args,
                "explanation": verdict.explanation,
                "risk_level": verdict.risk_level,
            }
        )


async def evaluate_domain(
    session_id: str,
    domain: str,
    command: str,
    *,
    usage_tracker: UsageTracker | None = None,
) -> bool:
    """Evaluate a proxy domain request. Returns True to allow, False to deny.

    If the bouncer escalates, delegates to the session's user escalation callback.
    """
    session = _sessions.get(session_id)
    if session is None:
        logger.warning(f"No security session for {session_id}, denying domain {domain}")
        return False

    bouncer = _bouncers.get(session_id)
    if bouncer is None:
        logger.warning(f"No bouncer for session {session_id}, denying domain {domain}")
        return False

    verdict = await bouncer.evaluate_domain(
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
    elif verdict.decision == "deny":
        allowed = False
        final_decision = "denied"
    else:
        allowed = await session.escalate_to_user(
            domain,
            {"command": command, "explanation": verdict.explanation},
        )
        final_decision = "allowed" if allowed else "denied"

    session.write_audit(
        AuditEntry(
            kind="proxy_domain",
            domain=domain,
            bouncer_verdict=verdict,
            final_decision=final_decision,
            explanation=verdict.explanation,
        )
    )

    return allowed


def _verdict_to_decision(verdict: BouncerVerdict) -> str:
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
