"""Find approval requests in a session event log that never got a decision, and close them.

A request is only answerable while the turn (or the escalation callback) that asked it is
still waiting. Once that waiter is gone, an unanswered request would stay actionable in the
UI forever, so it gets closed with a system denial in the same shape a user denial has.
"""

from __future__ import annotations

from typing import Any, Literal

ApprovalDecisionSource = Literal["user", "system"]

ORPHANED_APPROVAL_MESSAGE = "Turn ended before a decision was made."

TOOL_APPROVAL_REQUEST_ROLE = "approval_request"
TOOL_APPROVAL_RESPONSE_ROLE = "approval_response"

# Escalation requests and their responses share a role; a response is the event that carries
# a ``decision``. Values name the request fields each kind's response event repeats.
# ``proxy_approval`` is the legacy role of domain access escalations in older sessions.
ESCALATION_RESPONSE_FIELDS: dict[str, tuple[str, ...]] = {
    "domain_access_approval": ("domain", "command"),
    "proxy_approval": ("domain", "command"),
    "git_push_approval": ("ref",),
    "credential_approval": ("vault_paths",),
}


def closing_events_for_open_approvals(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return a system denial for every approval request in *events* without a response."""
    answered_tool_calls = {
        event.get("tool_call_id") for event in events if event.get("role") == TOOL_APPROVAL_RESPONSE_ROLE
    }
    answered_escalations = {
        event.get("request_id")
        for event in events
        if event.get("role") in ESCALATION_RESPONSE_FIELDS and event.get("decision") is not None
    }

    closing: list[dict[str, Any]] = []
    for event in events:
        role = event.get("role")
        if role == TOOL_APPROVAL_REQUEST_ROLE and event["tool_call_id"] not in answered_tool_calls:
            closing.append(
                {
                    "role": TOOL_APPROVAL_RESPONSE_ROLE,
                    "tool_call_id": event["tool_call_id"],
                    "decision": "denied",
                    "decision_source": "system",
                    "message": ORPHANED_APPROVAL_MESSAGE,
                }
            )
        elif (
            role in ESCALATION_RESPONSE_FIELDS
            and event.get("decision") is None
            and event["request_id"] not in answered_escalations
        ):
            closing.append(
                {
                    "role": role,
                    "request_id": event["request_id"],
                    **{field: event[field] for field in ESCALATION_RESPONSE_FIELDS[role]},
                    "decision": "deny",
                    "decision_source": "system",
                    "message": ORPHANED_APPROVAL_MESSAGE,
                }
            )
    return closing
