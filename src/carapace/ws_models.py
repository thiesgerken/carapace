from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

from .models.session import SessionBudget
from .models.tooling import SentFileInfo
from .security.context import ApprovalSource, ApprovalVerdict
from .usage import BudgetGauge, LlmRequestPhase, LlmSource

FinalStatus = Literal["success", "warning"]

SLASH_COMMANDS: list[dict[str, str]] = [
    {"command": "/session", "description": "Show current session state"},
    {"command": "/skills", "description": "List available skills"},
    {
        "command": "/retitle",
        "description": "Regenerate session title, or set it: /retitle My title",
    },
    {"command": "/reload", "description": "Reset sandbox (delete container + workspace, fresh git clone)"},
    {
        "command": "/models",
        "description": "View all models and available options",
    },
    {
        "command": "/model",
        "description": "View models, switch all with /model all NAME, or target one role "
        + "(agent/sentinel/title/compaction) with /model sentinel NAME",
    },
    {
        "command": "/budget",
        "description": "Show current budgets. Set with /budget input N, /budget output N, "
        + "/budget cost N, or /budget tools N",
    },
    {"command": "/usage", "description": "Show token usage for this session"},
    {
        "command": "/compact",
        "description": "Compact history to save context. /compact [K], /compact fold [K], or /compact tools [N]",
    },
    {
        "command": "/uncompact",
        "description": "Undo compaction: rebuild the full history from the transcript (debug aid)",
    },
    {"command": "/quit", "description": "Disconnect"},
    {"command": "/help", "description": "Show this help"},
]

# --- Client → Server ---


class Attachment(BaseModel):
    """A file the user uploaded into the sandbox before sending a message.

    ``file_id``/``size``/``mime`` are populated once the upload is persisted
    server-side (so it stays viewable/downloadable after the sandbox is gone).
    """

    name: str
    path: str
    file_id: str | None = None
    size: int | None = None
    mime: str | None = None


class UserMessage(BaseModel):
    type: Literal["message"] = "message"
    content: str
    attachments: list[Attachment] = []


class ApprovalResponse(BaseModel):
    type: Literal["approval_response"] = "approval_response"
    tool_call_id: str
    approved: bool
    message: str | None = None


EscalationDecision = Literal["allow", "deny"]


class EscalationResponse(BaseModel):
    """Client → Server: user's decision on a sentinel escalation (proxy domain or git push)."""

    type: Literal["escalation_response"] = "escalation_response"
    request_id: str
    decision: EscalationDecision
    message: str | None = None


class CancelRequest(BaseModel):
    """Client → Server: cancel the in-flight agent turn."""

    type: Literal["cancel"] = "cancel"


class RetryLatestTurnRequest(BaseModel):
    """Client → Server: rewind the latest completed turn and run it again."""

    type: Literal["retry_latest_turn"] = "retry_latest_turn"


class ResetToTurnRequest(BaseModel):
    """Client → Server: rewind session chat state to a completed turn boundary."""

    type: Literal["reset_to_turn"] = "reset_to_turn"
    event_index: int


ClientEnvelope = (
    UserMessage | ApprovalResponse | EscalationResponse | CancelRequest | RetryLatestTurnRequest | ResetToTurnRequest
)


def parse_client_message(raw: dict[str, Any]) -> ClientEnvelope:
    match raw.get("type"):
        case "message":
            return UserMessage.model_validate(raw)
        case "approval_response":
            return ApprovalResponse.model_validate(raw)
        case "escalation_response":
            return EscalationResponse.model_validate(raw)
        case "cancel":
            return CancelRequest.model_validate(raw)
        case "retry_latest_turn":
            return RetryLatestTurnRequest.model_validate(raw)
        case "reset_to_turn":
            return ResetToTurnRequest.model_validate(raw)
        case other:
            msg = f"Unknown client message type: {other}"
            raise ValueError(msg)


# --- Server → Client ---


class TokenChunk(BaseModel):
    type: Literal["token"] = "token"
    content: str


class ThinkingChunk(BaseModel):
    type: Literal["thinking"] = "thinking"
    content: str


class ToolCallInfo(BaseModel):
    type: Literal["tool_call"] = "tool_call"
    tool: str
    args: dict[str, Any]
    detail: str
    contexts: list[str] = []
    approval_source: ApprovalSource | None = None
    approval_verdict: ApprovalVerdict | None = None
    approval_explanation: str | None = None
    tool_id: str | None = None
    parent_tool_id: str | None = None


class ToolResultInfo(BaseModel):
    type: Literal["tool_result"] = "tool_result"
    tool: str
    result: str
    exit_code: int = 0
    tool_id: str | None = None
    files: list[SentFileInfo] | None = None


class ApprovalRequest(BaseModel):
    type: Literal["approval_request"] = "approval_request"
    tool_call_id: str
    tool: str
    args: dict[str, Any]
    explanation: str = ""
    risk_level: str = ""


class DomainAccessApprovalRequest(BaseModel):
    """Server → Client: sentinel is waiting for a domain access decision."""

    type: Literal["domain_access_approval_request"] = "domain_access_approval_request"
    request_id: str
    domain: str
    command: str  # the exec command that triggered this connection attempt


class GitPushApprovalRequest(BaseModel):
    """Server → Client: sentinel is waiting for a git push decision."""

    type: Literal["git_push_approval_request"] = "git_push_approval_request"
    request_id: str
    ref: str
    explanation: str
    changed_files: list[str]


class CredentialApprovalRequest(BaseModel):
    """Server → Client: sentinel escalated a credential access request to the user."""

    type: Literal["credential_approval_request"] = "credential_approval_request"
    request_id: str
    vault_paths: list[str]
    names: list[str]
    descriptions: list[str]
    skill_name: str | None = None
    explanation: str = ""


class TurnUsageBreakdownPct(BaseModel):
    """Tiktoken prompt-mix percents for the last agent request (sum 100)."""

    system: float
    user: float
    assistant: float
    tool_calls: float
    tool_returns: float
    other: float


class LlmActivity(BaseModel):
    request_id: str
    source: LlmSource
    model: str | None = None
    phase: LlmRequestPhase
    started_at: datetime
    first_thinking_at: datetime | None = None
    last_thinking_at: datetime | None = None
    first_text_at: datetime | None = None


class TurnUsage(BaseModel):
    """Token counts from the last LLM request of a turn."""

    input_tokens: int = 0
    output_tokens: int = 0
    breakdown_pct: TurnUsageBreakdownPct | None = None
    model: str | None = None
    context_cap_tokens: int | None = None
    ttft_ms: int | None = None
    total_duration_ms: int | None = None
    reasoning_duration_ms: int | None = None
    reasoning_tokens: int | None = None
    started_at: datetime | None = None
    first_thinking_at: datetime | None = None
    last_thinking_at: datetime | None = None
    first_text_at: datetime | None = None
    completed_at: datetime | None = None
    budget_gauges: list[BudgetGauge] = []


class Done(BaseModel):
    type: Literal["done"] = "done"
    content: str
    thinking: str | None = None
    usage: TurnUsage | None = None
    final_status: FinalStatus | None = None


class CommandResult(BaseModel):
    type: Literal["command_result"] = "command_result"
    command: str
    data: Any


class ErrorMessage(BaseModel):
    type: Literal["error"] = "error"
    detail: str
    turn_terminal: bool = False


class Cancelled(BaseModel):
    """Server → Client: confirms that the agent turn was cancelled."""

    type: Literal["cancelled"] = "cancelled"
    detail: str = "Agent cancelled."


class SessionTitleUpdate(BaseModel):
    """Server → Client: updated session title."""

    type: Literal["session_title"] = "session_title"
    title: str
    usage: TurnUsage | None = None


class LlmActivityUpdate(BaseModel):
    """Server → Client: current in-flight LLM activity changed."""

    type: Literal["llm_activity"] = "llm_activity"
    activity: LlmActivity | None = None


class StatusUpdate(BaseModel):
    """Server → Client: session status on connect and after a budget change.

    ``usage`` carries the last agent-turn usage for the context bar and the budget gauges, ``budget`` the
    limits themselves, so every client's session drawer follows ``/budget`` and edits from other clients.
    """

    type: Literal["status"] = "status"
    agent_running: bool
    usage: TurnUsage | None = None
    llm_activity: LlmActivity | None = None
    budget: SessionBudget


class UserMessageNotification(BaseModel):
    """Server → Client: a user message arrived (from another channel)."""

    type: Literal["user_message"] = "user_message"
    content: str
    attachments: list[Attachment] = []


ServerEnvelope = (
    TokenChunk
    | ThinkingChunk
    | ToolCallInfo
    | ToolResultInfo
    | ApprovalRequest
    | DomainAccessApprovalRequest
    | GitPushApprovalRequest
    | CredentialApprovalRequest
    | Done
    | CommandResult
    | ErrorMessage
    | Cancelled
    | SessionTitleUpdate
    | LlmActivityUpdate
    | StatusUpdate
    | UserMessageNotification
)
