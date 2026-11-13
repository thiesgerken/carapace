from __future__ import annotations

from typing import Annotated, Any, Literal, Self

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, model_validator
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    ThinkingPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from ..api_keys import Access, Scope
from ..auth import UserIdentity
from ..models.tooling import SentFileInfo, normalize_tool_call_args
from ..security.context import ApprovalSource, ApprovalVerdict
from ..session.compaction import tool_return_is_compacted
from ..session.open_approvals import ApprovalDecisionSource
from ..usage import LlmContext, LlmRequestRecord
from ..ws_models import Attachment, FinalStatus
from .auth import require
from .state import server_module

server = server_module()

router = APIRouter()

# ``memory`` is not bound to a session, so it never has a session LLM context.
DebugRole = Literal["agent", "sentinel", "titler", "compaction"]

_HistoryRole = Literal[
    "user",
    "assistant",
    "error",
    "thinking",
    "tool_call",
    "tool_result",
    "command",
    "proxy_approval",
    "domain_access_approval",
    "approval_request",
    "approval_response",
    "git_push",
    "git_push_approval",
    "credential_approval",
    "compaction",
]


class HistoryMessage(BaseModel):
    role: _HistoryRole
    content: str = ""
    final_status: FinalStatus | None = None
    event_index: int | None = None
    timestamp: str | None = None
    usage: dict[str, Any] | None = None
    partial: bool | None = None
    reasoning_duration_ms: int | None = None
    reasoning_tokens: int | None = None
    tool: str | None = None
    args: dict[str, Any] | None = None
    detail: str | None = None
    contexts: list[str] | None = None
    approval_source: ApprovalSource | None = None
    approval_verdict: ApprovalVerdict | None = None
    approval_explanation: str | None = None
    result: str | None = None
    command: str | None = None
    data: Any = None
    request_id: str | None = None
    domain: str | None = None
    decision: str | None = None
    tool_call_id: str | None = None
    decision_source: ApprovalDecisionSource | None = None
    message: str | None = None
    explanation: str | None = None
    risk_level: str | None = None
    ref: str | None = None
    changed_files: list[str] | None = None
    vault_paths: list[str] | None = None
    names: list[str] | None = None
    descriptions: list[str] | None = None
    skill_name: str | None = None
    tool_id: str | None = None
    model_tool_call_id: str | None = None
    parent_tool_id: str | None = None
    exit_code: int | None = None
    attachments: list[Attachment] | None = None
    files: list[SentFileInfo] | None = None
    # Compaction annotation: {folded_into: node_id} on folded events, or
    # {orig_tokens, summary_tokens} on a compacted tool_result.
    compaction: dict[str, Any] | None = None
    # A provider-side compaction event: who compacted, and its readable summary if the provider has one.
    provider: str | None = None
    summary: str | None = None
    # Set instead of a summary when the provider failed to compact: why, and that carapace compacted locally.
    failed: str | None = None
    # With ``failed``: the provider refused the setting, so the model compacts locally from now on.
    rejected: bool | None = None

    @model_validator(mode="after")
    def _contexts_from_args_when_missing(self) -> Self:
        """Legacy events only stored contexts inside ``args``; expose them top-level."""
        if self.role != "tool_call" or self.contexts is not None:
            return self
        raw = self.args.get("contexts") if self.args else None
        if isinstance(raw, list):
            return self.model_copy(update={"contexts": list(raw)})
        return self


@router.get("/sessions/{session_id}/history", response_model=list[HistoryMessage], response_model_exclude_none=True)
async def get_session_history(
    session_id: str,
    user: Annotated[UserIdentity, Depends(require(Scope.history, Access.read))],
    limit: Annotated[int, Query()] = -1,
) -> list[HistoryMessage]:
    _require_owned_session(session_id, user)

    events = server._engine.session_mgr.load_events(session_id)
    result = (
        [
            HistoryMessage.model_validate(
                {
                    **event,
                    "args": normalize_tool_call_args(event.get("tool", ""), event["args"])
                    if isinstance(event.get("args"), dict)
                    else event.get("args"),
                    "event_index": index,
                }
            )
            for index, event in enumerate(events)
        ]
        if events
        else [
            HistoryMessage.model_validate({**message.model_dump(mode="python"), "event_index": index})
            for index, message in enumerate(_history_from_messages(session_id))
        ]
    )

    _enrich_compaction_annotations(session_id, result)

    if limit > 0:
        result = result[-limit:]
    return result


def _enrich_compaction_annotations(session_id: str, messages: list[HistoryMessage]) -> None:
    """Fold/tool annotations carry only ids + token counts; attach the model-facing summary text.

    Lets the main (uncompacted) view show, inline and on demand, exactly what the model sees for a
    folded run (the node summary) or a compacted tool output (the shortened return).
    """
    if not any(m.compaction for m in messages):
        return

    tree = server._engine.session_mgr.load_compaction(session_id)
    nodes = {n.id: n for n in tree.nodes}
    # Folds roll: the model sees only the newest summary, for every folded event alike.
    newest = tree.nodes[-1] if tree.nodes else None
    model_tool_text: dict[str, str] = {}
    for msg in server._engine.session_mgr.load_history(session_id):
        if not isinstance(msg, ModelRequest):
            continue
        for part in msg.parts:
            if isinstance(part, ToolReturnPart) and part.tool_call_id and tool_return_is_compacted(part):
                model_tool_text[part.tool_call_id] = (
                    part.content if isinstance(part.content, str) else str(part.content)
                )

    for m in messages:
        if not m.compaction:
            continue
        ann = dict(m.compaction)
        node_id = ann.get("folded_into")
        if isinstance(node_id, str) and node_id in nodes and newest is not None:
            ann |= {
                "folded_into": newest.id,
                "summary": newest.summary,
                "orig_tokens": newest.orig_tokens,
                "summary_tokens": newest.summary_tokens,
            }
        tool_key = m.model_tool_call_id or m.tool_id
        if m.role == "tool_result" and isinstance(tool_key, str) and (text := model_tool_text.get(tool_key)):
            ann.setdefault("model_text", text)
        m.compaction = ann


@router.get("/sessions/{session_id}/llm-contexts/{role}", response_model=LlmContext | None)
async def get_llm_context(
    session_id: str,
    role: DebugRole,
    user: Annotated[UserIdentity, Depends(require(Scope.history, Access.read))],
) -> LlmContext | None:
    """The latest LLM context of *role* in the session, for the debug view; null before its first request."""
    _require_owned_session(session_id, user)
    return server._engine.session_mgr.load_llm_context(session_id, role)


@router.get("/sessions/{session_id}/llm-requests", response_model=list[LlmRequestRecord])
async def list_llm_requests(
    session_id: str,
    user: Annotated[UserIdentity, Depends(require(Scope.history, Access.read))],
    role: DebugRole | None = None,
) -> list[LlmRequestRecord]:
    """The session's recorded LLM requests in order, optionally of one *role*, for the debug view's timeline."""
    _require_owned_session(session_id, user)
    records = server._engine.session_mgr.load_llm_request_log(session_id).records
    return [r for r in records if role is None or r.source == role]


def _require_owned_session(session_id: str, user: UserIdentity) -> None:
    if server._engine.session_mgr.load_state(session_id) is None or not server._engine.session_mgr.is_owned_by(
        session_id, user.username
    ):
        raise HTTPException(status_code=404, detail="Session not found")


def _history_from_messages(session_id: str) -> list[HistoryMessage]:
    """Fallback: build history from Pydantic AI messages for sessions without events."""
    raw_messages = server._engine.session_mgr.load_history(session_id)
    result: list[HistoryMessage] = []
    for msg in raw_messages:
        if isinstance(msg, ModelRequest):
            for part in msg.parts:
                if isinstance(part, UserPromptPart) and isinstance(part.content, str):
                    result.append(HistoryMessage(role="user", content=part.content))
        elif isinstance(msg, ModelResponse):
            for part in msg.parts:
                if isinstance(part, ToolCallPart):
                    args = normalize_tool_call_args(part.tool_name, part.args) if isinstance(part.args, dict) else {}
                    ctx_raw = args.get("contexts")
                    contexts = list(ctx_raw) if isinstance(ctx_raw, list) else None
                    result.append(
                        HistoryMessage(
                            role="tool_call",
                            content="",
                            tool=part.tool_name,
                            args=args,
                            contexts=contexts,
                        )
                    )
                elif isinstance(part, TextPart):
                    result.append(HistoryMessage(role="assistant", content=part.content))
                elif isinstance(part, ThinkingPart) and part.content:
                    result.append(HistoryMessage(role="thinking", content=part.content))
    return result
