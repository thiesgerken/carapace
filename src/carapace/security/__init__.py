from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlsplit

from loguru import logger
from pydantic_ai import ApprovalRequired
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.usage import UsageLimits

from carapace.security.context import ActionLogEntry as ActionLogEntry
from carapace.security.context import (
    ApprovalSource,
    ApprovalVerdict,
    AuditEntry,
    CachedDomainApproval,
    DomainBatchSnapshot,
    GitPushEntry,
    SecurityDeniedError,
    SentinelVerdict,
    SessionSecurity,
    ToolCallEntry,
    format_denial_message,
    normalize_optional_message,
)
from carapace.security.context import CredentialAccessEntry as CredentialAccessEntry
from carapace.security.exec_allowlist import match_auto_allowed_exec
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
    assert_llm_budget_available: Callable[[], None] | None = None,
    usage_limits: UsageLimits | None = None,
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

    if tool_name == "exec":
        matched_exec = match_auto_allowed_exec(args)
        if matched_exec is not None:
            explanation = f"Auto-allowed by read-only exec heuristic ({matched_exec})."
            entry = ToolCallEntry(tool=tool_name, args=args, decision="auto_allowed", explanation=explanation)
            session.append(entry)
            session.write_audit(
                AuditEntry.now(
                    kind="tool_call",
                    tool=tool_name,
                    args_summary=args,
                    final_decision="auto_allowed",
                    explanation=explanation,
                )
            )
            if verbose:
                _log_tool_call(
                    tool_name,
                    args,
                    f"[safe-list] auto-allowed read-only exec heuristic ({matched_exec})",
                    tool_call_callback,
                    approval_source="safe-list",
                    approval_verdict="allow",
                    approval_explanation=explanation,
                )
            return

    if verbose:
        _log_tool_call(
            tool_name,
            args,
            "[sentinel] reviewing",
            tool_call_callback,
            approval_source="sentinel",
        )

    try:
        verdict = await sentinel.evaluate_tool_call(
            session,
            tool_name,
            args,
            usage_tracker=usage_tracker,
            assert_llm_budget_available=assert_llm_budget_available,
            usage_limits=usage_limits,
        )
    except UsageLimitExceeded:
        verdict = SentinelVerdict(
            decision="escalate",
            explanation=(
                "Automatic sentinel review hit its internal request limit and could not finish. "
                "Please approve or deny this tool call manually."
            ),
            risk_level="high",
        )

    decision_str = _verdict_to_decision(verdict)
    auto_approved_domain: str | None = None
    approval_explanation = verdict.explanation
    if verdict.decision == "allow":
        auto_approved_domain = _normalize_auto_approve_domain(verdict.auto_approve_domain)
        approval_explanation = _format_tool_approval_explanation(verdict.explanation, auto_approved_domain)

    entry = ToolCallEntry(
        tool=tool_name,
        args=args,
        decision=decision_str,
        explanation=approval_explanation,
    )
    session.append(entry)

    detail = f"[sentinel: {verdict.decision}] {approval_explanation}"
    if verbose:
        _log_tool_call(
            tool_name,
            args,
            detail,
            tool_call_callback,
            approval_source="sentinel",
            approval_verdict=verdict.decision,
            approval_explanation=approval_explanation,
        )

    if verdict.decision == "allow" and auto_approved_domain is not None:
        await session.cache_domain_approval_for_current_tool(
            auto_approved_domain,
            CachedDomainApproval(
                allowed=True,
                approval_source="sentinel",
                approval_verdict="allow",
                explanation=approval_explanation,
                detail=f"[sentinel: allow] {approval_explanation}",
                final_decision="allowed",
                audit_explanation=approval_explanation,
                sentinel_verdict=verdict,
            ),
        )
        logger.info(f"Sentinel auto-approved domain for tool call tool={tool_name} domain={auto_approved_domain}")

    if verdict.decision == "deny":
        session.write_audit(
            AuditEntry.now(
                kind="tool_call",
                tool=tool_name,
                args_summary=args,
                sentinel_verdict=verdict,
                final_decision="denied",
                explanation=approval_explanation,
            )
        )
        raise SecurityDeniedError(format_denial_message("sentinel", verdict.explanation))

    if verdict.decision == "escalate":
        raise ApprovalRequired(
            metadata={
                "tool": tool_name,
                "args": args,
                "explanation": approval_explanation,
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
            explanation=approval_explanation,
        )
    )


async def evaluate_domain_with(
    session: SessionSecurity,
    sentinel: Sentinel,
    domain: str,
    command: str,
    *,
    usage_tracker: UsageTracker | None = None,
    assert_llm_budget_available: Callable[[], None] | None = None,
    usage_limits: UsageLimits | None = None,
) -> bool:
    """Evaluate a proxy domain request. Returns True to allow, False to deny.

    If the sentinel escalates, delegates to the session's user escalation callback.
    """

    if session.current_parent_tool_id is None:
        result = await _evaluate_single_domain_access(
            session,
            sentinel,
            domain,
            command,
            usage_tracker=usage_tracker,
            assert_llm_budget_available=assert_llm_budget_available,
            usage_limits=usage_limits,
        )
        session.notify_domain_decision(
            domain,
            result.detail,
            approval_source=result.approval_source,
            approval_verdict=result.approval_verdict,
            approval_explanation=result.explanation,
        )
        session.write_audit(
            AuditEntry.now(
                kind="proxy_domain",
                domain=domain,
                sentinel_verdict=result.sentinel_verdict,
                final_decision=result.final_decision,
                explanation=result.audit_explanation,
            )
        )
        return result.allowed

    cached_approval, pending_result, should_notify_queued = await session.get_or_enqueue_domain_approval(
        domain,
        command,
        lambda: asyncio.create_task(
            _run_domain_batch_worker(
                session,
                sentinel,
                usage_tracker=usage_tracker,
                assert_llm_budget_available=assert_llm_budget_available,
                usage_limits=usage_limits,
            )
        ),
    )
    if cached_approval is not None:
        display_source: ApprovalSource = "safe-list" if cached_approval.allowed else cached_approval.approval_source
        detail = f"[cached {display_source}: {cached_approval.approval_verdict}] " + "reused earlier decision"
        session.notify_domain_decision(
            domain,
            detail,
            approval_source=display_source,
            approval_verdict=cached_approval.approval_verdict,
            approval_explanation=cached_approval.explanation,
        )
        session.write_audit(
            AuditEntry.now(
                kind="proxy_domain",
                domain=domain,
                final_decision="allowed" if cached_approval.allowed else "denied",
                explanation="Reused earlier domain decision within the same tool call.",
            )
        )
        return cached_approval.allowed

    if pending_result is None:
        result = await _evaluate_single_domain_access(
            session,
            sentinel,
            domain,
            command,
            usage_tracker=usage_tracker,
            assert_llm_budget_available=assert_llm_budget_available,
            usage_limits=usage_limits,
        )
        session.notify_domain_decision(
            domain,
            result.detail,
            approval_source=result.approval_source,
            approval_verdict=result.approval_verdict,
            approval_explanation=result.explanation,
        )
        session.write_audit(
            AuditEntry.now(
                kind="proxy_domain",
                domain=domain,
                sentinel_verdict=result.sentinel_verdict,
                final_decision=result.final_decision,
                explanation=result.audit_explanation,
            )
        )
        return result.allowed

    if should_notify_queued:
        session.notify_domain_decision(domain, "[sentinel] queued for batched review", approval_source="sentinel")

    result = await pending_result
    session.notify_domain_decision(
        domain,
        result.detail,
        approval_source=result.approval_source,
        approval_verdict=result.approval_verdict,
        approval_explanation=result.explanation,
    )
    session.write_audit(
        AuditEntry.now(
            kind="proxy_domain",
            domain=domain,
            sentinel_verdict=result.sentinel_verdict,
            final_decision=result.final_decision,
            explanation=result.audit_explanation,
        )
    )
    return result.allowed


async def _evaluate_single_domain_access(
    session: SessionSecurity,
    sentinel: Sentinel,
    domain: str,
    command: str,
    *,
    usage_tracker: UsageTracker | None = None,
    assert_llm_budget_available: Callable[[], None] | None = None,
    usage_limits: UsageLimits | None = None,
) -> CachedDomainApproval:
    session.notify_domain_decision(domain, "[sentinel] reviewing", approval_source="sentinel")

    try:
        verdict = await sentinel.evaluate_domain_access(
            session,
            domain,
            command,
            usage_tracker=usage_tracker,
            assert_llm_budget_available=assert_llm_budget_available,
            usage_limits=usage_limits,
        )
    except UsageLimitExceeded:
        return await _decision_for_usage_limit(session, domain, command)

    return await _decision_from_verdict(session, domain, command, verdict)


async def _decision_from_verdict(
    session: SessionSecurity,
    domain: str,
    command: str,
    verdict: SentinelVerdict,
) -> CachedDomainApproval:
    allowed: bool
    final_decision: Literal["allowed", "denied"]
    user_message: str | None = None

    if verdict.decision == "allow":
        allowed = True
        final_decision = "allowed"
        detail = f"[sentinel: allow] {verdict.explanation}"
    elif verdict.decision == "deny":
        allowed = False
        final_decision = "denied"
        detail = f"[sentinel: deny] {verdict.explanation}"
    else:
        user_decision = await session.escalate_to_user(
            domain,
            {"command": command, "explanation": verdict.explanation, "kind": "domain_access"},
        )
        allowed = user_decision.allowed
        user_message = user_decision.message
        final_decision = "allowed" if allowed else "denied"
        detail = format_denial_message("user", user_message) if not allowed else "[user: allow]"

    source: ApprovalSource = "sentinel" if verdict.decision != "escalate" else "user"
    approval_verdict: ApprovalVerdict = "allow" if allowed else "deny"
    approval_explanation = (
        verdict.explanation if source == "sentinel" else normalize_optional_message(user_message) or verdict.explanation
    )
    return CachedDomainApproval(
        allowed=allowed,
        approval_source=source,
        approval_verdict=approval_verdict,
        explanation=approval_explanation,
        detail=detail,
        final_decision=final_decision,
        audit_explanation=verdict.explanation,
        sentinel_verdict=verdict,
    )


async def _decision_for_batch_limit(
    session: SessionSecurity,
    domain: str,
    command: str,
    review_limit: int | None,
) -> CachedDomainApproval:
    limit_text = (
        "Automatic sentinel review hit the per-tool-call domain batch limit"
        + (f" ({review_limit})" if review_limit is not None else "")
        + ". Please approve or deny this domain manually."
    )
    verdict = SentinelVerdict(
        decision="escalate",
        explanation=limit_text,
        risk_level="high",
    )
    user_decision = await session.escalate_to_user(
        domain,
        {"command": command, "explanation": verdict.explanation, "kind": "domain_access"},
    )
    allowed = user_decision.allowed
    user_message = user_decision.message
    return CachedDomainApproval(
        allowed=allowed,
        approval_source="user",
        approval_verdict="allow" if allowed else "deny",
        explanation=normalize_optional_message(user_message) or verdict.explanation,
        detail=(
            "[user: allow] sentinel domain batch limit reached"
            if allowed
            else format_denial_message("user", user_message)
        ),
        final_decision="allowed" if allowed else "denied",
        audit_explanation=verdict.explanation,
        sentinel_verdict=verdict,
    )


async def _decision_for_usage_limit(
    session: SessionSecurity,
    domain: str,
    command: str,
) -> CachedDomainApproval:
    verdict = SentinelVerdict(
        decision="escalate",
        explanation=(
            "Automatic sentinel review hit its internal request limit and could not finish. "
            + "Please approve or deny this domain manually."
        ),
        risk_level="high",
    )
    return await _decision_from_verdict(session, domain, command, verdict)


async def _evaluate_domain_batch(
    session: SessionSecurity,
    sentinel: Sentinel,
    snapshot: DomainBatchSnapshot,
    *,
    usage_tracker: UsageTracker | None = None,
    assert_llm_budget_available: Callable[[], None] | None = None,
    usage_limits: UsageLimits | None = None,
) -> dict[str, CachedDomainApproval]:
    domain_commands = {domain: request.command for domain, request in snapshot.requests.items()}
    if not snapshot.can_review:
        return {
            domain: await _decision_for_batch_limit(session, domain, command, snapshot.review_limit)
            for domain, command in domain_commands.items()
        }

    for domain in domain_commands:
        session.notify_domain_decision(domain, "[sentinel] reviewing", approval_source="sentinel")

    try:
        verdict = await sentinel.evaluate_domain_access_batch(
            session,
            domain_commands,
            usage_tracker=usage_tracker,
            assert_llm_budget_available=assert_llm_budget_available,
            usage_limits=usage_limits,
        )
    except UsageLimitExceeded:
        return {
            domain: await _decision_for_usage_limit(session, domain, command)
            for domain, command in domain_commands.items()
        }

    return {
        domain: await _decision_from_verdict(session, domain, command, verdict)
        for domain, command in domain_commands.items()
    }


async def _run_domain_batch_worker(
    session: SessionSecurity,
    sentinel: Sentinel,
    *,
    usage_tracker: UsageTracker | None = None,
    assert_llm_budget_available: Callable[[], None] | None = None,
    usage_limits: UsageLimits | None = None,
) -> None:
    while True:
        snapshot = await session.next_domain_batch()
        if snapshot is None:
            return

        try:
            results = await _evaluate_domain_batch(
                session,
                sentinel,
                snapshot,
                usage_tracker=usage_tracker,
                assert_llm_budget_available=assert_llm_budget_available,
                usage_limits=usage_limits,
            )
        except asyncio.CancelledError:
            await session.fail_domain_batch(snapshot)
            for request in snapshot.requests.values():
                if not request.future.done():
                    request.future.set_exception(RuntimeError("Proxy domain batch was cancelled."))
            raise
        except Exception as exc:
            await session.fail_domain_batch(snapshot)
            await session.fail_pending_domain_requests(snapshot, exc)
            for request in snapshot.requests.values():
                if not request.future.done():
                    request.future.set_exception(exc)
            continue

        await session.complete_domain_batch(snapshot, results)
        for domain, request in snapshot.requests.items():
            result = results[domain]
            if not request.future.done():
                request.future.set_result(result)


async def evaluate_push_with(
    session: SessionSecurity,
    sentinel: Sentinel,
    ref: str,
    is_default_branch: bool,
    commits: str,
    diff: str,
    *,
    usage_tracker: UsageTracker | None = None,
    assert_llm_budget_available: Callable[[], None] | None = None,
    usage_limits: UsageLimits | None = None,
) -> bool:
    """Evaluate a Git push. Returns True to allow, False to deny.

    If the sentinel escalates, delegates to the session's user escalation callback.
    """
    await session.notify_push_decision(ref, "reviewing", "[sentinel] reviewing", approval_source="sentinel")

    verdict = await sentinel.evaluate_push(
        session,
        ref,
        is_default_branch,
        commits,
        diff,
        usage_tracker=usage_tracker,
        assert_llm_budget_available=assert_llm_budget_available,
        usage_limits=usage_limits,
    )

    decision = _verdict_to_decision(verdict)
    user_message: str | None = None

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
        user_decision = await session.escalate_to_user(
            f"git push {ref}",
            {
                "command": f"git push ({ref})",
                "explanation": verdict.explanation,
                "kind": "git_push",
                "ref": ref,
                "changed_files": changed_files,
            },
        )
        allowed = user_decision.allowed
        user_message = user_decision.message
        decision = "allowed" if allowed else "denied"
        detail = format_denial_message("user", user_message) if not allowed else "[user: allow]"

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
        approval_explanation=verdict.explanation if source == "sentinel" else normalize_optional_message(user_message),
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
    assert_llm_budget_available: Callable[[], None] | None = None,
    usage_limits: UsageLimits | None = None,
) -> CredentialAccessEvaluation:
    """Evaluate a credential access request.

    If the sentinel escalates, delegates to the session's user escalation callback.
    ``user_was_prompted`` is False when the sentinel allowed or denied without escalation
    (the engine's escalation callback already persists UI events when escalation runs).
    """
    session.notify_credential_review(vault_path, "[sentinel] reviewing", name=name, approval_source="sentinel")

    verdict = await sentinel.evaluate_credential_access(
        session,
        vault_path,
        name,
        description,
        trigger,
        usage_tracker=usage_tracker,
        assert_llm_budget_available=assert_llm_budget_available,
        usage_limits=usage_limits,
    )

    decision = _verdict_to_decision(verdict)
    user_was_prompted = verdict.decision == "escalate"

    if verdict.decision == "allow":
        allowed = True
        detail = f"[sentinel: allow] {verdict.explanation}"
        user_message: str | None = None
    elif verdict.decision == "deny":
        allowed = False
        detail = f"[sentinel: deny] {verdict.explanation}"
        user_message = None
    else:
        user_decision = await session.escalate_to_user(
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
        allowed = user_decision.allowed
        user_message = user_decision.message
        decision = "allowed" if allowed else "denied"
        detail = format_denial_message("user", user_message) if not allowed else "[user: allow]"

    cred_decision: Literal["approved", "escalated", "denied"] = (
        "approved" if decision == "allowed" else "denied" if decision == "denied" else "escalated"
    )
    source: ApprovalSource = "sentinel" if verdict.decision != "escalate" else "user"
    approval_verdict: ApprovalVerdict = "allow" if allowed else "deny"

    session.record_credential_access(
        vault_paths=[vault_path],
        names=[name],
        decision=cred_decision,
        explanation=verdict.explanation,
        ui_label=detail,
        approval_source=source,
        approval_verdict=approval_verdict,
        ui_explanation=verdict.explanation if source == "sentinel" else normalize_optional_message(user_message),
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


def _normalize_auto_approve_domain(candidate: str | None) -> str | None:
    if candidate is None:
        return None

    text = candidate.strip().lower().rstrip(".")
    if not text:
        return None
    if any(char.isspace() for char in text) or "," in text:
        return None

    hostname = _extract_hostname(text)
    if hostname is None:
        return None
    if "*" in hostname or "@" in hostname:
        return None
    if not re.fullmatch(r"[a-z0-9.-]+", hostname):
        return None
    if hostname.startswith(".") or hostname.endswith(".") or ".." in hostname:
        return None
    if "." not in hostname:
        return None
    return hostname


def _format_tool_approval_explanation(explanation: str, auto_approved_domain: str | None) -> str:
    if auto_approved_domain is None:
        return explanation
    suffix = f"Auto-approved domain for this tool call: {auto_approved_domain}."
    if explanation:
        return f"{explanation} {suffix}"
    return suffix


def _extract_hostname(text: str) -> str | None:
    if "://" in text:
        parsed = urlsplit(text)
        return parsed.hostname.lower() if parsed.hostname else None

    if any(sep in text for sep in ("/", "?", "#")):
        parsed = urlsplit(f"https://{text}")
        return parsed.hostname.lower() if parsed.hostname else None

    if text.count(":") == 1:
        host, port = text.rsplit(":", 1)
        if port.isdigit() and host:
            return host

    return text
