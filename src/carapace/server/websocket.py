from __future__ import annotations

import contextlib
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from loguru import logger
from pydantic import BaseModel

from ..api_keys import Access, Scope
from ..auth import UserIdentity
from ..models.session import SessionBudget
from ..models.tooling import ToolResult, normalize_tool_call_args
from ..notifications.models import NotificationClientType
from ..notifications.vapid import derive_vapid_public_key
from ..security.context import ApprovalSource, ApprovalVerdict
from ..usage import LlmRequestState
from ..ws_models import (
    SLASH_COMMANDS,
    ApprovalRequest,
    ApprovalResponse,
    Cancelled,
    CancelRequest,
    CommandResult,
    CredentialApprovalRequest,
    DomainAccessApprovalRequest,
    Done,
    ErrorMessage,
    EscalationResponse,
    FinalStatus,
    GitPushApprovalRequest,
    LlmActivity,
    LlmActivityUpdate,
    ResetToTurnRequest,
    RetryLatestTurnRequest,
    ServerEnvelope,
    SessionTitleUpdate,
    StatusUpdate,
    ThinkingChunk,
    TokenChunk,
    ToolCallInfo,
    ToolResultInfo,
    TurnUsage,
    UserMessage,
    UserMessageNotification,
    parse_client_message,
)
from .auth import require, verify_ws_token
from .notifications import _set_notification_presence
from .state import server_module

server = server_module()

router = APIRouter()


class ServerMeta(BaseModel):
    version: str


class VapidPublicKeyResponse(BaseModel):
    vapid_public_key: str


async def _send(ws: WebSocket, msg: ServerEnvelope) -> None:
    await ws.send_json(msg.model_dump(mode="json"))


def _llm_activity_payload(activity: LlmRequestState | None) -> LlmActivity | None:
    if activity is None:
        return None
    return LlmActivity(
        request_id=activity.request_id,
        source=activity.source,
        model=activity.model_name,
        phase=activity.phase,
        started_at=activity.started_at,
        first_thinking_at=activity.first_thinking_at,
        last_thinking_at=activity.last_thinking_at,
        first_text_at=activity.first_text_at,
    )


@router.get("/commands")
async def list_commands(
    _user: Annotated[UserIdentity, Depends(require(Scope.sessions, Access.read))],
) -> list[dict[str, str]]:
    return SLASH_COMMANDS


@router.get("/meta", response_model=ServerMeta)
async def get_meta(_user: Annotated[UserIdentity, Depends(require(Scope.sessions, Access.read))]) -> ServerMeta:
    return ServerMeta(version=server._APP_VERSION)


@router.get("/config/vapid-public-key", response_model=VapidPublicKeyResponse)
async def get_vapid_public_key() -> VapidPublicKeyResponse:
    vapid_private_key = server._config.notifications.vapid_private_key
    assert vapid_private_key is not None
    vapid_public_key = derive_vapid_public_key(vapid_private_key)
    return VapidPublicKeyResponse(vapid_public_key=vapid_public_key)


@router.get("/models")
async def list_models(
    _user: Annotated[UserIdentity, Depends(require(Scope.sessions, Access.read))],
) -> list[dict[str, Any]]:
    return [e.model_dump(mode="json", by_alias=True) for e in server._engine.enabled_model_entries]


class WebSocketSubscriber:
    """Thin adapter: forwards ``SessionEngine`` events to a WebSocket."""

    def __init__(self, ws: WebSocket) -> None:
        self._ws = ws

    async def _safe_send(self, msg: ServerEnvelope) -> None:
        try:
            await _send(self._ws, msg)
        except Exception as exc:
            logger.warning(f"WebSocket send failed: {exc}")

    async def on_user_message(self, content: str, *, from_self: bool, attachments: list[Any] | None = None) -> None:
        await self._safe_send(UserMessageNotification(content=content, attachments=list(attachments or [])))

    async def on_tool_call(
        self,
        tool: str,
        args: dict[str, Any],
        detail: str,
        approval_source: ApprovalSource | None = None,
        approval_verdict: ApprovalVerdict | None = None,
        approval_explanation: str | None = None,
        tool_id: str | None = None,
        parent_tool_id: str | None = None,
    ) -> None:
        normalized_args = normalize_tool_call_args(tool, args)
        contexts_raw = normalized_args.get("contexts")
        contexts = list(contexts_raw) if isinstance(contexts_raw, list) else []
        await self._safe_send(
            ToolCallInfo(
                tool=tool,
                args=normalized_args,
                detail=detail,
                contexts=contexts,
                approval_source=approval_source,
                approval_verdict=approval_verdict,
                approval_explanation=approval_explanation,
                tool_id=tool_id,
                parent_tool_id=parent_tool_id,
            )
        )

    async def on_tool_result(self, result: ToolResult) -> None:
        await self._safe_send(
            ToolResultInfo(
                tool=result.tool,
                result=result.output,
                exit_code=result.exit_code,
                tool_id=result.tool_id,
                files=list(result.files) or None,
            )
        )

    async def on_token(self, content: str) -> None:
        await self._safe_send(TokenChunk(content=content))

    async def on_thinking_token(self, content: str) -> None:
        await self._safe_send(ThinkingChunk(content=content))

    async def on_llm_activity(self, activity: LlmRequestState | None) -> None:
        await self._safe_send(LlmActivityUpdate(activity=_llm_activity_payload(activity)))

    async def on_status(
        self,
        *,
        agent_running: bool,
        usage: TurnUsage | None,
        llm_activity: LlmRequestState | None,
        budget: SessionBudget,
    ) -> None:
        await self._safe_send(
            StatusUpdate(
                agent_running=agent_running,
                usage=usage,
                llm_activity=_llm_activity_payload(llm_activity),
                budget=budget,
            )
        )

    async def on_done(
        self,
        content: str,
        usage: TurnUsage,
        *,
        thinking: str | None = None,
        final_status: FinalStatus | None = None,
    ) -> None:
        await self._safe_send(Done(content=content, thinking=thinking, usage=usage, final_status=final_status))

    async def on_error(self, detail: str, *, turn_terminal: bool = False) -> None:
        await self._safe_send(ErrorMessage(detail=detail, turn_terminal=turn_terminal))

    async def on_cancelled(self) -> None:
        await self._safe_send(Cancelled())

    async def on_approval_request(self, req: ApprovalRequest) -> None:
        await self._safe_send(req)

    async def on_domain_access_approval_request(self, request_id: str, domain: str, command: str) -> None:
        await self._safe_send(DomainAccessApprovalRequest(request_id=request_id, domain=domain, command=command))

    async def on_git_push_approval_request(
        self, request_id: str, ref: str, explanation: str, changed_files: list[str]
    ) -> None:
        await self._safe_send(
            GitPushApprovalRequest(request_id=request_id, ref=ref, explanation=explanation, changed_files=changed_files)
        )

    async def on_title_update(self, title: str, usage: TurnUsage | None = None) -> None:
        await self._safe_send(SessionTitleUpdate(title=title, usage=usage))

    async def on_domain_info(
        self,
        domain: str,
        detail: str,
        approval_source: ApprovalSource | None = None,
        approval_verdict: ApprovalVerdict | None = None,
        approval_explanation: str | None = None,
        tool_id: str | None = None,
        parent_tool_id: str | None = None,
    ) -> None:
        await self._safe_send(
            ToolCallInfo(
                tool="proxy_domain",
                args={"domain": domain},
                detail=detail,
                approval_source=approval_source,
                approval_verdict=approval_verdict,
                approval_explanation=approval_explanation,
                tool_id=tool_id,
                parent_tool_id=parent_tool_id,
            )
        )

    async def on_git_push_info(
        self,
        ref: str,
        decision: str,
        detail: str,
        approval_source: ApprovalSource | None = None,
        approval_verdict: ApprovalVerdict | None = None,
        approval_explanation: str | None = None,
        tool_id: str | None = None,
        parent_tool_id: str | None = None,
    ) -> None:
        await self._safe_send(
            ToolCallInfo(
                tool="git_push",
                args={"ref": ref, "decision": decision},
                detail=detail,
                approval_source=approval_source,
                approval_verdict=approval_verdict,
                approval_explanation=approval_explanation,
                tool_id=tool_id,
                parent_tool_id=parent_tool_id,
            )
        )

    async def on_credential_info(
        self,
        vault_path: str,
        name: str,
        detail: str,
        approval_source: ApprovalSource | None = None,
        approval_verdict: ApprovalVerdict | None = None,
        approval_explanation: str | None = None,
        tool_id: str | None = None,
        parent_tool_id: str | None = None,
    ) -> None:
        await self._safe_send(
            ToolCallInfo(
                tool="credential_access",
                args={"vault_path": vault_path, "name": name},
                detail=detail,
                approval_source=approval_source,
                approval_verdict=approval_verdict,
                approval_explanation=approval_explanation,
                tool_id=tool_id,
                parent_tool_id=parent_tool_id,
            )
        )

    async def on_credential_approval_request(
        self,
        request_id: str,
        vault_paths: list[str],
        names: list[str],
        descriptions: list[str],
        skill_name: str | None,
        explanation: str,
    ) -> None:
        await self._safe_send(
            CredentialApprovalRequest(
                request_id=request_id,
                vault_paths=vault_paths,
                names=names,
                descriptions=descriptions,
                skill_name=skill_name,
                explanation=explanation,
            )
        )


@router.websocket("/chat/{session_id}")
async def chat_ws(
    websocket: WebSocket,
    session_id: str,
    user: Annotated[UserIdentity, Depends(verify_ws_token)],
    client_id: Annotated[str | None, Query()] = None,
) -> None:
    current_state = server._engine.session_mgr.load_state(session_id)
    if current_state is None or not server._engine.session_mgr.is_owned_by(session_id, user.username):
        logger.warning(f"WebSocket rejected — session {session_id} not found")
        await websocket.close(code=4004, reason="Session not found")
        return

    await websocket.accept()
    logger.info(f"WebSocket connected for session {session_id}")

    normalized_client_id = client_id.strip() if client_id else ""
    ws_source_id = normalized_client_id or f"ws:{uuid.uuid4().hex}"
    ws_client_type: NotificationClientType = "cli" if current_state.channel_type == "cli" else "web"
    await _set_notification_presence(
        session_id=session_id,
        source_id=ws_source_id,
        client_type=ws_client_type,
        focus_state="visible",
    )

    sub = WebSocketSubscriber(websocket)
    active = server._engine.subscribe(session_id, sub)

    agent_running = active.agent_task is not None and not active.agent_task.done()
    usage = server._engine._turn_usage_payload(active)
    with contextlib.suppress(Exception):
        await _send(
            websocket,
            StatusUpdate(
                agent_running=agent_running,
                usage=usage,
                llm_activity=_llm_activity_payload(active.llm_request_state if agent_running else None),
                budget=active.state.budget,
            ),
        )

    for pa in list(active.pending_approval_requests):
        with contextlib.suppress(Exception):
            await _send(
                websocket,
                ApprovalRequest(
                    tool_call_id=pa["tool_call_id"],
                    tool=pa.get("tool", ""),
                    args=pa.get("args", {}),
                    explanation=pa.get("explanation", ""),
                    risk_level=pa.get("risk_level", ""),
                ),
            )
    for pp in list(active.pending_escalations):
        with contextlib.suppress(Exception):
            if pp.get("kind") == "git_push":
                await _send(
                    websocket,
                    GitPushApprovalRequest(
                        request_id=pp["request_id"],
                        ref=pp.get("ref", ""),
                        explanation=pp.get("explanation", ""),
                        changed_files=pp.get("changed_files", []),
                    ),
                )
            elif pp.get("kind") == "credential_access":
                await _send(
                    websocket,
                    CredentialApprovalRequest(
                        request_id=pp["request_id"],
                        vault_paths=pp.get("vault_paths", []),
                        names=pp.get("names", []),
                        descriptions=pp.get("descriptions", []),
                        skill_name=pp.get("skill_name"),
                        explanation=pp.get("explanation", ""),
                    ),
                )
            else:
                await _send(
                    websocket,
                    DomainAccessApprovalRequest(
                        request_id=pp["request_id"],
                        domain=pp.get("domain", ""),
                        command=pp.get("command", ""),
                    ),
                )

    try:
        while True:
            raw = await websocket.receive_json()
            try:
                client_msg = parse_client_message(raw)
            except (ValueError, Exception) as exc:
                await _send(websocket, ErrorMessage(detail=str(exc)))
                continue

            current_state = server._engine.session_mgr.load_state(session_id)
            archived_session = current_state is not None and current_state.attributes.archived

            if isinstance(client_msg, CancelRequest):
                await server._engine.submit_cancel(session_id)
                continue

            if archived_session and isinstance(client_msg, RetryLatestTurnRequest | ResetToTurnRequest | UserMessage):
                await _send(websocket, ErrorMessage(detail="Archived sessions must be unarchived before use"))
                continue

            if isinstance(client_msg, RetryLatestTurnRequest):
                await server._engine.retry_latest_turn(session_id, origin=sub)
                continue

            if isinstance(client_msg, ResetToTurnRequest):
                reset_applied = await server._engine.reset_to_turn(session_id, client_msg.event_index)
                if reset_applied:
                    await _send(
                        websocket,
                        CommandResult(
                            command="reset_to_turn",
                            data={"event_index": client_msg.event_index},
                        ),
                    )
                continue

            if isinstance(client_msg, ApprovalResponse | EscalationResponse):
                await server._engine.submit_approval(session_id, client_msg)
                continue

            if not isinstance(client_msg, UserMessage):
                await _send(websocket, ErrorMessage(detail="Expected a message"))
                continue

            user_input = client_msg.content.strip()
            # Only trust attachment paths the upload endpoint could have produced (under /tmp);
            # the client echoes these back, so drop anything pointing elsewhere.
            attachments = [a for a in client_msg.attachments if a.path.startswith("/tmp/")]
            if not user_input and not attachments:
                continue

            # Slash commands carry no attachments; an attachment-only message is a normal turn.
            if user_input.startswith("/") and not attachments:
                if user_input.lower() in ("/quit", "/exit"):
                    await websocket.close(code=1000)
                    break

                cmd_result = await server._engine.handle_slash_command(session_id, user_input)
                if cmd_result:
                    result = CommandResult(
                        command=cmd_result["command"],
                        data=cmd_result["data"],
                    )
                    await _send(websocket, UserMessageNotification(content=user_input))
                    await _send(websocket, result)
                    server._engine.session_mgr.append_events(
                        session_id,
                        [
                            {"role": "user", "content": user_input},
                            {"role": "command", "command": result.command, "data": result.data},
                        ],
                    )
                    continue

            await server._engine.submit_message(session_id, user_input, origin=sub, attachments=attachments)

    except WebSocketDisconnect as exc:
        logger.info(f"Client disconnected from session {session_id} (code={exc.code})")
    except Exception as exc:
        logger.exception(f"Unexpected WebSocket error in session {session_id}: {exc}")
        with contextlib.suppress(Exception):
            await websocket.close(code=1011)
    finally:
        server._notification_presence.remove_presence(session_id=session_id, source_id=ws_source_id)
        server._engine.unsubscribe(session_id, sub)
        logger.debug(f"WebSocket cleanup for session {session_id}")
