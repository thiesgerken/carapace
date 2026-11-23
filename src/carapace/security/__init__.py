from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic_ai import ApprovalRequired
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.usage import UsageLimits

from ..git.diff import touched_paths
from ..usage import UsageTracker
from .context import (
    CREDENTIAL_LISTING_PATH,
    ApprovalSource,
    ApprovalVerdict,
    AuditEntry,
    BoundaryEvaluation,
    CachedDomainApproval,
    ChangesRequestedError,
    DomainBatchSnapshot,
    GitPushEntry,
    SecurityDeniedError,
    SentinelVerdict,
    SessionSecurity,
    ToolCallEntry,
    UpfrontRequest,
    format_changes_requested_message,
    format_denial_message,
    normalize_optional_message,
)
from .context import ActionLogEntry as ActionLogEntry
from .context import CredentialAccessEntry as CredentialAccessEntry
from .sentinel import Sentinel

SAFE_TOOLS: frozenset[str] = frozenset(
    {
        "read",
        "write",
        "str_replace",
        "list_skills",
        "send_file",
        # Shows an already pushed artifact (the push itself was gated) and sends nothing out.
        "show_artifact",
        # Only returns tool output this session's agent has already seen.
        "read_tool_output",
        # The sandbox is the boundary: a command only reaches the outside through the proxy, `ccred`
        # or `cgate`, and each of those is reviewed when it asks. The exec itself stays in the action log.
        "exec",
    }
)


def _fallback_verdict(session: SessionSecurity, *, explanation: str) -> SentinelVerdict:
    return SentinelVerdict(
        decision="deny" if session.unattended else "escalate",
        explanation=explanation,
        risk_level="high",
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
    tool_call_callback: Any = None,
    tool_call_id: str | None,
) -> None:
    """Main security gate. Auto-allows safe tools; asks the sentinel for everything else.

    Raises ApprovalRequired if the sentinel escalates, ChangesRequestedError if it wants the agent
    to change its approach, or SecurityDeniedError if denied.
    """
    if session.yolo_mode:
        explanation = "YOLO mode bypassed sentinel."
        entry = ToolCallEntry(tool=tool_name, args=args, decision="allowed", explanation=explanation)
        session.append(entry)
        session.write_audit(
            AuditEntry.now(
                kind="tool_call",
                tool=tool_name,
                args_summary=args,
                final_decision="allowed",
                explanation=explanation,
            )
        )
        _log_tool_call(
            tool_name,
            args,
            "[bypass] yolo mode auto-allowed",
            tool_call_callback,
            tool_call_id=tool_call_id,
            approval_source="bypass",
            approval_verdict="allow",
            approval_explanation=explanation,
        )
        return

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
        _log_tool_call(
            tool_name,
            args,
            "[safe-list] auto-allowed",
            tool_call_callback,
            tool_call_id=tool_call_id,
            approval_source="safe-list",
            approval_verdict="allow",
            approval_explanation="auto-allowed",
        )
        return

    _log_tool_call(
        tool_name,
        args,
        "[sentinel] reviewing",
        tool_call_callback,
        tool_call_id=tool_call_id,
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
        verdict = _fallback_verdict(
            session,
            explanation=(
                "Automatic sentinel review hit its internal request limit and could not finish. "
                + (
                    "The tool call was denied because no user approval path is available."
                    if session.unattended
                    else "Please approve or deny this tool call manually."
                )
            ),
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
    _log_tool_call(
        tool_name,
        args,
        detail,
        tool_call_callback,
        tool_call_id=tool_call_id,
        approval_source="sentinel",
        approval_verdict=verdict.decision,
        approval_explanation=verdict.explanation,
        approval_comment=verdict.comment or None,
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
        raise SecurityDeniedError(format_denial_message("sentinel", verdict.explanation))

    if verdict.decision == "revise":
        session.write_audit(
            AuditEntry.now(
                kind="tool_call",
                tool=tool_name,
                args_summary=args,
                sentinel_verdict=verdict,
                final_decision="changes_requested",
                explanation=verdict.explanation,
            )
        )
        raise ChangesRequestedError(format_changes_requested_message(verdict.explanation))

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
    if verdict.comment:
        subject = f"the `{tool_name}` call {tool_call_id}" if tool_call_id else f"the `{tool_name}` call"
        session.leave_comment_for_agent(subject, verdict.comment)


async def evaluate_domain_with(
    session: SessionSecurity,
    sentinel: Sentinel,
    domain: str,
    command: str,
    *,
    exec_id: str,
    follow_up: bool,
    usage_tracker: UsageTracker | None = None,
    assert_llm_budget_available: Callable[[], None] | None = None,
    usage_limits: UsageLimits | None = None,
) -> BoundaryEvaluation:
    """Evaluate a proxy domain request as a decision of its own: no earlier review covers it.

    Requests of one exec (*exec_id*) are reviewed together and their decisions reused until that exec
    ends; the next exec asks again. *follow_up* says the sentinel already decided a request of this exec, so the
    request need not repeat the command.

    If the sentinel escalates, delegates to the session's user escalation callback.
    """

    if session.yolo_mode:
        explanation = "YOLO mode bypassed sentinel."
        session.notify_domain_decision(
            domain,
            "[bypass] yolo mode auto-allowed",
            approval_source="bypass",
            approval_verdict="allow",
            approval_explanation=explanation,
        )
        session.write_audit(
            AuditEntry.now(
                kind="proxy_domain",
                domain=domain,
                final_decision="allowed",
                explanation=explanation,
            )
        )
        return BoundaryEvaluation(allowed=True, rejection="")

    cached_approval, pending_result, should_notify_queued = await session.get_or_enqueue_domain_approval(
        domain,
        command,
        exec_id,
        follow_up,
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
                explanation="Reused earlier domain decision within the same exec.",
            )
        )
        return cached_approval.evaluation()

    assert pending_result is not None, "no earlier decision, so a review is pending"

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
    return result.evaluation()


async def _decision_from_verdict(
    session: SessionSecurity,
    domain: str,
    command: str,
    verdict: SentinelVerdict,
) -> CachedDomainApproval:
    allowed: bool
    final_decision: Literal["allowed", "denied"]
    user_message: str | None = None
    rejection = ""

    match verdict.decision:
        case "allow":
            allowed = True
            final_decision = "allowed"
            detail = f"[sentinel: allow] {verdict.explanation}"
        case "deny":
            allowed = False
            final_decision = "denied"
            detail = f"[sentinel: deny] {verdict.explanation}"
            rejection = format_denial_message("sentinel", verdict.explanation)
        case "escalate":
            user_decision = await session.escalate_to_user(
                domain,
                {"command": command, "explanation": verdict.explanation, "kind": "domain_access"},
            )
            allowed = user_decision.allowed
            user_message = user_decision.message
            final_decision = "allowed" if allowed else "denied"
            rejection = "" if allowed else format_denial_message("user", user_message)
            detail = rejection or "[user: allow]"
        case "revise":
            raise _revise_not_offered("domain access")

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
        rejection=rejection,
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
        + (
            ". The domain request was denied because no user approval path is available."
            if session.unattended
            else ". Please approve or deny this domain manually."
        )
    )
    verdict = _fallback_verdict(session, explanation=limit_text)
    if session.unattended:
        return CachedDomainApproval(
            allowed=False,
            approval_source="sentinel",
            approval_verdict="deny",
            explanation=verdict.explanation,
            detail=f"[sentinel: deny] {verdict.explanation}",
            final_decision="denied",
            audit_explanation=verdict.explanation,
            sentinel_verdict=verdict,
            rejection=format_denial_message("sentinel", verdict.explanation),
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
        rejection="" if allowed else format_denial_message("user", user_message),
    )


async def _decision_for_usage_limit(
    session: SessionSecurity,
    domain: str,
    command: str,
) -> CachedDomainApproval:
    verdict = _fallback_verdict(
        session,
        explanation=(
            "Automatic sentinel review hit its internal request limit and could not finish. "
            + (
                "The domain request was denied because no user approval path is available."
                if session.unattended
                else "Please approve or deny this domain manually."
            )
        ),
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

    # One exec per scope: its requests share the command.
    any_request = next(iter(snapshot.requests.values()))
    try:
        verdict = await sentinel.evaluate_domain_access(
            session,
            list(domain_commands),
            any_request.command,
            follow_up=all(request.follow_up for request in snapshot.requests.values()),
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


@dataclass(frozen=True, slots=True)
class PushEvaluation:
    allowed: bool
    # What the pushing agent reads in git's output when the push is rejected; empty when allowed.
    rejection: str


async def evaluate_push_with(
    session: SessionSecurity,
    sentinel: Sentinel,
    ref: str,
    is_default_branch: bool,
    commits: str,
    diff: str,
    *,
    shared_artifacts: set[str],
    usage_tracker: UsageTracker | None = None,
    assert_llm_budget_available: Callable[[], None] | None = None,
    usage_limits: UsageLimits | None = None,
) -> PushEvaluation:
    """Evaluate a Git push.

    If the sentinel escalates, delegates to the session's user escalation callback.
    """
    if session.yolo_mode:
        explanation = "YOLO mode bypassed sentinel."
        entry = GitPushEntry(ref=ref, decision="allowed", explanation=explanation)
        session.append(entry)
        await session.notify_push_decision(
            ref,
            "allowed",
            "[bypass] yolo mode auto-allowed",
            approval_source="bypass",
            approval_verdict="allow",
            approval_explanation=explanation,
        )
        session.write_audit(
            AuditEntry.now(
                kind="git_push",
                final_decision="allowed",
                explanation=explanation,
            )
        )
        return PushEvaluation(allowed=True, rejection="")

    if session.ask_mode:
        explanation = "Ask mode blocks git push because it writes outside the sandbox."
        entry = GitPushEntry(ref=ref, decision="denied", explanation=explanation)
        session.append(entry)
        await session.notify_push_decision(
            ref,
            "denied",
            f"[sentinel: deny] {explanation}",
            approval_source="sentinel",
            approval_verdict="deny",
            approval_explanation=explanation,
        )
        session.write_audit(
            AuditEntry.now(
                kind="git_push",
                final_decision="denied",
                explanation=explanation,
            )
        )
        return PushEvaluation(allowed=False, rejection=format_denial_message("sentinel", explanation))

    await session.notify_push_decision(ref, "reviewing", "[sentinel] reviewing", approval_source="sentinel")

    verdict = await sentinel.evaluate_push(
        session,
        ref,
        is_default_branch,
        commits,
        diff,
        shared_artifacts=shared_artifacts,
        usage_tracker=usage_tracker,
        assert_llm_budget_available=assert_llm_budget_available,
        usage_limits=usage_limits,
    )

    if verdict.decision == "escalate" and session.unattended:
        verdict = SentinelVerdict(
            decision="deny",
            explanation=(
                verdict.explanation
                or "The push was denied because no user approval path is available for unattended sessions."
            ),
            risk_level=verdict.risk_level,
        )

    decision = _verdict_to_decision(verdict)
    user_message: str | None = None
    source: ApprovalSource = "sentinel"
    approval_verdict: ApprovalVerdict = verdict.decision

    if verdict.decision == "allow":
        allowed = True
        detail = f"[sentinel: allow] {verdict.explanation}"
        rejection = ""
    elif verdict.decision == "deny":
        allowed = False
        detail = f"[sentinel: deny] {verdict.explanation}"
        rejection = format_denial_message("sentinel", verdict.explanation)
    elif verdict.decision == "revise":
        allowed = False
        detail = f"[sentinel: revise] {verdict.explanation}"
        rejection = format_changes_requested_message(verdict.explanation)
    else:
        changed_files = sorted(touched_paths(diff))
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
        rejection = "" if allowed else format_denial_message("user", user_message)
        detail = rejection or "[user: allow]"
        source = "user"
        approval_verdict = "allow" if allowed else "deny"

    entry = GitPushEntry(ref=ref, decision=decision, explanation=verdict.explanation)
    session.append(entry)
    if verdict.comment:
        session.leave_comment_for_agent(f"the git push to {ref}", verdict.comment)
    await session.notify_push_decision(
        ref,
        decision,
        detail,
        approval_source=source,
        approval_verdict=approval_verdict,
        approval_explanation=verdict.explanation if source == "sentinel" else normalize_optional_message(user_message),
        approval_comment=verdict.comment or None,
    )

    session.write_audit(
        AuditEntry.now(
            kind="git_push",
            sentinel_verdict=verdict,
            final_decision=decision,
            explanation=verdict.explanation,
        )
    )

    return PushEvaluation(allowed=allowed, rejection=rejection)


@dataclass(frozen=True, slots=True)
class CredentialAccessEvaluation:
    """Outcome of a credential request, for the sandbox API that answers ``ccred``."""

    allowed: bool
    """True if access was granted."""

    user_was_prompted: bool
    """True when the sentinel escalated and the user escalation callback ran."""

    explanation: str
    """Sentinel explanation text (same as stored on the audit entry)."""

    rejection: str
    """What ``ccred`` prints on stderr when access was denied; empty when allowed."""


async def evaluate_credential_with(
    session: SessionSecurity,
    sentinel: Sentinel,
    vault_path: str,
    name: str,
    description: str,
    asked_by: str,
    command: str,
    *,
    follow_up: bool,
    usage_tracker: UsageTracker | None = None,
    assert_llm_budget_available: Callable[[], None] | None = None,
    usage_limits: UsageLimits | None = None,
    audit_args: dict[str, Any] | None = None,
) -> CredentialAccessEvaluation:
    """Evaluate a request for a credential value.

    If the sentinel escalates, delegates to the session's user escalation callback.
    """
    return await _evaluate_credential_request(
        session,
        lambda: sentinel.evaluate_credential_access(
            session,
            vault_path,
            name,
            description,
            asked_by,
            command,
            follow_up=follow_up,
            usage_tracker=usage_tracker,
            assert_llm_budget_available=assert_llm_budget_available,
            usage_limits=usage_limits,
        ),
        vault_path=vault_path,
        name=name,
        description=description,
        audit_args=audit_args,
    )


async def evaluate_credential_listing_with(
    session: SessionSecurity,
    sentinel: Sentinel,
    query: str,
    command: str,
    *,
    follow_up: bool,
    usage_tracker: UsageTracker | None = None,
    assert_llm_budget_available: Callable[[], None] | None = None,
    usage_limits: UsageLimits | None = None,
) -> CredentialAccessEvaluation:
    """Evaluate ``ccred list`` / ``ccred search``: they enumerate vault metadata, so they are gated too."""
    return await _evaluate_credential_request(
        session,
        lambda: sentinel.evaluate_credential_listing(
            session,
            query,
            command,
            follow_up=follow_up,
            usage_tracker=usage_tracker,
            assert_llm_budget_available=assert_llm_budget_available,
            usage_limits=usage_limits,
        ),
        vault_path=CREDENTIAL_LISTING_PATH,
        name=f"ccred search {query!r}" if query else "ccred list",
        description="Names, vault paths and descriptions of matching credentials, no values",
        audit_args={"operation": "list", "query": query},
    )


async def _evaluate_credential_request(
    session: SessionSecurity,
    review: Callable[[], Awaitable[SentinelVerdict]],
    *,
    vault_path: str,
    name: str,
    description: str,
    audit_args: dict[str, Any] | None,
) -> CredentialAccessEvaluation:
    if session.yolo_mode:
        explanation = "YOLO mode bypassed sentinel."
        session.record_credential_access(
            vault_paths=[vault_path],
            names=[name],
            decision="approved",
            explanation=explanation,
            ui_label="[bypass] yolo mode auto-allowed",
            approval_source="bypass",
            approval_verdict="allow",
            ui_explanation=explanation,
            audit_final="allowed",
            audit_args=audit_args,
            sentinel_verdict=None,
        )
        return CredentialAccessEvaluation(
            allowed=True,
            user_was_prompted=False,
            explanation=explanation,
            rejection="",
        )

    session.notify_credential_review(vault_path, "[sentinel] reviewing", name=name, approval_source="sentinel")

    outcome = await _decide_boundary_request(
        session,
        await review(),
        subject=vault_path,
        what="credential access",
        items=_AccessItems(vault_paths=[vault_path], names=[name], descriptions=[description], domains=[]),
    )
    _record_credential_outcome(session, outcome, vault_path=vault_path, name=name, audit_args=audit_args)
    return CredentialAccessEvaluation(
        allowed=outcome.allowed,
        user_was_prompted=outcome.source == "user",
        explanation=outcome.verdict.explanation,
        rejection=outcome.rejection,
    )


async def evaluate_upfront_request_with(
    session: SessionSecurity,
    sentinel: Sentinel,
    request: UpfrontRequest,
    command: str,
    *,
    follow_up: bool,
    usage_tracker: UsageTracker | None = None,
    assert_llm_budget_available: Callable[[], None] | None = None,
    usage_limits: UsageLimits | None = None,
) -> BoundaryEvaluation:
    """Evaluate what a command declared with ``cgate request``: one decision for all of it.

    The declaration only bundles requests and carries no trust; the sentinel judges it like the single requests.
    """
    if session.yolo_mode:
        outcome = _BoundaryOutcome(
            verdict=SentinelVerdict(decision="allow", explanation="YOLO mode bypassed sentinel."),
            allowed=True,
            source="bypass",
            detail="[bypass] yolo mode auto-allowed",
            rejection="",
            ui_explanation="YOLO mode bypassed sentinel.",
        )
    else:
        for domain in request.domains:
            session.notify_domain_decision(domain, "[sentinel] reviewing", approval_source="sentinel")
        for credential in request.credentials:
            session.notify_credential_review(
                credential.vault_path, "[sentinel] reviewing", name=credential.name, approval_source="sentinel"
            )
        verdict = await sentinel.evaluate_upfront_request(
            session,
            request,
            command,
            follow_up=follow_up,
            usage_tracker=usage_tracker,
            assert_llm_budget_available=assert_llm_budget_available,
            usage_limits=usage_limits,
        )
        outcome = await _decide_boundary_request(
            session,
            verdict,
            subject=", ".join([*request.domains, *(c.vault_path for c in request.credentials)]),
            what="the up-front request",
            items=_AccessItems(
                vault_paths=[c.vault_path for c in request.credentials],
                names=[c.name for c in request.credentials],
                descriptions=[c.description for c in request.credentials],
                domains=request.domains,
            ),
        )

    for domain in request.domains:
        session.notify_domain_decision(
            domain,
            outcome.detail,
            approval_source=outcome.source,
            approval_verdict="allow" if outcome.allowed else "deny",
            approval_explanation=outcome.ui_explanation,
        )
        session.write_audit(
            AuditEntry.now(
                kind="proxy_domain",
                domain=domain,
                sentinel_verdict=outcome.verdict if outcome.source != "bypass" else None,
                final_decision="allowed" if outcome.allowed else "denied",
                explanation=outcome.verdict.explanation,
            )
        )
    for credential in request.credentials:
        _record_credential_outcome(
            session,
            outcome,
            vault_path=credential.vault_path,
            name=credential.name,
            audit_args={"operation": "upfront_request", "vault_path": credential.vault_path},
        )
    return BoundaryEvaluation(allowed=outcome.allowed, rejection=outcome.rejection)


@dataclass(frozen=True, slots=True)
class _AccessItems:
    """What an escalated boundary request shows the user, in the shape of a credential approval request."""

    vault_paths: list[str]
    names: list[str]
    descriptions: list[str]
    domains: list[str]


@dataclass(frozen=True, slots=True, kw_only=True)
class _BoundaryOutcome:
    verdict: SentinelVerdict
    allowed: bool
    source: ApprovalSource
    detail: str
    rejection: str
    ui_explanation: str | None


async def _decide_boundary_request(
    session: SessionSecurity,
    verdict: SentinelVerdict,
    *,
    subject: str,
    what: str,
    items: _AccessItems,
) -> _BoundaryOutcome:
    """Turn the sentinel's verdict on a credential or up-front request into the final decision, asking the user."""
    if verdict.decision == "escalate" and session.unattended:
        verdict = SentinelVerdict(
            decision="deny",
            explanation=(
                verdict.explanation
                or f"Denied {what} because no user approval path is available for unattended sessions."
            ),
            risk_level=verdict.risk_level,
        )

    match verdict.decision:
        case "allow":
            detail = f"[sentinel: allow] {verdict.explanation}"
            return _BoundaryOutcome(
                verdict=verdict,
                allowed=True,
                source="sentinel",
                detail=detail,
                rejection="",
                ui_explanation=verdict.explanation,
            )
        case "deny":
            detail = f"[sentinel: deny] {verdict.explanation}"
            rejection = format_denial_message("sentinel", verdict.explanation)
            return _BoundaryOutcome(
                verdict=verdict,
                allowed=False,
                source="sentinel",
                detail=detail,
                rejection=rejection,
                ui_explanation=verdict.explanation,
            )
        case "escalate":
            user_decision = await session.escalate_to_user(
                subject,
                {
                    "kind": "credential_access",
                    "vault_path": subject,
                    "vault_paths": items.vault_paths,
                    "names": items.names,
                    "descriptions": items.descriptions,
                    "domains": items.domains,
                    "explanation": verdict.explanation,
                },
            )
            message = normalize_optional_message(user_decision.message)
            rejection = "" if user_decision.allowed else format_denial_message("user", message)
            return _BoundaryOutcome(
                verdict=verdict,
                allowed=user_decision.allowed,
                source="user",
                detail=rejection or "[user: allow]",
                rejection=rejection,
                ui_explanation=message,
            )
        case "revise":
            raise _revise_not_offered(what)


def _record_credential_outcome(
    session: SessionSecurity,
    outcome: _BoundaryOutcome,
    *,
    vault_path: str,
    name: str,
    audit_args: dict[str, Any] | None,
) -> None:
    session.record_credential_access(
        vault_paths=[vault_path],
        names=[name],
        decision="approved" if outcome.allowed else "denied",
        explanation=outcome.verdict.explanation,
        ui_label=outcome.detail,
        approval_source=outcome.source,
        approval_verdict="allow" if outcome.allowed else "deny",
        ui_explanation=outcome.ui_explanation,
        audit_final="allowed" if outcome.allowed else "denied",
        audit_args=audit_args,
        sentinel_verdict=outcome.verdict if outcome.source != "bypass" else None,
    )


def _verdict_to_decision(verdict: SentinelVerdict) -> Literal["allowed", "changes_requested", "escalated", "denied"]:
    match verdict.decision:
        case "allow":
            return "allowed"
        case "revise":
            return "changes_requested"
        case "escalate":
            return "escalated"
        case "deny":
            return "denied"


def _revise_not_offered(kind: str) -> RuntimeError:
    # The sentinel's output validator rejects `revise` where the agent never reads the explanation.
    return RuntimeError(f"Sentinel returned `revise` for {kind}, where it is not offered.")


def _log_tool_call(
    tool_name: str,
    args: dict[str, Any],
    detail: str,
    callback: Any = None,
    approval_source: ApprovalSource | None = None,
    approval_verdict: ApprovalVerdict | None = None,
    approval_explanation: str | None = None,
    *,
    tool_call_id: str | None,
    approval_comment: str | None = None,
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
        callback(
            tool_name,
            args,
            detail,
            approval_source,
            approval_verdict,
            approval_explanation,
            tool_call_id,
            approval_comment,
        )
    else:
        print(f"  \033[2m{tool_name}({args_str}) {detail}\033[0m")
