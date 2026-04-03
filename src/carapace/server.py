from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging  # stdlib logging used only for _InterceptHandler → loguru bridge
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any, Literal

import logfire
import loguru
import uvicorn
from dotenv import load_dotenv
from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    HTTPException,
    Query,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
    WebSocketException,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from genai_prices import UpdatePrices
from httpx import AsyncClient, HTTPStatusError, Timeout
from loguru import logger
from pydantic import BaseModel
from pydantic_ai.models import Model, infer_model
from pydantic_ai.providers import Provider, infer_provider, infer_provider_class
from pydantic_ai.retries import AsyncTenacityTransport, RetryConfig, wait_retry_after
from tenacity import retry_if_exception_type, stop_after_attempt, wait_exponential

from carapace.auth import get_token
from carapace.bootstrap import ensure_data_dir, ensure_knowledge_dir
from carapace.config import _resolve_data_dir, _resolve_knowledge_dir, get_config_path, get_data_dir, load_config
from carapace.credentials import CredentialRegistry, build_credential_registry
from carapace.git.http import GitHttpHandler
from carapace.git.store import GitStore
from carapace.models import Config, SessionState, ToolResult
from carapace.sandbox.manager import SandboxManager
from carapace.sandbox.proxy import ProxyServer
from carapace.sandbox.runtime import ContainerRuntime
from carapace.security.context import CredentialAccessEntry
from carapace.session import SessionEngine, SessionManager
from carapace.skills import SkillRegistry
from carapace.ws_models import (
    SLASH_COMMANDS,
    ApprovalRequest,
    ApprovalResponse,
    Cancelled,
    CancelRequest,
    CommandResult,
    CredentialApprovalRequest,
    CredentialApprovalResponse,
    DomainAccessApprovalRequest,
    Done,
    ErrorMessage,
    EscalationResponse,
    GitPushApprovalRequest,
    ServerEnvelope,
    SessionTitleUpdate,
    StatusUpdate,
    TokenChunk,
    ToolCallInfo,
    ToolResultInfo,
    TurnUsage,
    UserMessage,
    UserMessageNotification,
    parse_client_message,
)

load_dotenv()

# --- Shared state populated in lifespan ---

_data_dir: Path
_config: Config
_engine: SessionEngine
_git_handler: GitHttpHandler
_credential_registry: CredentialRegistry


def _retry_http_client() -> AsyncClient:
    transport = AsyncTenacityTransport(
        config=RetryConfig(
            retry=retry_if_exception_type((HTTPStatusError, ConnectionError)),
            wait=wait_retry_after(fallback_strategy=wait_exponential(multiplier=1, max=60), max_wait=300),
            stop=stop_after_attempt(5),
            reraise=True,
        ),
        validate_response=lambda r: r.raise_for_status() if r.status_code in (429, 502, 503, 504) else None,
    )
    return AsyncClient(transport=transport, timeout=Timeout(60.0))


def _create_model(model_name: str) -> Model:
    """Create a Pydantic AI model with retry-capable HTTP transport."""
    http_client = _retry_http_client()

    def _provider_factory(name: str) -> Provider:
        if name.startswith("gateway/"):
            return infer_provider(name)
        if name in ("google-vertex", "google-gla"):
            from pydantic_ai.providers.google import GoogleProvider

            return GoogleProvider(vertexai=name == "google-vertex", http_client=http_client)
        cls = infer_provider_class(name)
        if "http_client" in inspect.signature(cls).parameters:
            return cls(http_client=http_client)  # type: ignore
        return cls()

    return infer_model(model_name, provider_factory=_provider_factory)


def _create_sandbox_runtime(config: Config, data_dir: Path) -> ContainerRuntime:
    """Instantiate the sandbox container runtime based on config."""
    if config.sandbox.runtime == "kubernetes":
        from carapace.sandbox.kubernetes import KubernetesRuntime

        return KubernetesRuntime(
            namespace=config.sandbox.k8s_namespace,
            pvc_claim=config.sandbox.k8s_pvc_claim,
            data_dir=data_dir,
            service_account=config.sandbox.k8s_service_account,
            priority_class=config.sandbox.k8s_priority_class,
            owner_ref=config.sandbox.k8s_owner_ref,
            app_instance=config.sandbox.k8s_app_instance,
            session_pvc_size=config.sandbox.k8s_session_pvc_size,
            session_pvc_storage_class=config.sandbox.k8s_session_pvc_storage_class,
            resource_requests_cpu=config.sandbox.k8s_resource_requests_cpu,
            resource_requests_memory=config.sandbox.k8s_resource_requests_memory,
            resource_limits_cpu=config.sandbox.k8s_resource_limits_cpu,
            resource_limits_memory=config.sandbox.k8s_resource_limits_memory,
        )

    from carapace.sandbox.docker import DockerRuntime

    host_data_dir_env = os.environ.get("CARAPACE_HOST_DATA_DIR")
    return DockerRuntime(
        data_dir=data_dir,
        host_data_dir=Path(host_data_dir_env) if host_data_dir_env else None,
        network_name=config.sandbox.network_name,
    )


async def _idle_cleanup_loop(sandbox_mgr: SandboxManager) -> None:
    """Periodically clean up idle sandbox containers."""
    while True:
        await asyncio.sleep(60)
        try:
            await sandbox_mgr.cleanup_idle()
        except Exception as exc:
            logger.warning(f"Sandbox idle cleanup error: {exc}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _data_dir, _config, _engine, _git_handler, _credential_registry

    # 1. Load config
    config_path = get_config_path()
    _config = load_config()
    _data_dir = _resolve_data_dir(config_path, _config)
    knowledge_dir = _resolve_knowledge_dir(config_path, _config)

    # 2. Bootstrap directories
    ensure_data_dir(_data_dir)

    # 3. Git-backed knowledge store
    git_store = GitStore(
        knowledge_dir,
        remote_branch=_config.git.branch,
        author=_config.git.author,
    )
    await git_store.ensure_repo()

    # Pull from external remote if configured
    if _config.git.remote:
        git_token = _config.git.token.resolve().get_secret_value() if _config.git.token else None
        await git_store.add_remote(_config.git.remote, git_token)
        try:
            summary = await git_store.pull_from_remote()
            logger.info(f"Pulled from remote: {summary}")
        except RuntimeError as exc:
            logger.error(str(exc))
            raise SystemExit(1) from exc

    # Bootstrap knowledge files (after pull so we don't override remote content)
    seeded = ensure_knowledge_dir(knowledge_dir)
    if seeded:
        await git_store.commit(seeded, "🔧 bootstrap: seed default files")
        if _config.git.remote:
            await git_store.push_to_remote()

    if _config.carapace.logfire_token:
        logfire.configure(token=_config.carapace.logfire_token, console=False)
        logfire.instrument_pydantic_ai()

    session_mgr = SessionManager(_data_dir)
    registry = SkillRegistry(knowledge_dir / "skills")
    skill_catalog = registry.scan()
    agent_model = _create_model(_config.agent.model)

    runtime = _create_sandbox_runtime(_config, _data_dir)

    network_info = await runtime.get_self_network_info()
    if network_info:
        for net_name, ip in network_info.items():
            logger.info(f"Network interface: {net_name} → {ip}")
    else:
        logger.warning("Could not determine any network addresses")

    base_image = _config.sandbox.base_image

    if not runtime.image_exists(base_image):
        logger.error(
            f"Sandbox image '{base_image}' not found. "
            f"Build it with: docker compose build sandbox\n"
            f"Or pull it with: docker pull {base_image}"
        )
        raise SystemExit(1)

    sandbox_network = _config.sandbox.network_name
    if _config.sandbox.runtime == "docker":
        # Resolve the actual Docker network name once at startup.
        # Docker Compose prefixes networks with the project name, so the logical
        # name "carapace-sandbox" may be "carapace_carapace-sandbox" in Docker.
        sandbox_network = await runtime.resolve_self_network_name(sandbox_network)
        if sandbox_network != _config.sandbox.network_name:
            logger.info(f"Resolved sandbox network '{_config.sandbox.network_name}' → '{sandbox_network}'")

        # Pre-create the network when not already managed by docker-compose,
        # always as internal so sandbox containers have no direct internet egress.
        await runtime.ensure_network(sandbox_network, internal=True)

    proxy_port = _config.sandbox.proxy_port

    _sandbox_mgr = SandboxManager(
        runtime=runtime,
        data_dir=_data_dir,
        knowledge_dir=knowledge_dir,
        base_image=base_image,
        network_name=sandbox_network,
        idle_timeout_minutes=_config.sandbox.idle_timeout_minutes,
        proxy_port=proxy_port,
        sandbox_port=_config.server.sandbox_port,
        git_author=_config.git.author,
    )
    logger.info(f"Sandbox enabled (image={base_image}, network={sandbox_network})")

    if _config.sandbox.cleanup_orphans_on_startup:
        known = set(session_mgr.list_sessions())
        removed = await _sandbox_mgr.cleanup_orphaned_sandboxes(known)
        if removed:
            logger.info(f"Cleaned up {removed} orphaned sandbox(es)")

    _engine = SessionEngine(
        config=_config,
        data_dir=_data_dir,
        knowledge_dir=knowledge_dir,
        git_store=git_store,
        session_mgr=session_mgr,
        skill_catalog=skill_catalog,
        agent_model=agent_model,
        sandbox_mgr=_sandbox_mgr,
        model_factory=_create_model,
    )

    # Credential vault backends (must be built before passing to engine)
    _credential_registry = await build_credential_registry(_config.credentials, _data_dir)
    if _credential_registry.backend_names:
        logger.info(f"Credential backends: {', '.join(_credential_registry.backend_names)}")
    _engine.set_credential_registry(_credential_registry)

    # Git HTTP handler — serves the knowledge repo on the sandbox API
    _git_handler = GitHttpHandler(
        knowledge_dir=knowledge_dir,
        default_branch="main",
        api_port=_config.server.internal_port,
        verify_session_token=_sandbox_mgr.verify_session_token,
        on_push_success=git_store.push_to_remote if _config.git.remote else None,
    )

    proxy = ProxyServer(
        verify_session_token=_sandbox_mgr.verify_session_token,
        get_allowed_domains=_sandbox_mgr.get_effective_domains,
        request_approval=_sandbox_mgr.request_domain_approval,
        host="0.0.0.0",
        port=proxy_port,
    )
    await proxy.start()

    # Start sandbox-facing API server (Basic Auth, accessible by containers)
    sandbox_server = uvicorn.Server(
        uvicorn.Config(
            sandbox_app,
            host="0.0.0.0",
            port=_config.server.sandbox_port,
            log_level=_config.carapace.log_level,
            log_config=None,
        )
    )
    sandbox_task = asyncio.create_task(sandbox_server.serve())
    logger.info(f"Sandbox API listening on 0.0.0.0:{_config.server.sandbox_port}")

    # Start internal API server (loopback only, no auth)
    internal_server = uvicorn.Server(
        uvicorn.Config(
            internal_app,
            host="127.0.0.1",
            port=_config.server.internal_port,
            log_level=_config.carapace.log_level,
            log_config=None,
        )
    )
    internal_task = asyncio.create_task(internal_server.serve())
    logger.info(f"Internal API listening on 127.0.0.1:{_config.server.internal_port}")

    token = get_token()

    price_updater = UpdatePrices()
    price_updater.start()

    cleanup_task = asyncio.create_task(_idle_cleanup_loop(_sandbox_mgr))

    matrix_channel = None
    if _config.channels.matrix.enabled:
        from carapace.channels.matrix import MatrixChannel

        matrix_channel = MatrixChannel(
            config=_config.channels.matrix,
            full_config=_config,
            session_mgr=session_mgr,
            skill_catalog=skill_catalog,
            agent_model=agent_model,
            sandbox_mgr=_sandbox_mgr,
            engine=_engine,
        )
        await matrix_channel.start()

    logger.info(
        f"Carapace server ready — model={_config.agent.model}, "
        f"skills={len(skill_catalog)}, proxy_port={proxy_port}, token={token[:8]}…"
        + (f", matrix=on ({_config.channels.matrix.homeserver})" if _config.channels.matrix.enabled else "")
    )
    yield
    logger.info("Server shutting down…")
    cleanup_task.cancel()
    if matrix_channel:
        await matrix_channel.stop()
    sandbox_server.should_exit = True
    internal_server.should_exit = True
    sandbox_task.cancel()
    internal_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await sandbox_task
    with contextlib.suppress(asyncio.CancelledError):
        await internal_task
    await proxy.stop()
    await _credential_registry.close()
    await _sandbox_mgr.cleanup_all()
    price_updater.stop()
    logger.info("Shutdown complete")


app = FastAPI(title="Carapace", lifespan=lifespan)

router = APIRouter(prefix="/api")

# CORS must be added before the app starts (Starlette forbids it in lifespan).
# Load config early so we know the allowed origins.
_cors_config = load_config(get_data_dir())
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_config.server.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_bearer_scheme = HTTPBearer()


async def _verify_token(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer_scheme)],
) -> str:
    expected = get_token()
    if credentials.credentials != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return credentials.credentials


async def _verify_ws_token(
    websocket: WebSocket,
    token: Annotated[str | None, Query()] = None,
) -> str:
    expected = get_token()
    if token and token == expected:
        return token
    auth = websocket.headers.get("authorization", "")
    if auth.startswith("Bearer ") and auth.removeprefix("Bearer ") == expected:
        return expected
    await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
    raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION)


# --- REST: Sessions ---


class SessionCreateRequest(BaseModel):
    channel_type: str = "cli"
    channel_ref: str = ""


class SessionInfo(BaseModel):
    session_id: str
    channel_type: str
    channel_ref: str | None = None
    created_at: str
    last_active: str
    title: str | None = None
    message_count: int = 0

    @classmethod
    def from_state(cls, state: SessionState, *, message_count: int = 0) -> SessionInfo:
        return cls(
            session_id=state.session_id,
            channel_type=state.channel_type,
            channel_ref=state.channel_ref,
            created_at=state.created_at.isoformat(),
            last_active=state.last_active.isoformat(),
            title=state.title,
            message_count=message_count,
        )


@router.post("/sessions", response_model=SessionInfo)
async def create_session(
    body: SessionCreateRequest | None = None,
    _token: str = Depends(_verify_token),
) -> SessionInfo:
    body = body or SessionCreateRequest()
    state = _engine.session_mgr.create_session(body.channel_type, body.channel_ref)
    return SessionInfo.from_state(state)


@router.get("/sessions", response_model=list[SessionInfo])
async def list_sessions(_token: str = Depends(_verify_token)) -> list[SessionInfo]:
    results: list[SessionInfo] = []
    for sid in _engine.session_mgr.list_sessions():
        state = _engine.session_mgr.load_state(sid)
        if state:
            events = _engine.session_mgr.load_events(sid)
            message_count = sum(1 for e in events if e.get("role") == "user")
            results.append(SessionInfo.from_state(state, message_count=message_count))
    return results


@router.get("/sessions/{session_id}", response_model=SessionInfo)
async def get_session(session_id: str, _token: str = Depends(_verify_token)) -> SessionInfo:
    state = _engine.session_mgr.load_state(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return SessionInfo.from_state(state)


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(session_id: str, _token: str = Depends(_verify_token)) -> None:
    _engine.deactivate(session_id)
    await _engine.sandbox_mgr.destroy_session(session_id)
    if not _engine.session_mgr.delete_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found")


_HistoryRole = Literal[
    "user",
    "assistant",
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
]


class HistoryMessage(BaseModel):
    role: _HistoryRole
    content: str = ""
    tool: str | None = None
    args: dict[str, Any] | None = None
    detail: str | None = None
    result: str | None = None
    command: str | None = None
    data: Any = None
    request_id: str | None = None
    domain: str | None = None
    decision: str | None = None
    tool_call_id: str | None = None
    explanation: str | None = None
    risk_level: str | None = None
    ref: str | None = None
    changed_files: list[str] | None = None
    vault_paths: list[str] | None = None
    names: list[str] | None = None
    descriptions: list[str] | None = None
    skill_name: str | None = None


@router.get("/sessions/{session_id}/history", response_model=list[HistoryMessage])
async def get_session_history(
    session_id: str,
    limit: Annotated[int, Query()] = -1,
    _token: str = Depends(_verify_token),
) -> list[HistoryMessage]:
    if _engine.session_mgr.load_state(session_id) is None:
        raise HTTPException(status_code=404, detail="Session not found")

    events = _engine.session_mgr.load_events(session_id)
    result = [HistoryMessage.model_validate(e) for e in events] if events else _history_from_messages(session_id)

    if limit > 0:
        result = result[-limit:]
    return result


def _history_from_messages(session_id: str) -> list[HistoryMessage]:
    """Fallback: build history from Pydantic AI messages for sessions without events."""
    from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, ToolCallPart, UserPromptPart

    raw_messages = _engine.session_mgr.load_history(session_id)
    result: list[HistoryMessage] = []
    for msg in raw_messages:
        if isinstance(msg, ModelRequest):
            for part in msg.parts:
                if isinstance(part, UserPromptPart) and isinstance(part.content, str):
                    result.append(HistoryMessage(role="user", content=part.content))
        elif isinstance(msg, ModelResponse):
            for part in msg.parts:
                if isinstance(part, ToolCallPart):
                    args = part.args if isinstance(part.args, dict) else {}
                    result.append(HistoryMessage(role="tool_call", content="", tool=part.tool_name, args=args))
                elif isinstance(part, TextPart):
                    result.append(HistoryMessage(role="assistant", content=part.content))
    return result


# --- WebSocket: Chat ---


async def _send(ws: WebSocket, msg: ServerEnvelope) -> None:
    await ws.send_json(msg.model_dump())


@router.get("/commands")
async def list_commands(_token: str = Depends(_verify_token)) -> list[dict[str, str]]:
    return SLASH_COMMANDS


@router.get("/models")
async def list_models(_token: str = Depends(_verify_token)) -> list[str]:
    return _engine.available_models


class WebSocketSubscriber:
    """Thin adapter: forwards ``SessionEngine`` events to a WebSocket."""

    def __init__(self, ws: WebSocket) -> None:
        self._ws = ws

    async def _safe_send(self, msg: ServerEnvelope) -> None:
        try:
            await _send(self._ws, msg)
        except Exception as exc:
            logger.warning(f"WebSocket send failed: {exc}")

    async def on_user_message(self, content: str, *, from_self: bool) -> None:
        await self._safe_send(UserMessageNotification(content=content))

    async def on_tool_call(self, tool: str, args: dict[str, Any], detail: str) -> None:
        await self._safe_send(ToolCallInfo(tool=tool, args=args, detail=detail))

    async def on_tool_result(self, result: ToolResult) -> None:
        await self._safe_send(ToolResultInfo(tool=result.tool, result=result.output, exit_code=result.exit_code))

    async def on_token(self, content: str) -> None:
        await self._safe_send(TokenChunk(content=content))

    async def on_done(self, content: str, usage: TurnUsage) -> None:
        await self._safe_send(Done(content=content, usage=usage))

    async def on_error(self, detail: str) -> None:
        await self._safe_send(ErrorMessage(detail=detail))

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

    async def on_title_update(self, title: str) -> None:
        await self._safe_send(SessionTitleUpdate(title=title))

    async def on_domain_info(self, domain: str, detail: str) -> None:
        await self._safe_send(ToolCallInfo(tool="proxy_domain", args={"domain": domain}, detail=detail))

    async def on_git_push_info(self, ref: str, decision: str, detail: str) -> None:
        await self._safe_send(ToolCallInfo(tool="git_push", args={"ref": ref, "decision": decision}, detail=detail))

    async def on_credential_approval_request(
        self,
        vault_paths: list[str],
        names: list[str],
        descriptions: list[str],
        skill_name: str | None,
        explanation: str,
    ) -> None:
        await self._safe_send(
            CredentialApprovalRequest(
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
    _token: Annotated[str, Depends(_verify_ws_token)],
) -> None:
    if _engine.session_mgr.load_state(session_id) is None:
        logger.warning(f"WebSocket rejected — session {session_id} not found")
        await websocket.close(code=4004, reason="Session not found")
        return

    await websocket.accept()
    logger.info(f"WebSocket connected for session {session_id}")

    sub = WebSocketSubscriber(websocket)
    active = _engine.subscribe(session_id, sub)

    # Tell the client whether an agent turn is in progress.
    agent_running = active.agent_task is not None and not active.agent_task.done()
    tracker = active.usage_tracker
    usage = (
        TurnUsage(input_tokens=tracker.total_input, output_tokens=tracker.total_output)
        if tracker.total_input or tracker.total_output
        else None
    )
    with contextlib.suppress(Exception):
        await _send(websocket, StatusUpdate(agent_running=agent_running, usage=usage))

    # If agent is already running (e.g. reconnect), the subscriber will
    # start receiving events immediately.  If there are pending approvals,
    # re-send them so the client can respond.
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
            else:
                await _send(
                    websocket,
                    DomainAccessApprovalRequest(
                        request_id=pp["request_id"],
                        domain=pp.get("domain", ""),
                        command=pp.get("command", ""),
                    ),
                )

    for pc in list(active.pending_credential_approvals):
        with contextlib.suppress(Exception):
            await _send(
                websocket,
                CredentialApprovalRequest(
                    vault_paths=pc.get("vault_paths", []),
                    names=pc.get("names", []),
                    descriptions=pc.get("descriptions", []),
                    skill_name=pc.get("skill_name"),
                    explanation=pc.get("explanation", ""),
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

            # --- Cancel in-flight agent turn ---
            if isinstance(client_msg, CancelRequest):
                await _engine.submit_cancel(session_id)
                continue

            # --- Approval responses — forward to engine ---
            if isinstance(client_msg, ApprovalResponse | EscalationResponse | CredentialApprovalResponse):
                await _engine.submit_approval(session_id, client_msg)
                continue

            if not isinstance(client_msg, UserMessage):
                await _send(websocket, ErrorMessage(detail="Expected a message"))
                continue

            user_input = client_msg.content.strip()
            if not user_input:
                continue

            # --- Slash commands ---
            if user_input.startswith("/"):
                if user_input.lower() in ("/quit", "/exit"):
                    await websocket.close(code=1000)
                    break

                if user_input.lower() == "/verbose":
                    active.verbose = not active.verbose
                    state_str = "on" if active.verbose else "off"
                    result = CommandResult(
                        command="verbose",
                        data={"verbose": active.verbose, "message": f"Verbose mode {state_str}"},
                    )
                    await _send(websocket, UserMessageNotification(content=user_input))
                    await _send(websocket, result)
                    _engine.session_mgr.append_events(
                        session_id,
                        [
                            {"role": "user", "content": user_input},
                            {"role": "command", "command": result.command, "data": result.data},
                        ],
                    )
                    continue

                cmd_result = await _engine.handle_slash_command(session_id, user_input)
                if cmd_result:
                    result = CommandResult(
                        command=cmd_result["command"],
                        data=cmd_result["data"],
                    )
                    await _send(websocket, UserMessageNotification(content=user_input))
                    await _send(websocket, result)
                    _engine.session_mgr.append_events(
                        session_id,
                        [
                            {"role": "user", "content": user_input},
                            {"role": "command", "command": result.command, "data": result.data},
                        ],
                    )
                    continue

                await _send(websocket, ErrorMessage(detail=f"Unknown command: {user_input.split()[0]}"))
                continue

            # --- Agent turn ---
            await _engine.submit_message(session_id, user_input, origin=sub)

    except WebSocketDisconnect as exc:
        logger.info(f"Client disconnected from session {session_id} (code={exc.code})")
    except Exception as exc:
        logger.exception(f"Unexpected WebSocket error in session {session_id}: {exc}")
        with contextlib.suppress(Exception):
            await websocket.close(code=1011)
    finally:
        _engine.unsubscribe(session_id, sub)
        logger.debug(f"WebSocket cleanup for session {session_id}")


class _InterceptHandler(logging.Handler):
    """Route stdlib logging records to loguru."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        frame, depth = logging.currentframe(), 0
        while frame and (depth == 0 or frame.f_code.co_filename == logging.__file__):
            frame = frame.f_back
            depth += 1
        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def _setup_logging() -> None:
    logging.root.handlers = [_InterceptHandler()]
    logging.root.setLevel(logging.DEBUG)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi"):
        log = logging.getLogger(name)
        log.handlers = [_InterceptHandler()]
        log.propagate = False

    for name in (
        "httpcore",
        "httpx",
        "docker",
        "anthropic",
        "websockets",
        "websockets.server",
        "urllib3",
        "nio",
        "markdown.core",
    ):
        logging.getLogger(name).setLevel(logging.WARNING)

    def _abbrev_patcher(record: loguru.Record) -> None:
        if record["name"]:
            record["name"] = record["name"].replace("carapace.", "cp.").replace("sandbox.", "sndbx.")

    logger.configure(patcher=_abbrev_patcher)


def main() -> None:
    """Entry point for `python -m carapace` / `carapace-server`."""
    load_dotenv()
    _setup_logging()

    data_dir = get_data_dir()
    ensure_data_dir(data_dir)
    config = load_config(data_dir)
    token = get_token()

    logger.info(f"Starting Carapace server on {config.server.host}:{config.server.port}")
    logger.info(f"Sandbox API on 0.0.0.0:{config.server.sandbox_port}")
    logger.info(f"Internal API on 127.0.0.1:{config.server.internal_port}")
    logger.info(f"Bearer token: {token[:8]}…")

    uvicorn.run(
        "carapace.server:app",
        host=config.server.host,
        port=config.server.port,
        log_level=config.carapace.log_level,
        log_config=None,
    )


# --- Internal endpoint for pre-receive hook sentinel evaluation ---
# Bound to 127.0.0.1 only — unreachable from sandbox containers.

internal_app = FastAPI(title="Carapace Internal")


class PushEvalRequest(BaseModel):
    session_id: str
    ref: str
    is_default_branch: bool
    commits: str
    diff: str


@internal_app.post("/internal/sentinel/evaluate-push")
async def evaluate_push(req: PushEvalRequest) -> dict[str, str]:
    """Evaluate a Git push via the sentinel. Called by the pre-receive hook."""
    try:
        active = _engine.get_or_activate(req.session_id)
    except KeyError:
        return {"verdict": "deny", "reason": "Session not found"}
    if active.security is None or active.sentinel is None:
        return {"verdict": "deny", "reason": "Session not initialised"}

    from carapace.security import evaluate_push_with

    allowed = await evaluate_push_with(
        active.security,
        active.sentinel,
        req.ref,
        req.is_default_branch,
        req.commits,
        req.diff,
        usage_tracker=active.usage_tracker,
    )
    if allowed:
        return {"verdict": "allow"}
    return {"verdict": "deny", "reason": "Denied by sentinel"}


app.include_router(router)


# --- Sandbox-facing API (Basic Auth, serves git HTTP backend) ---

sandbox_app = FastAPI(title="Carapace Sandbox API")


@sandbox_app.api_route("/git/{path:path}", methods=["GET", "POST"])
async def git_http_backend(request: Request, path: str) -> Response:
    """Proxy Git HTTP Smart Protocol requests to ``git http-backend``."""
    auth = request.headers.get("authorization")
    session_id = _git_handler.authenticate(auth)
    if session_id is None:
        return Response(
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="carapace git"'},
        )

    full_path = f"/git/{path}"
    query = str(request.query_params)
    body = await request.body()

    status_code, headers, response_body = await _git_handler.handle(
        session_id=session_id,
        method=request.method,
        path=full_path,
        query_string=query,
        content_type=request.headers.get("content-type"),
        body=body,
    )
    return Response(content=response_body, status_code=status_code, headers=headers)


def _authenticate_sandbox(auth: str | None) -> str | None:
    """Extract and verify session_id from Basic Auth on the sandbox API."""
    if not auth or not auth.startswith("Basic "):
        return None
    import base64

    try:
        decoded = base64.b64decode(auth.removeprefix("Basic ")).decode()
    except Exception:
        return None
    session_id, _, token = decoded.partition(":")
    if not session_id or not token:
        return None
    if _engine.sandbox_mgr.verify_session_token(session_id, token):
        return session_id
    return None


@sandbox_app.get("/credentials")
async def list_credentials(request: Request, q: str = "") -> list[dict[str, str]]:
    """List/search available credentials (metadata only, no values)."""
    session_id = _authenticate_sandbox(request.headers.get("authorization"))
    if session_id is None:
        raise HTTPException(status_code=401, detail="Unauthorized")

    items = await _credential_registry.list(q)

    return [i.model_dump() for i in items]


@sandbox_app.get("/credentials/{vault_path:path}")
async def fetch_credential(request: Request, vault_path: str) -> Response:
    """Fetch a credential value (blocks until user approves if not yet approved)."""
    session_id = _authenticate_sandbox(request.headers.get("authorization"))
    if session_id is None:
        raise HTTPException(status_code=401, detail="Unauthorized")

    # Check if credential exists in any backend
    try:
        meta = await _credential_registry.fetch_metadata(vault_path)
    except KeyError:
        return Response(status_code=404, content="Credential not found")

    active = _engine.get_or_activate(session_id)

    # Check if already approved in this session
    already_approved = any(c.vault_path == vault_path for c in active.state.approved_credentials)

    if not already_approved:
        approved = await _engine.request_credential_approval(
            session_id,
            vault_paths=[vault_path],
            names=[meta.name],
            descriptions=[meta.description],
            explanation=f"Sandbox requested credential: {meta.name}",
        )
        if not approved:
            if active.security:
                active.security.append(CredentialAccessEntry(vault_paths=[vault_path], decision="denied"))
            return Response(status_code=403, content="Credential access denied")

        # Record approval in session state
        active.state.approved_credentials.append(meta)
        _engine.session_mgr.save_state(active.state)

    # Fetch the actual value
    try:
        value = await _credential_registry.fetch(vault_path)
    except KeyError:
        return Response(status_code=404, content="Credential not found")

    if active.security:
        active.security.append(CredentialAccessEntry(vault_paths=[vault_path], decision="approved"))
    return Response(content=value, media_type="text/plain")


if __name__ == "__main__":
    main()
