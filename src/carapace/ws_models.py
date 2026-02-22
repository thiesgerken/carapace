from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

# --- Client → Server ---


class UserMessage(BaseModel):
    type: Literal["message"] = "message"
    content: str


class ApprovalResponse(BaseModel):
    type: Literal["approval_response"] = "approval_response"
    tool_call_id: str
    approved: bool


class ProxyApprovalResponse(BaseModel):
    """Client → Server: user's decision for a proxy domain approval request."""

    type: Literal["proxy_approval_response"] = "proxy_approval_response"
    request_id: str
    decision: Literal["allow_once", "allow_all_once", "allow_15min", "allow_all_15min", "deny"]


ClientEnvelope = UserMessage | ApprovalResponse | ProxyApprovalResponse


def parse_client_message(raw: dict[str, Any]) -> ClientEnvelope:
    match raw.get("type"):
        case "message":
            return UserMessage.model_validate(raw)
        case "approval_response":
            return ApprovalResponse.model_validate(raw)
        case "proxy_approval_response":
            return ProxyApprovalResponse.model_validate(raw)
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


class ApprovalRequest(BaseModel):
    type: Literal["approval_request"] = "approval_request"
    tool_call_id: str
    tool: str
    args: dict[str, Any]
    classification: dict[str, Any]
    triggered_rules: list[str]
    descriptions: list[str]


class ProxyApprovalRequest(BaseModel):
    """Server → Client: proxy is waiting for a domain access decision."""

    type: Literal["proxy_approval_request"] = "proxy_approval_request"
    request_id: str
    domain: str
    command: str  # the exec command that triggered this connection attempt


class Done(BaseModel):
    type: Literal["done"] = "done"
    content: str


class CommandResult(BaseModel):
    type: Literal["command_result"] = "command_result"
    command: str
    data: Any


class ErrorMessage(BaseModel):
    type: Literal["error"] = "error"
    detail: str


ServerEnvelope = (
    TokenChunk | ToolCallInfo | ApprovalRequest | ProxyApprovalRequest | Done | CommandResult | ErrorMessage
)
