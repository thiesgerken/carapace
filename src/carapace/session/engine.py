from __future__ import annotations

import asyncio
import contextlib
import secrets
import traceback
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

from loguru import logger
from pydantic_ai import ToolDenied
from pydantic_ai.messages import ModelRequest, UserPromptPart
from pydantic_ai.models import Model, infer_model

import carapace.security as security_mod
from carapace.agent.loop import run_agent_turn
from carapace.git.store import GitStore
from carapace.memory import MemoryStore
from carapace.models import Config, Deps, SessionState, SkillInfo, ToolResult
from carapace.sandbox.manager import SandboxManager
from carapace.security.context import SessionSecurity, UserVouchedEntry
from carapace.security.sentinel import Sentinel
from carapace.session.manager import SessionManager
from carapace.session.titler import generate_title
from carapace.skills import SkillRegistry
from carapace.usage import UsageTracker
from carapace.ws_models import (
    SLASH_COMMANDS,
    ApprovalRequest,
    ApprovalResponse,
    CredentialApprovalResponse,
    EscalationResponse,
    TurnUsage,
)

ModelType = Literal["agent", "sentinel", "title"]

# security_mod is still imported for evaluate_domain_with (used in domain approval callback)

# ---------------------------------------------------------------------------
# Subscriber protocol — channels (WebSocket, Matrix, …) implement this
# ---------------------------------------------------------------------------


@runtime_checkable
class SessionSubscriber(Protocol):
    async def on_user_message(self, content: str, *, from_self: bool) -> None: ...
    async def on_tool_call(self, tool: str, args: dict[str, Any], detail: str) -> None: ...
    async def on_tool_result(self, result: ToolResult) -> None: ...
    async def on_token(self, content: str) -> None: ...
    async def on_done(self, content: str, usage: TurnUsage) -> None: ...
    async def on_error(self, detail: str) -> None: ...
    async def on_cancelled(self) -> None: ...
    async def on_approval_request(self, req: ApprovalRequest) -> None: ...
    async def on_domain_access_approval_request(self, request_id: str, domain: str, command: str) -> None: ...
    async def on_git_push_approval_request(
        self, request_id: str, ref: str, explanation: str, changed_files: list[str]
    ) -> None: ...
    async def on_title_update(self, title: str) -> None: ...
    async def on_domain_info(self, domain: str, detail: str) -> None: ...
    async def on_git_push_info(self, ref: str, decision: str, detail: str) -> None: ...
    async def on_credential_approval_request(
        self,
        vault_paths: list[str],
        names: list[str],
        descriptions: list[str],
        skill_name: str | None,
        explanation: str,
    ) -> None: ...


# ---------------------------------------------------------------------------
# ActiveSession — in-memory state for a session that is currently loaded
# ---------------------------------------------------------------------------


@dataclass
class ActiveSession:
    state: SessionState
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    security: SessionSecurity | None = None
    sentinel: Sentinel | None = None
    agent_task: asyncio.Task[None] | None = None
    subscribers: list[SessionSubscriber] = field(default_factory=list)
    tool_approval_queue: asyncio.Queue[ApprovalResponse | None] = field(default_factory=asyncio.Queue)
    escalation_queue: asyncio.Queue[EscalationResponse | None] = field(default_factory=asyncio.Queue)
    usage_tracker: UsageTracker = field(default_factory=UsageTracker)
    verbose: bool = True
    agent_model: Model | None = None
    agent_model_name: str | None = None
    sentinel_model_name: str | None = None
    title_model_name: str | None = None
    pending_approval_requests: list[dict[str, Any]] = field(default_factory=list)
    pending_escalations: list[dict[str, Any]] = field(default_factory=list)
    pending_credential_approvals: list[dict[str, Any]] = field(default_factory=list)
    credential_approval_queue: asyncio.Queue[CredentialApprovalResponse | None] = field(default_factory=asyncio.Queue)
    _pending_sends: set[asyncio.Task[Any]] = field(default_factory=set)


# ---------------------------------------------------------------------------
# SessionEngine — central owner of session lifecycle and agent execution
# ---------------------------------------------------------------------------


class SessionEngine:
    """Central session lifecycle manager.

    Owns all in-memory session state, security sessions, and agent execution.
    Channels (WebSocket, Matrix, …) subscribe to events and submit messages
    through this class.  Agent turns survive transport disconnects, and LLM
    concurrency is bounded by a shared semaphore.
    """

    def __init__(
        self,
        *,
        config: Config,
        data_dir: Path,
        knowledge_dir: Path,
        git_store: GitStore,
        session_mgr: SessionManager,
        skill_catalog: list[SkillInfo],
        agent_model: Model | None,
        sandbox_mgr: SandboxManager,
        model_factory: Callable[[str], Model] | None = None,
    ) -> None:
        self._config = config
        self._data_dir = data_dir
        self._knowledge_dir = knowledge_dir
        self._git_store = git_store
        self._session_mgr = session_mgr
        self._skill_catalog = skill_catalog
        self._agent_model = agent_model
        self._sandbox_mgr = sandbox_mgr
        self._model_factory = model_factory
        self._credential_registry: Any = None
        self._active: dict[str, ActiveSession] = {}
        self._llm_semaphore = asyncio.Semaphore(config.agent.max_parallel_llm)

        # Let SandboxManager retrieve activated skills for venv rebuild on container recreation
        sandbox_mgr.set_activated_skills_callback(self._get_activated_skills)

    def set_credential_registry(self, registry: Any) -> None:
        self._credential_registry = registry

    # -- public access to file I/O manager --

    @property
    def session_mgr(self) -> SessionManager:
        return self._session_mgr

    @property
    def config(self) -> Config:
        return self._config

    @property
    def data_dir(self) -> Path:
        return self._data_dir

    @property
    def skill_catalog(self) -> list[SkillInfo]:
        return self._skill_catalog

    @property
    def sandbox_mgr(self) -> SandboxManager:
        return self._sandbox_mgr

    @property
    def agent_model(self) -> Model | None:
        return self._agent_model

    @property
    def available_models(self) -> list[str]:
        return self._available_models()

    def _resolve_model(self, name: str) -> Model:
        """Create a Model from a name, using the model_factory if available."""
        return self._model_factory(name) if self._model_factory else infer_model(name)

    # -- session lifecycle --

    def _ensure_active(self, session_id: str) -> ActiveSession:
        """Return or create the in-memory ``ActiveSession`` for *session_id*."""
        if session_id in self._active:
            return self._active[session_id]

        state = self._session_mgr.resume_session(session_id)
        if state is None:
            raise KeyError(f"Session {session_id} not found on disk")

        audit_dir = self._data_dir / "sessions" / session_id
        security = SessionSecurity(session_id, audit_dir=audit_dir)
        sentinel = Sentinel(
            model=self._config.agent.sentinel_model,
            knowledge_dir=self._knowledge_dir,
            skills_dir=self._knowledge_dir / "skills",
        )
        usage_tracker = self._session_mgr.load_usage(session_id)

        active = ActiveSession(
            state=state,
            security=security,
            sentinel=sentinel,
            usage_tracker=usage_tracker,
        )
        self._active[session_id] = active

        # Wire security callbacks so domain escalation / info works
        # even outside an agent turn (e.g. during sandbox setup).
        security.set_user_escalation_callback(self._make_escalation_cb(active))
        security.set_domain_info_callback(self._make_domain_info_cb(active))
        security.set_push_info_callback(self._make_push_info_cb(active))

        # Register a domain-approval callback so the sandbox proxy can
        # evaluate domain requests through the per-session sentinel.
        self._sandbox_mgr.set_domain_approval_callback(
            session_id,
            self._make_domain_eval_cb(security, sentinel, active),
        )

        return active

    def _get_activated_skills(self, session_id: str) -> list[str]:
        """Return activated skills for a session (from in-memory state or disk)."""
        active = self._active.get(session_id)
        if active:
            return list(active.state.activated_skills)
        state = self._session_mgr.load_state(session_id)
        if state:
            return list(state.activated_skills)
        return []

    def get_active(self, session_id: str) -> ActiveSession | None:
        """Return the ``ActiveSession`` if loaded, else ``None``."""
        return self._active.get(session_id)

    def get_or_activate(self, session_id: str) -> ActiveSession:
        """Return (or load) the ``ActiveSession``."""
        return self._ensure_active(session_id)

    def deactivate(self, session_id: str) -> None:
        """Remove in-memory state when a session is no longer needed."""
        active = self._active.pop(session_id, None)
        if active and active.agent_task and not active.agent_task.done():
            active.agent_task.cancel()
        self._sandbox_mgr.set_domain_approval_callback(session_id, None)

    # -- subscribers --

    def subscribe(self, session_id: str, sub: SessionSubscriber) -> ActiveSession:
        """Attach a subscriber and return the ``ActiveSession``."""
        active = self._ensure_active(session_id)
        if sub not in active.subscribers:
            active.subscribers.append(sub)
        return active

    def unsubscribe(self, session_id: str, sub: SessionSubscriber) -> None:
        """Detach a subscriber.  Does NOT cancel agent work or destroy security."""
        active = self._active.get(session_id)
        if active:
            with contextlib.suppress(ValueError):
                active.subscribers.remove(sub)
            # When all subscribers disconnect and no task is running we can
            # flush usage to disk, but keep the active session alive.
            if not active.subscribers and (active.agent_task is None or active.agent_task.done()):
                self._session_mgr.save_usage(session_id, active.usage_tracker)

    # -- broadcasting helpers --

    async def _broadcast(
        self,
        active: ActiveSession,
        method: str,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        for sub in list(active.subscribers):
            try:
                await getattr(sub, method)(*args, **kwargs)
            except Exception as exc:
                logger.warning(f"Subscriber broadcast {method} failed: {exc}")

    # -- agent execution --

    def _build_deps(
        self,
        active: ActiveSession,
        *,
        tool_call_callback: Callable[[str, dict[str, Any], str], None] | None = None,
        tool_result_callback: Callable[[ToolResult], None] | None = None,
    ) -> Deps:
        assert active.security is not None and active.sentinel is not None
        return Deps(
            config=self._config,
            data_dir=self._data_dir,
            knowledge_dir=self._knowledge_dir,
            session_state=active.state,
            security=active.security,
            sentinel=active.sentinel,
            git_store=self._git_store,
            skill_catalog=self._skill_catalog,
            agent_model=active.agent_model or self._agent_model or self._resolve_model(self._config.agent.model),
            verbose=active.verbose,
            tool_call_callback=tool_call_callback,
            tool_result_callback=tool_result_callback,
            usage_tracker=active.usage_tracker,
            sandbox=self._sandbox_mgr,
            activated_skills=[],
            credential_registry=self._credential_registry,
        )

    async def submit_message(
        self,
        session_id: str,
        content: str,
        *,
        origin: SessionSubscriber | None = None,
    ) -> None:
        """Start an agent turn.  Safe to call from any channel."""
        active = self._ensure_active(session_id)

        if active.agent_task and not active.agent_task.done():
            await self._broadcast(active, "on_error", "Agent is busy — cancel first")
            return

        # Drain leftover approval responses
        while not active.tool_approval_queue.empty():
            active.tool_approval_queue.get_nowait()
        while not active.escalation_queue.empty():
            active.escalation_queue.get_nowait()

        active.agent_task = asyncio.create_task(
            self._run_turn(active, content, origin=origin),
            name=f"agent-turn-{session_id}",
        )

    async def submit_cancel(self, session_id: str) -> None:
        """Cancel the running agent turn for *session_id*."""
        active = self._active.get(session_id)
        if not active:
            return
        if active.agent_task and not active.agent_task.done():
            active.agent_task.cancel()
            active.tool_approval_queue.put_nowait(None)
            active.escalation_queue.put_nowait(None)
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await active.agent_task
            active.agent_task = None

    async def submit_approval(
        self,
        session_id: str,
        response: ApprovalResponse | EscalationResponse | CredentialApprovalResponse,
    ) -> None:
        """Forward an approval / escalation / credential response to the running turn."""
        active = self._active.get(session_id)
        if active:
            if isinstance(response, ApprovalResponse):
                active.tool_approval_queue.put_nowait(response)
            elif isinstance(response, CredentialApprovalResponse):
                active.credential_approval_queue.put_nowait(response)
            else:
                active.escalation_queue.put_nowait(response)

    async def request_credential_approval(
        self,
        session_id: str,
        vault_paths: list[str],
        names: list[str],
        descriptions: list[str],
        *,
        skill_name: str | None = None,
        explanation: str = "",
    ) -> bool:
        """Send a credential approval request to subscribers and block until resolved.

        Returns ``True`` if the user approved, ``False`` if denied.
        """
        active = self._active.get(session_id)
        if not active:
            return False

        pending = {
            "vault_paths": vault_paths,
            "names": names,
            "descriptions": descriptions,
            "skill_name": skill_name,
        }
        active.pending_credential_approvals.append(pending)

        await self._broadcast(
            active,
            "on_credential_approval_request",
            vault_paths,
            names,
            descriptions,
            skill_name,
            explanation,
        )

        # Block until a matching response arrives
        while True:
            msg = await active.credential_approval_queue.get()
            if msg is None:
                active.pending_credential_approvals = [
                    p for p in active.pending_credential_approvals if p["vault_paths"] != vault_paths
                ]
                return False
            if set(msg.vault_paths) == set(vault_paths):
                active.pending_credential_approvals = [
                    p for p in active.pending_credential_approvals if p["vault_paths"] != vault_paths
                ]
                return msg.decision == "approved"

    # -- slash commands --

    async def handle_slash_command(self, session_id: str, command: str) -> dict[str, Any] | None:
        """Process a slash command, return structured data or ``None``."""
        active = self._active.get(session_id)
        if not active:
            return None

        parts = command.strip().split(maxsplit=1)
        cmd = parts[0].lower()

        if cmd == "/help":
            return {"command": "help", "data": {"commands": SLASH_COMMANDS}}

        if cmd == "/security":
            security_path = self._knowledge_dir / "SECURITY.md"
            policy = security_path.read_text() if security_path.exists() else "(no SECURITY.md loaded)"
            log_count = len(active.security.action_log) if active.security else 0
            eval_count = active.security.sentinel_eval_count if active.security else 0
            return {
                "command": "security",
                "data": {
                    "policy_preview": policy[:500] + ("..." if len(policy) > 500 else ""),
                    "action_log_entries": log_count,
                    "sentinel_evaluations": eval_count,
                },
            }

        if cmd == "/approve-context":
            if active.security:
                active.security.append(UserVouchedEntry())
            return {
                "command": "approve-context",
                "data": {"message": "Recorded: you vouch for the current agent context as trustworthy."},
            }

        if cmd == "/session":
            return {
                "command": "session",
                "data": {
                    "session_id": session_id,
                    "channel_type": active.state.channel_type,
                    "approved_credentials": active.state.approved_credentials,
                    "allowed_domains": self._sandbox_mgr.get_domain_info(session_id),
                },
            }

        if cmd == "/skills":
            skills = [{"name": s.name, "description": s.description.strip()} for s in self._skill_catalog]
            return {"command": "skills", "data": skills}

        if cmd == "/memory":
            store = MemoryStore(self._knowledge_dir)
            files = store.list_files()
            return {"command": "memory", "data": files}

        if cmd == "/models":
            return self._handle_models_command(active)

        if cmd in ("/model", "/model-sentinel", "/model-title"):
            model_map: dict[str, ModelType] = {
                "/model": "agent",
                "/model-sentinel": "sentinel",
                "/model-title": "title",
            }
            model_type = model_map[cmd]
            return await self._handle_model_command(active, model_type, parts[1].strip() if len(parts) > 1 else "")

        if cmd == "/usage":
            tracker = active.usage_tracker
            costs = tracker.estimated_cost()
            return {
                "command": "usage",
                "data": {
                    "models": {k: v.model_dump() for k, v in tracker.models.items()},
                    "categories": {k: v.model_dump() for k, v in tracker.categories.items()},
                    "total_input": tracker.total_input,
                    "total_output": tracker.total_output,
                    "costs": {k: str(v) for k, v in costs.items()},
                },
            }

        if cmd == "/pull":
            return await self._handle_pull_command()

        if cmd == "/push":
            return await self._handle_push_command()

        if cmd == "/reload":
            return await self._handle_reload_command(session_id)

        return None

    # -- pull / push from/to remote --

    async def _handle_push_command(self) -> dict[str, Any]:
        """Handle the ``/push`` slash command — push to external remote."""
        if not self._config.git.remote:
            return {"command": "push", "data": {"message": "No external remote configured."}}
        try:
            await self._git_store.push_to_remote()
            return {"command": "push", "data": {"message": "Pushed to external remote."}}
        except Exception as exc:
            return {"command": "push", "data": {"message": f"Push failed: {exc}"}}

    async def _handle_pull_command(self) -> dict[str, Any]:
        """Handle the ``/pull`` slash command — pull from external remote."""
        if not self._config.git.remote:
            return {"command": "pull", "data": {"message": "No external remote configured."}}
        try:
            summary = await self._git_store.pull_from_remote()
            # Re-scan skills after pull
            registry = SkillRegistry(self._knowledge_dir / "skills")
            self._skill_catalog = registry.scan()
            return {"command": "pull", "data": {"message": summary}}
        except RuntimeError as exc:
            return {"command": "pull", "data": {"message": f"Pull failed: {exc}"}}

    async def _handle_reload_command(self, session_id: str) -> dict[str, Any]:
        """Handle the ``/reload`` slash command — reset the sandbox completely."""
        try:
            await self._sandbox_mgr.reset_session(session_id)
            return {
                "command": "reload",
                "data": {
                    "message": ("Sandbox reset. A fresh workspace will be created from Git on the next command."),
                },
            }
        except Exception as exc:
            return {"command": "reload", "data": {"message": f"Reload failed: {exc}"}}

    # -- model switching --

    _MODEL_TYPES: tuple[ModelType, ...] = ("agent", "sentinel", "title")

    def _handle_models_command(self, active: ActiveSession) -> dict[str, Any]:
        """Show all model types with their current and default values."""
        defaults = {
            "agent": self._config.agent.model,
            "sentinel": self._config.agent.sentinel_model,
            "title": self._config.agent.title_model,
        }
        overrides = {
            "agent": active.agent_model_name,
            "sentinel": active.sentinel_model_name,
            "title": active.title_model_name,
        }
        models = {t: {"current": overrides[t] or defaults[t], "default": defaults[t]} for t in self._MODEL_TYPES}
        available = self._available_models()
        return {"command": "models", "data": {"models": models, "available": available}}

    async def _handle_model_command(self, active: ActiveSession, model_type: ModelType, arg: str) -> dict[str, Any]:
        """Process ``/model[-(sentinel|title)] [MODEL | reset]``."""
        cmd_name = {"agent": "model", "sentinel": "model-sentinel", "title": "model-title"}[model_type]
        defaults = {
            "agent": self._config.agent.model,
            "sentinel": self._config.agent.sentinel_model,
            "title": self._config.agent.title_model,
        }
        overrides = {
            "agent": active.agent_model_name,
            "sentinel": active.sentinel_model_name,
            "title": active.title_model_name,
        }
        default = defaults[model_type]
        current = overrides[model_type] or default

        # No argument — show current
        if not arg:
            return {"command": cmd_name, "data": {"current": current, "default": default}}

        # Reset
        if arg == "reset":
            self._apply_model_override(active, model_type, None, None)
            if model_type == "title":
                await self._regenerate_title(active)
            return {
                "command": cmd_name,
                "data": {"current": default, "default": default, "message": f"Reset to default: {default}"},
            }

        # Switch
        try:
            new_model = self._model_factory(arg) if self._model_factory else infer_model(arg)
        except Exception as exc:
            return {"command": cmd_name, "data": {"current": current, "default": default, "error": str(exc)}}

        self._apply_model_override(active, model_type, arg, new_model if model_type == "agent" else None)
        if model_type == "title":
            await self._regenerate_title(active)
        return {
            "command": cmd_name,
            "data": {"current": arg, "default": default, "message": f"Switched to: {arg}"},
        }

    def _apply_model_override(
        self, active: ActiveSession, model_type: ModelType, name: str | None, model_obj: Model | None = None
    ) -> None:
        if model_type == "agent":
            active.agent_model = model_obj
            active.agent_model_name = name
        elif model_type == "sentinel":
            active.sentinel_model_name = name
            if active.sentinel:
                active.sentinel.set_model(name or self._config.agent.sentinel_model)
        elif model_type == "title":
            active.title_model_name = name

    async def _regenerate_title(self, active: ActiveSession) -> None:
        """Regenerate the session title using the current title model."""
        session_id = active.state.session_id
        events = self._session_mgr.load_events(session_id)
        if events:
            await self._generate_title(active, events)

    def _available_models(self) -> list[str]:
        """Return deduplicated sorted list of available models."""
        return sorted(
            {
                self._config.agent.model,
                self._config.agent.sentinel_model,
                self._config.agent.title_model,
                *self._config.agent.available_models,
            }
        )

    # -- internal turn runner --

    async def _run_turn(
        self,
        active: ActiveSession,
        user_input: str,
        *,
        origin: SessionSubscriber | None = None,
    ) -> None:
        """Execute a single agent turn with semaphore-bounded LLM access."""
        session_id = active.state.session_id

        def _tool_call_cb(tool: str, args: dict[str, Any], detail: str) -> None:
            self._session_mgr.append_events(
                session_id,
                [{"role": "tool_call", "tool": tool, "args": args, "detail": detail}],
            )
            task = asyncio.ensure_future(self._broadcast(active, "on_tool_call", tool, args, detail))
            active._pending_sends.add(task)
            task.add_done_callback(active._pending_sends.discard)

        def _tool_result_cb(tr: ToolResult) -> None:
            self._session_mgr.append_events(
                session_id,
                [{"role": "tool_result", "tool": tr.tool, "result": tr.output, "exit_code": tr.exit_code}],
            )
            task = asyncio.ensure_future(self._broadcast(active, "on_tool_result", tr))
            active._pending_sends.add(task)
            task.add_done_callback(active._pending_sends.discard)

        try:
            async with active.lock:
                # Refresh state from disk (other channels may have updated it)
                fresh = self._session_mgr.resume_session(session_id)
                if fresh:
                    active.state = fresh

                deps = self._build_deps(
                    active,
                    tool_call_callback=_tool_call_cb,
                    tool_result_callback=_tool_result_cb,
                )

                self._session_mgr.append_events(session_id, [{"role": "user", "content": user_input}])
                for sub in list(active.subscribers):
                    try:
                        await sub.on_user_message(user_input, from_self=(sub is origin))
                    except Exception as exc:
                        logger.warning(f"Subscriber on_user_message failed: {exc}")
                message_history = self._session_mgr.load_history(session_id)

                async def _send_approval(req: ApprovalRequest) -> None:
                    self._session_mgr.append_events(
                        session_id,
                        [
                            {
                                "role": "approval_request",
                                "tool_call_id": req.tool_call_id,
                                "tool": req.tool,
                                "args": req.args,
                                "explanation": req.explanation,
                                "risk_level": req.risk_level,
                            }
                        ],
                    )
                    active.pending_approval_requests.append(req.model_dump())
                    await self._broadcast(active, "on_approval_request", req)

                async def _collect_approvals(
                    pending: set[str],
                ) -> dict[str, bool | ToolDenied]:
                    results: dict[str, bool | ToolDenied] = {}
                    remaining = set(pending)
                    while remaining:
                        msg = await active.tool_approval_queue.get()
                        if msg is None:
                            for tid in remaining:
                                results[tid] = ToolDenied("Agent cancelled.")
                            break
                        if msg.tool_call_id in remaining:
                            results[msg.tool_call_id] = (
                                True if msg.approved else ToolDenied("User denied this operation.")
                            )
                            remaining.discard(msg.tool_call_id)
                    # Store approval decisions in events for history reconstruction
                    for tool_call_id, decision in results.items():
                        user_decision = "approved" if decision is True else "denied"
                        self._session_mgr.append_events(
                            session_id,
                            [{"role": "approval_response", "tool_call_id": tool_call_id, "decision": user_decision}],
                        )
                    active.pending_approval_requests.clear()
                    return results

                async def _on_token(chunk: str) -> None:
                    await self._broadcast(active, "on_token", chunk)

                async with self._llm_semaphore:
                    messages, output, (inp_tok, out_tok) = await run_agent_turn(
                        user_input,
                        deps,
                        message_history,
                        send_approval_request=_send_approval,
                        collect_approvals=_collect_approvals,
                        on_token=_on_token,
                    )

                self._session_mgr.save_history(session_id, messages)
                self._session_mgr.save_state(active.state)
                self._session_mgr.save_usage(session_id, active.usage_tracker)
                self._session_mgr.append_events(
                    session_id,
                    [{"role": "assistant", "content": output}],
                )

                if output.startswith("Unexpected agent output type:"):
                    await self._broadcast(active, "on_error", output)
                else:
                    await self._broadcast(
                        active,
                        "on_done",
                        output,
                        TurnUsage(input_tokens=inp_tok, output_tokens=out_tok),
                    )

                # Generate a title after the 1st and 3rd user message
                events = self._session_mgr.load_events(session_id)
                user_msg_count = sum(1 for e in events if e.get("role") == "user")
                if user_msg_count in (1, 3):
                    t = asyncio.create_task(
                        self._generate_title(active, events),
                        name=f"title-{session_id}",
                    )
                    active._pending_sends.add(t)
                    t.add_done_callback(active._pending_sends.discard)

        except asyncio.CancelledError:
            logger.info(f"Agent turn cancelled for session {session_id}")
            self._session_mgr.save_usage(session_id, active.usage_tracker)
            self._save_user_message_on_failure(session_id, user_input)
            await self._broadcast(active, "on_cancelled")
        except Exception:
            logger.exception("Agent error")
            self._save_user_message_on_failure(session_id, user_input)
            await self._broadcast(active, "on_error", traceback.format_exc())
        finally:
            active.agent_task = None

    def _save_user_message_on_failure(self, session_id: str, user_input: str) -> None:
        """Persist the user message to history even when the agent turn fails.

        Without this the next turn would load stale history and the agent would
        have no memory of what the user said before the error.
        """
        history = self._session_mgr.load_history(session_id)
        history.append(ModelRequest(parts=[UserPromptPart(content=user_input)]))
        self._session_mgr.save_history(session_id, history)

    async def _generate_title(self, active: ActiveSession, events: list[dict[str, Any]]) -> None:
        session_id = active.state.session_id
        try:
            title = await generate_title(
                events,
                model=active.title_model_name or self._config.agent.title_model,
                usage_tracker=active.usage_tracker,
            )
            if title:
                active.state.title = title
                self._session_mgr.save_state(active.state)
                await self._broadcast(active, "on_title_update", title)
        except Exception as exc:
            logger.warning(f"Title generation failed for {session_id}: {exc}")

    def _make_escalation_cb(
        self,
        active: ActiveSession,
    ) -> Callable[[str, str, dict[str, Any]], Awaitable[bool]]:
        """Build a callback that broadcasts sentinel escalations (proxy domain or git push) to subscribers."""

        async def _escalate(session_id: str, subject: str, context: dict[str, Any]) -> bool:
            request_id = secrets.token_hex(8)
            cmd = context.get("command", "")
            kind = context.get("kind", "domain_access")

            # Auto-deny stale pending escalations of the same kind+key.
            # This happens when an exec timeout killed git push but the old
            # escalation callback is still blocked on the queue.
            match_key = "ref" if kind == "git_push" else "domain"
            match_val = context.get(match_key, subject)
            for old in list(active.pending_escalations):
                if old.get("kind") == kind and old.get(match_key) == match_val:
                    logger.info(f"Superseding stale {kind} escalation {old['request_id']} for {match_val}")
                    active.escalation_queue.put_nowait(
                        EscalationResponse(request_id=old["request_id"], decision="deny")
                    )

            if kind == "git_push":
                ref = context.get("ref", subject)
                explanation = context.get("explanation", "")
                changed_files: list[str] = context.get("changed_files", [])
                self._session_mgr.append_events(
                    session_id,
                    [
                        {
                            "role": "git_push_approval",
                            "request_id": request_id,
                            "ref": ref,
                            "explanation": explanation,
                            "changed_files": changed_files,
                        }
                    ],
                )
                active.pending_escalations.append(
                    {
                        "request_id": request_id,
                        "kind": "git_push",
                        "ref": ref,
                        "explanation": explanation,
                        "changed_files": changed_files,
                    }
                )
                await self._broadcast(
                    active, "on_git_push_approval_request", request_id, ref, explanation, changed_files
                )
            else:
                self._session_mgr.append_events(
                    session_id,
                    [{"role": "domain_access_approval", "request_id": request_id, "domain": subject, "command": cmd}],
                )
                active.pending_escalations.append(
                    {"request_id": request_id, "kind": "domain_access", "domain": subject, "command": cmd}
                )
                await self._broadcast(active, "on_domain_access_approval_request", request_id, subject, cmd)
            # Block until a subscriber responds
            while True:
                msg = await active.escalation_queue.get()
                if msg is None:
                    active.pending_escalations.clear()
                    return False
                if msg.request_id == request_id:
                    decision = msg.decision
                    event_role = "git_push_approval" if kind == "git_push" else "domain_access_approval"
                    self._session_mgr.append_events(
                        session_id,
                        [
                            {
                                "role": event_role,
                                "request_id": request_id,
                                "domain": subject,
                                "command": cmd,
                                "decision": decision,
                            }
                        ],
                    )
                    active.pending_escalations = [
                        p for p in active.pending_escalations if p["request_id"] != request_id
                    ]
                    return decision != "deny"

        return _escalate

    def _make_domain_info_cb(self, active: ActiveSession) -> Callable[[str, str], None]:
        """Build a callback that broadcasts domain access decisions to subscribers."""

        def _notify(domain: str, detail: str) -> None:
            task = asyncio.ensure_future(self._broadcast(active, "on_domain_info", domain, detail))
            active._pending_sends.add(task)
            task.add_done_callback(active._pending_sends.discard)

        return _notify

    def _make_push_info_cb(
        self,
        active: ActiveSession,
    ) -> Callable[[str, str, str], Awaitable[None]]:
        """Build a callback that broadcasts git push decisions to subscribers."""
        session_id = active.state.session_id

        async def _notify(ref: str, decision: str, detail: str) -> None:
            self._session_mgr.append_events(
                session_id,
                [{"role": "git_push", "ref": ref, "decision": decision, "detail": detail}],
            )
            await self._broadcast(active, "on_git_push_info", ref, decision, detail)

        return _notify

    def _make_domain_eval_cb(
        self,
        security: SessionSecurity,
        sentinel: Sentinel,
        active: ActiveSession,
    ) -> Callable[[str, str], Awaitable[bool]]:
        """Build a callback for SandboxManager.request_domain_approval."""

        async def _eval(domain: str, command: str) -> bool:
            return await security_mod.evaluate_domain_with(
                security,
                sentinel,
                domain,
                command,
                usage_tracker=active.usage_tracker,
            )

        return _eval
