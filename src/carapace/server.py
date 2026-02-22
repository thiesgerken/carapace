from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

import logfire
import loguru
import uvicorn
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect, WebSocketException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from httpx import AsyncClient, HTTPStatusError
from loguru import logger
from pydantic import BaseModel
from pydantic_ai import DeferredToolRequests, DeferredToolResults, ToolDenied
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.retries import AsyncTenacityTransport, RetryConfig, wait_retry_after
from tenacity import retry_if_exception_type, stop_after_attempt, wait_exponential

from carapace.agent import create_agent
from carapace.auth import ensure_token
from carapace.bootstrap import ensure_data_dir, get_sandbox_dockerfile
from carapace.config import get_data_dir, load_config, load_rules
from carapace.memory import MemoryStore
from carapace.models import Config, Deps, Rule, SessionState, UsageTracker
from carapace.sandbox.docker import DockerRuntime
from carapace.sandbox.manager import SandboxManager
from carapace.sandbox.proxy import DomainApprovalPending, DomainDecision, ProxyServer
from carapace.session import SessionManager
from carapace.skills import SkillRegistry
from carapace.ws_models import (
    ApprovalRequest,
    ApprovalResponse,
    CommandResult,
    Done,
    ErrorMessage,
    ProxyApprovalRequest,
    ProxyApprovalResponse,
    ServerEnvelope,
    ToolCallInfo,
    UserMessage,
    parse_client_message,
)

load_dotenv()

_BUILTIN_SANDBOX_IMAGE = "carapace-sandbox:latest"

# --- Shared state populated in lifespan ---

_data_dir: Path
_config: Config
_rules: list[Rule]
_session_mgr: SessionManager
_skill_catalog: list
_agent_model: Any
_sandbox_mgr: SandboxManager
_session_locks: dict[str, asyncio.Lock] = {}
_session_lock_refs: dict[str, int] = {}


@asynccontextmanager
async def _session_connection(session_id: str):
    """Track one WebSocket connection for a session.

    Ensures the per-session Lock exists for the lifetime of the connection and
    is removed only when the last connection closes.
    """
    _session_lock_refs[session_id] = _session_lock_refs.get(session_id, 0) + 1
    _session_locks.setdefault(session_id, asyncio.Lock())
    try:
        yield _session_locks[session_id]
    finally:
        count = _session_lock_refs[session_id] - 1
        if count <= 0:
            _session_locks.pop(session_id, None)
            _session_lock_refs.pop(session_id, None)
        else:
            _session_lock_refs[session_id] = count


def _create_anthropic_model(model_name: str) -> AnthropicModel:
    transport = AsyncTenacityTransport(
        config=RetryConfig(
            retry=retry_if_exception_type((HTTPStatusError, ConnectionError)),
            wait=wait_retry_after(fallback_strategy=wait_exponential(multiplier=1, max=60), max_wait=300),
            stop=stop_after_attempt(5),
            reraise=True,
        ),
        validate_response=lambda r: r.raise_for_status() if r.status_code in (429, 502, 503, 504) else None,
    )
    model_id = model_name.removeprefix("anthropic:")
    return AnthropicModel(model_id, provider=AnthropicProvider(http_client=AsyncClient(transport=transport)))


async def _idle_cleanup_loop() -> None:
    """Periodically clean up idle sandbox containers."""
    while True:
        await asyncio.sleep(60)
        try:
            await _sandbox_mgr.cleanup_idle()
        except Exception as exc:
            logger.warning(f"Sandbox idle cleanup error: {exc}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _data_dir, _config, _rules, _session_mgr, _skill_catalog, _agent_model, _sandbox_mgr

    _data_dir = get_data_dir()
    ensure_data_dir(_data_dir)
    _config = load_config(_data_dir)

    if _config.carapace.logfire_token:
        logfire.configure(token=_config.carapace.logfire_token, console=False)
        logfire.instrument_pydantic_ai()

    _rules = load_rules(_data_dir)
    _session_mgr = SessionManager(_data_dir)
    registry = SkillRegistry(_data_dir / "skills")
    _skill_catalog = registry.scan()
    _agent_model = _create_anthropic_model(_config.agent.model)

    runtime = DockerRuntime()

    network_info = await runtime.get_self_network_info()
    if network_info:
        for net_name, ip in network_info.items():
            logger.info(f"Network interface: {net_name} → {ip}")
    else:
        logger.warning("Could not determine any network addresses")

    base_image = _config.sandbox.base_image or _BUILTIN_SANDBOX_IMAGE
    if not _config.sandbox.base_image:
        runtime.build_image(get_sandbox_dockerfile(), _BUILTIN_SANDBOX_IMAGE)

    host_data_dir_env = os.environ.get("CARAPACE_HOST_DATA_DIR")
    host_data_dir = Path(host_data_dir_env) if host_data_dir_env else None

    proxy_port = _config.sandbox.proxy_port

    # Resolve the actual Docker network name once at startup.
    # Docker Compose prefixes networks with the project name, so the logical
    # name "carapace-sandbox" may be "carapace_carapace-sandbox" in Docker.
    # Using the concrete name everywhere avoids ambiguous resolution when stale
    # networks with the logical name exist from a previous run.
    sandbox_network = await runtime.resolve_self_network_name(_config.sandbox.network_name)
    if sandbox_network != _config.sandbox.network_name:
        logger.info(f"Resolved sandbox network '{_config.sandbox.network_name}' → '{sandbox_network}'")

    # Pre-create the network when not already managed by docker-compose,
    # always as internal so sandbox containers have no direct internet egress.
    await runtime.ensure_network(sandbox_network, internal=True)

    _sandbox_mgr = SandboxManager(
        runtime=runtime,
        data_dir=_data_dir,
        base_image=base_image,
        network_name=sandbox_network,
        idle_timeout_minutes=_config.sandbox.idle_timeout_minutes,
        host_data_dir=host_data_dir,
        proxy_port=proxy_port,
    )
    logger.info(f"Sandbox enabled (image={base_image}, network={sandbox_network})")

    proxy = ProxyServer(
        get_session_by_token=_sandbox_mgr.get_session_by_token,
        get_allowed_domains=_sandbox_mgr.get_effective_domains,
        request_approval=_sandbox_mgr.request_domain_approval,
        host="0.0.0.0",
        port=proxy_port,
    )
    await proxy.start()

    token = ensure_token(_data_dir)

    from genai_prices import UpdatePrices

    price_updater = UpdatePrices()
    price_updater.start()

    cleanup_task = asyncio.create_task(_idle_cleanup_loop())

    logger.info(
        f"Carapace server ready — model={_config.agent.model}, rules={len(_rules)}, "
        f"skills={len(_skill_catalog)}, sandbox=on, proxy_port={proxy_port}, token={token[:8]}…"
    )
    yield
    logger.info("Server shutting down…")
    cleanup_task.cancel()
    await proxy.stop()
    await _sandbox_mgr.cleanup_all()
    price_updater.stop()
    logger.info("Shutdown complete")


app = FastAPI(title="Carapace", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_bearer_scheme = HTTPBearer()


async def _verify_token(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer_scheme)],
) -> str:
    expected = ensure_token(_data_dir)
    if credentials.credentials != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return credentials.credentials


async def _verify_ws_token(
    websocket: WebSocket,
    token: Annotated[str | None, Query()] = None,
) -> str:
    expected = ensure_token(_data_dir)
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
    channel_ref: str
    created_at: str
    last_active: str
    activated_rules: list[str]
    disabled_rules: list[str]
    message_count: int = 0

    @classmethod
    def from_state(cls, state: SessionState, *, message_count: int = 0) -> SessionInfo:
        return cls(
            session_id=state.session_id,
            channel_type=state.channel_type,
            channel_ref=state.channel_ref,
            created_at=state.created_at.isoformat(),
            last_active=state.last_active.isoformat(),
            activated_rules=state.activated_rules,
            disabled_rules=state.disabled_rules,
            message_count=message_count,
        )


@app.post("/sessions", response_model=SessionInfo)
async def create_session(
    body: SessionCreateRequest | None = None,
    _token: str = Depends(_verify_token),
) -> SessionInfo:
    body = body or SessionCreateRequest()
    state = _session_mgr.create_session(body.channel_type, body.channel_ref)
    return SessionInfo.from_state(state)


@app.get("/sessions", response_model=list[SessionInfo])
async def list_sessions(_token: str = Depends(_verify_token)) -> list[SessionInfo]:
    results: list[SessionInfo] = []
    for sid in _session_mgr.list_sessions():
        state = _session_mgr.load_state(sid)
        if state:
            events = _session_mgr.load_events(sid)
            message_count = sum(1 for e in events if e.get("role") == "user")
            results.append(SessionInfo.from_state(state, message_count=message_count))
    return results


@app.get("/sessions/{session_id}", response_model=SessionInfo)
async def get_session(session_id: str, _token: str = Depends(_verify_token)) -> SessionInfo:
    state = _session_mgr.load_state(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return SessionInfo.from_state(state)


@app.delete("/sessions/{session_id}", status_code=204)
async def delete_session(session_id: str, _token: str = Depends(_verify_token)) -> None:
    await _sandbox_mgr.cleanup_session(session_id)
    if not _session_mgr.delete_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found")


class HistoryMessage(BaseModel):
    role: str  # "user" | "assistant" | "tool_call" | "command"
    content: str = ""
    tool: str | None = None
    args: dict[str, Any] | None = None
    command: str | None = None
    data: Any = None


@app.get("/sessions/{session_id}/history", response_model=list[HistoryMessage])
async def get_session_history(
    session_id: str,
    limit: Annotated[int, Query()] = -1,
    _token: str = Depends(_verify_token),
) -> list[HistoryMessage]:
    if _session_mgr.load_state(session_id) is None:
        raise HTTPException(status_code=404, detail="Session not found")

    events = _session_mgr.load_events(session_id)
    result = [HistoryMessage.model_validate(e) for e in events] if events else _history_from_messages(session_id)

    if limit > 0:
        result = result[-limit:]
    return result


def _history_from_messages(session_id: str) -> list[HistoryMessage]:
    """Fallback: build history from Pydantic AI messages for sessions without events.json."""
    from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, ToolCallPart, UserPromptPart

    raw_messages = _session_mgr.load_history(session_id)
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


def _build_deps(
    session_state: SessionState,
    *,
    verbose: bool = True,
    tool_call_callback: Any = None,
    domain_approval_callback: Any = None,
    usage_tracker: UsageTracker | None = None,
) -> Deps:
    return Deps(
        config=_config,
        data_dir=_data_dir,
        session_state=session_state,
        rules=_rules,
        skill_catalog=_skill_catalog,
        classifier_model=_config.agent.classifier_model,
        agent_model=_agent_model,
        verbose=verbose,
        tool_call_callback=tool_call_callback,
        domain_approval_callback=domain_approval_callback,
        usage_tracker=usage_tracker or _session_mgr.load_usage(session_state.session_id),
        sandbox=_sandbox_mgr,
        activated_skills=[],
    )


async def _send(ws: WebSocket, msg: ServerEnvelope) -> None:
    await ws.send_json(msg.model_dump())


def _handle_slash_command(command: str, deps: Deps) -> CommandResult | None:
    """Handle a slash command and return structured data, or None if unrecognised."""
    parts = command.strip().split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    if cmd == "/help":
        return CommandResult(
            command="help",
            data={
                "commands": [
                    {"command": "/rules", "description": "List all rules and their status"},
                    {"command": "/disable <id>", "description": "Disable a rule for this session"},
                    {"command": "/enable <id>", "description": "Re-enable a disabled rule"},
                    {"command": "/session", "description": "Show current session state"},
                    {"command": "/skills", "description": "List available skills"},
                    {"command": "/memory", "description": "List memory files"},
                    {"command": "/usage", "description": "Show token usage for this session"},
                    {"command": "/verbose", "description": "Toggle tool call display"},
                    {"command": "/quit", "description": "Disconnect"},
                    {"command": "/help", "description": "Show this help"},
                ]
            },
        )

    if cmd == "/rules":
        rules_data = []
        for rule in deps.rules:
            if rule.id in deps.session_state.disabled_rules:
                rule_status = "disabled"
            elif rule.id in deps.session_state.activated_rules:
                rule_status = "activated"
            elif rule.trigger.strip().lower() == "always":
                rule_status = "always-on"
            else:
                rule_status = "inactive"
            rules_data.append(
                {
                    "id": rule.id,
                    "trigger": rule.trigger[:50] + ("..." if len(rule.trigger) > 50 else ""),
                    "mode": rule.mode.value,
                    "status": rule_status,
                }
            )
        return CommandResult(command="rules", data=rules_data)

    if cmd == "/disable":
        if not arg:
            return CommandResult(command="disable", data={"error": "Usage: /disable <rule-id>"})
        rule_ids = [r.id for r in deps.rules]
        if arg not in rule_ids:
            return CommandResult(command="disable", data={"error": f"Unknown rule: {arg}"})
        if arg not in deps.session_state.disabled_rules:
            deps.session_state.disabled_rules.append(arg)
            _session_mgr.save_state(deps.session_state)
        return CommandResult(command="disable", data={"rule_id": arg, "message": f"Rule '{arg}' disabled"})

    if cmd == "/enable":
        if not arg:
            return CommandResult(command="enable", data={"error": "Usage: /enable <rule-id>"})
        if arg in deps.session_state.disabled_rules:
            deps.session_state.disabled_rules.remove(arg)
            _session_mgr.save_state(deps.session_state)
        return CommandResult(command="enable", data={"rule_id": arg, "message": f"Rule '{arg}' re-enabled"})

    if cmd == "/session":
        session_id = deps.session_state.session_id
        return CommandResult(
            command="session",
            data={
                "session_id": session_id,
                "channel_type": deps.session_state.channel_type,
                "activated_rules": deps.session_state.activated_rules,
                "disabled_rules": deps.session_state.disabled_rules,
                "approved_credentials": deps.session_state.approved_credentials,
                "allowed_domains": deps.sandbox.get_domain_info(session_id),
            },
        )

    if cmd == "/skills":
        skills = [{"name": s.name, "description": s.description.strip()} for s in deps.skill_catalog]
        return CommandResult(command="skills", data=skills)

    if cmd == "/memory":
        store = MemoryStore(deps.data_dir)
        files = store.list_files()
        return CommandResult(command="memory", data=files)

    if cmd == "/usage":
        tracker = deps.usage_tracker
        costs = tracker.estimated_cost()
        return CommandResult(
            command="usage",
            data={
                "models": {k: v.model_dump() for k, v in tracker.models.items()},
                "categories": {k: v.model_dump() for k, v in tracker.categories.items()},
                "total_input": tracker.total_input,
                "total_output": tracker.total_output,
                "costs": {k: str(v) for k, v in costs.items()},
            },
        )

    return None


@app.websocket("/chat/{session_id}")
async def chat_ws(
    websocket: WebSocket,
    session_id: str,
    _token: Annotated[str, Depends(_verify_ws_token)],
) -> None:
    session_state = _session_mgr.resume_session(session_id)
    if session_state is None:
        logger.warning(f"WebSocket rejected — session {session_id} not found")
        await websocket.close(code=4004, reason="Session not found")
        return

    await websocket.accept()
    logger.info(f"WebSocket connected for session {session_id}")
    verbose = True
    pending_sends: set[asyncio.Task] = set()

    def send_tool_call_info(tool: str, args: dict[str, Any], detail: str) -> None:
        """Callback to send tool call info via WebSocket."""

        async def _send_and_cleanup() -> None:
            try:
                await _send(websocket, ToolCallInfo(tool=tool, args=args, detail=detail))
            except Exception as exc:
                logger.warning(f"WebSocket send failed for tool call info: {exc}")
            finally:
                pending_sends.discard(task)

        task = asyncio.create_task(_send_and_cleanup())
        pending_sends.add(task)

    async def request_domain_approval(pending: DomainApprovalPending) -> DomainDecision:
        """Send a proxy domain approval request to the client and wait for the response."""
        await _send(
            websocket,
            ProxyApprovalRequest(
                request_id=pending.request_id,
                domain=pending.domain,
                command=pending.command,
            ),
        )
        while True:
            raw = await websocket.receive_json()
            try:
                msg = parse_client_message(raw)
            except (ValueError, Exception):
                continue
            if isinstance(msg, ProxyApprovalResponse) and msg.request_id == pending.request_id:
                return DomainDecision(msg.decision)
            # Any other message while we're waiting for domain approval is unexpected;
            # log it and keep waiting — the approval must be resolved first.
            logger.warning(f"Unexpected WS message while waiting for proxy domain approval: {msg}")

    deps = _build_deps(
        session_state,
        verbose=verbose,
        tool_call_callback=send_tool_call_info,
        domain_approval_callback=request_domain_approval,
    )

    async with _session_connection(session_id) as session_lock:
        try:
            while True:
                raw = await websocket.receive_json()
                try:
                    client_msg = parse_client_message(raw)
                except (ValueError, Exception) as exc:
                    await _send(websocket, ErrorMessage(detail=str(exc)))
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
                        verbose = not verbose
                        deps.verbose = verbose
                        state_str = "on" if verbose else "off"
                        result = CommandResult(
                            command="verbose",
                            data={"verbose": verbose, "message": f"Verbose mode {state_str}"},
                        )
                        await _send(websocket, result)
                        _session_mgr.append_events(
                            session_id,
                            [
                                {"role": "user", "content": user_input},
                                {"role": "command", "command": result.command, "data": result.data},
                            ],
                        )
                        continue

                    result = _handle_slash_command(user_input, deps)
                    if result:
                        await _send(websocket, result)
                        _session_mgr.append_events(
                            session_id,
                            [
                                {"role": "user", "content": user_input},
                                {"role": "command", "command": result.command, "data": result.data},
                            ],
                        )
                        continue

                    await _send(websocket, ErrorMessage(detail=f"Unknown command: {user_input.split()[0]}"))
                    continue

                # --- Agent loop (serialised per session) ---
                try:
                    async with session_lock:
                        fresh_state = _session_mgr.resume_session(session_id)
                        if fresh_state:
                            tracker = deps.usage_tracker
                            deps = _build_deps(
                                fresh_state,
                                verbose=verbose,
                                tool_call_callback=send_tool_call_info,
                                domain_approval_callback=request_domain_approval,
                                usage_tracker=tracker,
                            )
                        message_history = _session_mgr.load_history(session_id)
                        message_history, output = await _run_agent_turn(
                            websocket,
                            user_input,
                            deps,
                            message_history,
                        )
                        _session_mgr.save_history(session_id, message_history)
                        _session_mgr.save_state(deps.session_state)
                        _session_mgr.save_usage(session_id, deps.usage_tracker)
                        _session_mgr.append_events(
                            session_id,
                            [
                                {"role": "user", "content": user_input},
                                {"role": "assistant", "content": output},
                            ],
                        )
                except Exception as exc:
                    logger.exception("Agent error")
                    await _send(websocket, ErrorMessage(detail=str(exc)))

        except WebSocketDisconnect as exc:
            logger.info(f"Client disconnected from session {session_id} (code={exc.code})")
        except Exception as exc:
            logger.exception(f"Unexpected WebSocket error in session {session_id}: {exc}")
        finally:
            logger.debug(f"WebSocket cleanup for session {session_id}")
            for task in pending_sends:
                task.cancel()


async def _run_agent_turn(
    ws: WebSocket,
    user_input: str,
    deps: Deps,
    message_history: list,
) -> tuple[list, str]:
    """Run one agent turn, handling approval loops over the WebSocket."""
    agent = create_agent(deps)

    model_name = deps.config.agent.model
    result = await agent.run(
        user_input,
        deps=deps,
        message_history=message_history or None,
    )
    deps.usage_tracker.record(model_name, "agent", result.usage())
    messages = result.all_messages()

    while isinstance(result.output, DeferredToolRequests):
        requests = result.output
        deferred_results = DeferredToolResults()

        for call in requests.approvals:
            assert isinstance(call.args, dict)
            meta = requests.metadata.get(call.tool_call_id, {})
            await _send(
                ws,
                ApprovalRequest(
                    tool_call_id=call.tool_call_id,
                    tool=meta.get("tool", call.tool_name),
                    args=call.args,
                    classification=meta.get("classification", {}),
                    triggered_rules=meta.get("triggered_rules", []),
                    descriptions=meta.get("descriptions", []),
                ),
            )

        # Collect all approval responses
        pending = {call.tool_call_id for call in requests.approvals}
        while pending:
            raw = await ws.receive_json()
            try:
                client_msg = parse_client_message(raw)
            except (ValueError, Exception):
                continue
            if not isinstance(client_msg, ApprovalResponse):
                for tid in pending:
                    deferred_results.approvals[tid] = ToolDenied("Approval interrupted.")
                pending.clear()
                break
            if client_msg.tool_call_id in pending:
                if client_msg.approved:
                    deferred_results.approvals[client_msg.tool_call_id] = True
                else:
                    deferred_results.approvals[client_msg.tool_call_id] = ToolDenied("User denied this operation.")
                pending.discard(client_msg.tool_call_id)

        result = await agent.run(
            deps=deps,
            message_history=messages,
            deferred_tool_results=deferred_results,
        )
        deps.usage_tracker.record(model_name, "agent", result.usage())
        messages = result.all_messages()

    output: str
    if isinstance(result.output, str):
        output = result.output
        await _send(ws, Done(content=output))
    else:
        output = f"Unexpected agent output type: {type(result.output).__name__}"
        await _send(ws, ErrorMessage(detail=output))

    return messages, output


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

    for name in ("httpcore", "httpx", "docker", "anthropic", "websockets", "websockets.server", "urllib3"):
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
    token = ensure_token(data_dir)

    logger.info(f"Starting Carapace server on {config.server.host}:{config.server.port}")
    logger.info(f"Bearer token: {token[:8]}…  (full token in {data_dir / 'server.token'})")

    uvicorn.run(
        "carapace.server:app",
        host=config.server.host,
        port=config.server.port,
        log_level=config.carapace.log_level,
        log_config=None,
    )


if __name__ == "__main__":
    main()
