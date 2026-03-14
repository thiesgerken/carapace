from __future__ import annotations

import asyncio
import contextlib
import json
import secrets
import shutil
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import yaml
from loguru import logger
from pydantic_ai import ModelMessage, ModelMessagesTypeAdapter, ToolDenied

import carapace.security as security_mod
from carapace.agent_loop import run_agent_turn
from carapace.memory import MemoryStore
from carapace.models import Config, Deps, SessionState, SkillInfo, UsageTracker
from carapace.sandbox.manager import SandboxManager
from carapace.security.context import SessionSecurity, UserVouchedEntry
from carapace.security.sentinel import Sentinel
from carapace.ws_models import SLASH_COMMANDS, ApprovalRequest, ApprovalResponse, ProxyApprovalResponse, TurnUsage

# ---------------------------------------------------------------------------
# Subscriber protocol — channels (WebSocket, Matrix, …) implement this
# ---------------------------------------------------------------------------


@runtime_checkable
class SessionSubscriber(Protocol):
    async def on_user_message(self, content: str, *, from_self: bool) -> None: ...
    async def on_tool_call(self, tool: str, args: dict[str, Any], detail: str) -> None: ...
    async def on_tool_result(self, tool: str, result: str) -> None: ...
    async def on_done(self, content: str, usage: TurnUsage) -> None: ...
    async def on_error(self, detail: str) -> None: ...
    async def on_cancelled(self) -> None: ...
    async def on_approval_request(self, req: ApprovalRequest) -> None: ...
    async def on_proxy_approval_request(self, request_id: str, domain: str, command: str) -> None: ...
    async def on_title_update(self, title: str) -> None: ...
    async def on_domain_info(self, domain: str, detail: str) -> None: ...


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
    approval_queue: asyncio.Queue[ApprovalResponse | ProxyApprovalResponse | None] = field(
        default_factory=asyncio.Queue
    )
    usage_tracker: UsageTracker = field(default_factory=UsageTracker)
    verbose: bool = True
    pending_approval_requests: list[dict[str, Any]] = field(default_factory=list)
    pending_proxy_approvals: list[dict[str, Any]] = field(default_factory=list)
    _pending_sends: set[asyncio.Task[Any]] = field(default_factory=set)


class SessionManager:
    def __init__(self, data_dir: Path):
        self.sessions_dir = data_dir / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def create_session(self, channel_type: str = "cli", channel_ref: str = "") -> SessionState:
        now = datetime.now(tz=UTC)
        session_id = f"{now:%Y-%m-%d-%H-%M}-{secrets.token_hex(4)}"
        state = SessionState(
            session_id=session_id,
            channel_type=channel_type,
            channel_ref=channel_ref or None,
            created_at=now,
            last_active=now,
        )
        session_dir = self.sessions_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        self._save_state(state)
        return state

    def load_state(self, session_id: str) -> SessionState | None:
        """Load session state without mutating last_active."""
        state_path = self.sessions_dir / session_id / "state.yaml"
        if not state_path.exists():
            return None
        with open(state_path) as f:
            raw = yaml.safe_load(f)
        return SessionState.model_validate(raw)

    def resume_session(self, session_id: str) -> SessionState | None:
        state = self.load_state(session_id)
        if state is not None:
            state.last_active = datetime.now(tz=UTC)
        return state

    def list_sessions(self) -> list[str]:
        if not self.sessions_dir.exists():
            return []
        return sorted(
            [d.name for d in self.sessions_dir.iterdir() if d.is_dir()],
            key=lambda s: self._get_mtime(s),
            reverse=True,
        )

    def find_session(self, channel_type: str, channel_ref: str) -> str | None:
        """Return the most recently active session ID for the given channel, or None."""
        candidates: list[tuple[float, str]] = []
        for session_id in self.list_sessions():
            state = self.load_state(session_id)
            if state and state.channel_type == channel_type and state.channel_ref == channel_ref:
                candidates.append((self._get_mtime(session_id), session_id))
        if not candidates:
            return None
        return max(candidates, key=lambda t: t[0])[1]

    def _get_mtime(self, session_id: str) -> float:
        state_path = self.sessions_dir / session_id / "state.yaml"
        if state_path.exists():
            return state_path.stat().st_mtime
        return 0.0

    def delete_session(self, session_id: str) -> bool:
        session_dir = self.sessions_dir / session_id
        if session_dir.exists():
            shutil.rmtree(session_dir)
            return True
        return False

    def save_state(self, state: SessionState) -> None:
        self._save_state(state)

    def _save_state(self, state: SessionState) -> None:
        session_dir = self.sessions_dir / state.session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        state_path = session_dir / "state.yaml"
        with open(state_path, "w") as f:
            yaml.dump(state.model_dump(mode="json"), f, default_flow_style=False)

    def load_history(self, session_id: str) -> list[ModelMessage]:
        history_path = self.sessions_dir / session_id / "history.yaml"
        if not history_path.exists():
            # fallback to legacy JSON
            json_path = history_path.with_suffix(".json")
            if json_path.exists():
                return ModelMessagesTypeAdapter.validate_json(json_path.read_bytes())
            return []
        with open(history_path) as f:
            raw = yaml.safe_load(f)
        return ModelMessagesTypeAdapter.validate_python(raw or [])

    def save_history(self, session_id: str, messages: list[ModelMessage]) -> None:
        session_dir = self.sessions_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        history_path = session_dir / "history.yaml"
        data = ModelMessagesTypeAdapter.dump_python(messages, mode="json")
        with open(history_path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    # --- Usage tracking persistence ---

    def load_usage(self, session_id: str) -> UsageTracker:
        usage_path = self.sessions_dir / session_id / "usage.yaml"
        if not usage_path.exists():
            # fallback to legacy JSON
            json_path = usage_path.with_suffix(".json")
            if json_path.exists():
                return UsageTracker.model_validate_json(json_path.read_bytes())
            return UsageTracker()
        with open(usage_path) as f:
            raw = yaml.safe_load(f)
        return UsageTracker.model_validate(raw or {})

    def save_usage(self, session_id: str, tracker: UsageTracker) -> None:
        session_dir = self.sessions_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        usage_path = session_dir / "usage.yaml"
        with open(usage_path, "w") as f:
            yaml.dump(tracker.model_dump(mode="json"), f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    # --- Event log (ordered display history including slash commands) ---

    def load_events(self, session_id: str) -> list[dict[str, Any]]:
        events_path = self.sessions_dir / session_id / "events.yaml"
        if not events_path.exists():
            # fallback to legacy JSON
            json_path = events_path.with_suffix(".json")
            if json_path.exists():
                return json.loads(json_path.read_bytes())
            return []
        with open(events_path) as f:
            return yaml.safe_load(f) or []

    def append_events(self, session_id: str, events: list[dict[str, Any]]) -> None:
        session_dir = self.sessions_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        events_path = session_dir / "events.yaml"
        existing = self.load_events(session_id)
        existing.extend(events)
        with open(events_path, "w") as f:
            yaml.dump(existing, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


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
        security_md: str,
        session_mgr: SessionManager,
        skill_catalog: list[SkillInfo],
        agent_model: Any,
        sandbox_mgr: SandboxManager,
    ) -> None:
        self._config = config
        self._data_dir = data_dir
        self._security_md = security_md
        self._session_mgr = session_mgr
        self._skill_catalog = skill_catalog
        self._agent_model = agent_model
        self._sandbox_mgr = sandbox_mgr
        self._active: dict[str, ActiveSession] = {}
        self._llm_semaphore = asyncio.Semaphore(config.agent.max_parallel_llm)

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
    def agent_model(self) -> Any:
        return self._agent_model

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
            security_md=self._security_md,
            skills_dir=self._data_dir / "skills",
        )
        usage_tracker = self._session_mgr.load_usage(session_id)

        active = ActiveSession(
            state=state,
            security=security,
            sentinel=sentinel,
            usage_tracker=usage_tracker,
        )
        self._active[session_id] = active

        # Register in the global dicts so agent.py / agent_loop.py can
        # look up the session via security.evaluate / append_log / write_audit.
        security_mod._sessions[session_id] = security
        security_mod._sentinels[session_id] = sentinel
        security_mod._session_refs[session_id] = 1

        return active

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
        security_mod.destroy_session(session_id)

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
        tool_result_callback: Callable[[str, str], None] | None = None,
    ) -> Deps:
        return Deps(
            config=self._config,
            data_dir=self._data_dir,
            session_state=active.state,
            skill_catalog=self._skill_catalog,
            agent_model=self._agent_model,
            verbose=active.verbose,
            tool_call_callback=tool_call_callback,
            tool_result_callback=tool_result_callback,
            usage_tracker=active.usage_tracker,
            sandbox=self._sandbox_mgr,
            activated_skills=[],
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
        while not active.approval_queue.empty():
            active.approval_queue.get_nowait()

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
            active.approval_queue.put_nowait(None)
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await active.agent_task
            active.agent_task = None

    async def submit_approval(
        self,
        session_id: str,
        response: ApprovalResponse | ProxyApprovalResponse,
    ) -> None:
        """Forward an approval / proxy-approval response to the running turn."""
        active = self._active.get(session_id)
        if active:
            active.approval_queue.put_nowait(response)

    # -- slash commands --

    def handle_slash_command(self, session_id: str, command: str) -> dict[str, Any] | None:
        """Process a slash command, return structured data or ``None``."""
        active = self._active.get(session_id)
        if not active:
            return None

        parts = command.strip().split(maxsplit=1)
        cmd = parts[0].lower()

        if cmd == "/help":
            return {"command": "help", "data": {"commands": SLASH_COMMANDS}}

        if cmd == "/security":
            policy = self._security_md or "(no SECURITY.md loaded)"
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
            store = MemoryStore(self._data_dir)
            files = store.list_files()
            return {"command": "memory", "data": files}

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

        return None

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

        def _tool_result_cb(tool: str, result: str) -> None:
            self._session_mgr.append_events(
                session_id,
                [{"role": "tool_result", "tool": tool, "result": result}],
            )
            task = asyncio.ensure_future(self._broadcast(active, "on_tool_result", tool, result))
            active._pending_sends.add(task)
            task.add_done_callback(active._pending_sends.discard)

        # Wire up security callbacks for domain escalation / info
        if active.security:
            active.security.set_user_escalation_callback(self._make_domain_escalation_cb(active))
            active.security.set_domain_info_callback(self._make_domain_info_cb(active))

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
                    active.pending_approval_requests.append({"tool_call_id": req.tool_call_id, "tool": req.tool})
                    await self._broadcast(active, "on_approval_request", req)

                async def _collect_approvals(
                    pending: set[str],
                ) -> dict[str, bool | ToolDenied]:
                    results: dict[str, bool | ToolDenied] = {}
                    remaining = set(pending)
                    while remaining:
                        msg = await active.approval_queue.get()
                        if msg is None:
                            for tid in remaining:
                                results[tid] = ToolDenied("Agent cancelled.")
                            break
                        if not isinstance(msg, ApprovalResponse):
                            continue
                        if msg.tool_call_id in remaining:
                            results[msg.tool_call_id] = (
                                True if msg.approved else ToolDenied("User denied this operation.")
                            )
                            remaining.discard(msg.tool_call_id)
                    active.pending_approval_requests.clear()
                    return results

                async with self._llm_semaphore:
                    messages, output, (inp_tok, out_tok) = await run_agent_turn(
                        user_input,
                        deps,
                        message_history,
                        send_approval_request=_send_approval,
                        collect_approvals=_collect_approvals,
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
            await self._broadcast(active, "on_cancelled")
        except Exception as exc:
            logger.exception("Agent error")
            await self._broadcast(active, "on_error", str(exc))
        finally:
            active.agent_task = None

    async def _generate_title(self, active: ActiveSession, events: list[dict[str, Any]]) -> None:
        from carapace.titler import generate_title

        session_id = active.state.session_id
        try:
            title = await generate_title(
                events,
                model=self._config.agent.title_model,
                usage_tracker=active.usage_tracker,
            )
            if title:
                active.state.title = title
                self._session_mgr.save_state(active.state)
                await self._broadcast(active, "on_title_update", title)
        except Exception as exc:
            logger.warning(f"Title generation failed for {session_id}: {exc}")

    def _make_domain_escalation_cb(
        self,
        active: ActiveSession,
    ) -> Callable[[str, str, dict[str, Any]], Awaitable[bool]]:
        """Build a callback that broadcasts proxy-domain escalations to subscribers."""

        async def _escalate(session_id: str, domain: str, context: dict[str, Any]) -> bool:
            request_id = secrets.token_hex(8)
            cmd = context.get("command", "")
            self._session_mgr.append_events(
                session_id,
                [{"role": "proxy_approval", "request_id": request_id, "domain": domain, "command": cmd}],
            )
            active.pending_proxy_approvals.append({"request_id": request_id, "domain": domain})
            await self._broadcast(active, "on_proxy_approval_request", request_id, domain, cmd)
            # Block until a subscriber responds
            while True:
                msg = await active.approval_queue.get()
                if msg is None:
                    active.pending_proxy_approvals.clear()
                    return False
                if isinstance(msg, ProxyApprovalResponse) and msg.request_id == request_id:
                    decision = msg.decision
                    self._session_mgr.append_events(
                        session_id,
                        [
                            {
                                "role": "proxy_approval",
                                "request_id": request_id,
                                "domain": domain,
                                "command": cmd,
                                "decision": decision,
                            }
                        ],
                    )
                    active.pending_proxy_approvals = [
                        p for p in active.pending_proxy_approvals if p["request_id"] != request_id
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
