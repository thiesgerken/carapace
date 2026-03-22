from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

SLASH_COMMANDS: list[dict[str, str]] = [
    {"command": "/security", "description": "Show security policy summary"},
    {"command": "/approve-context", "description": "Vouch for the current agent context as trustworthy"},
    {"command": "/session", "description": "Show current session state"},
    {"command": "/skills", "description": "List available skills"},
    {"command": "/memory", "description": "List memory files"},
    {"command": "/pull", "description": "Pull from external Git remote (if configured)"},
    {"command": "/push", "description": "Push to external Git remote (if configured)"},
    {
        "command": "/models",
        "description": "View all models and available options",
    },
    {"command": "/model", "description": "View or switch the agent model (e.g. /model openai:gpt-4o)"},
    {"command": "/model-sentinel", "description": "View or switch the sentinel model"},
    {"command": "/model-title", "description": "View or switch the title model"},
    {"command": "/usage", "description": "Show token usage for this session"},
    {"command": "/verbose", "description": "Toggle tool call display"},
    {"command": "/quit", "description": "Disconnect"},
    {"command": "/help", "description": "Show this help"},
]

# --- Client → Server ---


class UserMessage(BaseModel):
    type: Literal["message"] = "message"
    content: str


class ApprovalResponse(BaseModel):
    type: Literal["approval_response"] = "approval_response"
    tool_call_id: str
    approved: bool


DomainDecision = Literal["allow", "deny"]


class ProxyApprovalResponse(BaseModel):
    """Client → Server: user's decision for a proxy domain approval request."""

    type: Literal["proxy_approval_response"] = "proxy_approval_response"
    request_id: str
    decision: DomainDecision


class CancelRequest(BaseModel):
    """Client → Server: cancel the in-flight agent turn."""

    type: Literal["cancel"] = "cancel"


ClientEnvelope = UserMessage | ApprovalResponse | ProxyApprovalResponse | CancelRequest


def parse_client_message(raw: dict[str, Any]) -> ClientEnvelope:
    match raw.get("type"):
        case "message":
            return UserMessage.model_validate(raw)
        case "approval_response":
            return ApprovalResponse.model_validate(raw)
        case "proxy_approval_response":
            return ProxyApprovalResponse.model_validate(raw)
        case "cancel":
            return CancelRequest.model_validate(raw)
        case other:
            msg = f"Unknown client message type: {other}"
            raise ValueError(msg)


# --- Server → Client ---


class TokenChunk(BaseModel):
    type: Literal["token"] = "token"
    content: str


class ToolCallInfo(BaseModel):
    type: Literal["tool_call"] = "tool_call"
    tool: str
    args: dict[str, Any]
    detail: str


class ToolResultInfo(BaseModel):
    type: Literal["tool_result"] = "tool_result"
    tool: str
    result: str


class ApprovalRequest(BaseModel):
    type: Literal["approval_request"] = "approval_request"
    tool_call_id: str
    tool: str
    args: dict[str, Any]
    explanation: str = ""
    risk_level: str = ""


class ProxyApprovalRequest(BaseModel):
    """Server → Client: proxy is waiting for a domain access decision."""

    type: Literal["proxy_approval_request"] = "proxy_approval_request"
    request_id: str
    domain: str
    command: str  # the exec command that triggered this connection attempt
    kind: Literal["proxy_domain", "git_push"] = "proxy_domain"


class TurnUsage(BaseModel):
    """Token counts from the last LLM request of a turn."""

    input_tokens: int = 0
    output_tokens: int = 0


class Done(BaseModel):
    type: Literal["done"] = "done"
    content: str
    usage: TurnUsage | None = None


class CommandResult(BaseModel):
    type: Literal["command_result"] = "command_result"
    command: str
    data: Any


class ErrorMessage(BaseModel):
    type: Literal["error"] = "error"
    detail: str


class Cancelled(BaseModel):
    """Server → Client: confirms that the agent turn was cancelled."""

    type: Literal["cancelled"] = "cancelled"
    detail: str = "Agent cancelled."


class SessionTitleUpdate(BaseModel):
    """Server → Client: updated session title."""

    type: Literal["session_title"] = "session_title"
    title: str


class StatusUpdate(BaseModel):
    """Server → Client: session status on connect."""

    type: Literal["status"] = "status"
    agent_running: bool
    usage: TurnUsage | None = None


class UserMessageNotification(BaseModel):
    """Server → Client: a user message arrived (from another channel)."""

    type: Literal["user_message"] = "user_message"
    content: str


ServerEnvelope = (
    TokenChunk
    | ToolCallInfo
    | ToolResultInfo
    | ApprovalRequest
    | ProxyApprovalRequest
    | Done
    | CommandResult
    | ErrorMessage
    | Cancelled
    | SessionTitleUpdate
    | StatusUpdate
    | UserMessageNotification
)
