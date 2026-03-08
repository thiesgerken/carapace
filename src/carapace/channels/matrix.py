"""Matrix channel adapter for Carapace.

Connects to a Matrix homeserver via matrix-nio (plain-text, no E2EE for now).
Maps one session per room; supports slash commands including /reset.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import time
from pathlib import Path
from typing import Any

import markdown as md
import nio
from loguru import logger
from pydantic_ai import ToolDenied

import carapace.security as security_mod
from carapace.agent_loop import run_agent_turn
from carapace.models import Config, Deps, MatrixChannelConfig, SessionState, SkillInfo, UsageTracker
from carapace.sandbox.manager import SandboxManager
from carapace.session import SessionManager
from carapace.ws_models import ApprovalRequest, CommandResult

# Reactions used for approval decisions
_APPROVE_REACTIONS = {"✅", "👍", "✓", "✔", "✔️", "👍🏻", "👍🏼", "👍🏽", "👍🏾", "👍🏿"}
_DENY_REACTIONS = {"❌", "👎", "✗", "🚫", "👎🏻", "👎🏼", "👎🏽", "👎🏾", "👎🏿"}

# Commands that mean "approve" or "deny"
_APPROVE_COMMANDS = {"/allow", "/yes"}
_DENY_COMMANDS = {"/deny", "/no"}

# Typing notification interval in seconds
_TYPING_INTERVAL = 10.0


def _md_to_html(text: str) -> str:
    """Convert markdown text to HTML for Matrix rich-text messages."""
    return md.markdown(text, extensions=["fenced_code", "tables"])


def _format_command_result_text(result: CommandResult) -> str:
    """Render a CommandResult as plain text suitable for a Matrix message."""
    data = result.data

    match result.command:
        case "help":
            lines = ["**Available commands:**\n"]
            for entry in data.get("commands", []):
                lines.append(f"- `{entry['command']}` — {entry['description']}")
            return "\n".join(lines)

        case "security":
            lines = [
                "**Security Policy:**\n",
                data.get("policy_preview", "(none)"),
                f"\nAction log entries: {data.get('action_log_entries', 0)}",
                f"Bouncer evaluations: {data.get('bouncer_evaluations', 0)}",
            ]
            return "\n".join(lines)

        case "approve-context":
            return data.get("message", "Context approved.")

        case "session":
            creds = data.get("approved_credentials") or []
            domain_entries: list[dict[str, str]] = data.get("allowed_domains") or []
            if domain_entries:
                domains_str = "\n" + "\n".join(f"  - `{e['domain']}` ({e['scope']})" for e in domain_entries)
            else:
                domains_str = " (none)"
            lines = [
                f"**Session:** `{data.get('session_id', '?')}`",
                f"**Channel:** {data.get('channel_type', '?')}",
                f"**Approved credentials:** {', '.join(creds) if creds else '(none)'}",
                f"**Allowed domains:**{domains_str}",
            ]
            return "\n".join(lines)

        case "skills":
            if not data:
                return "No skills available."
            lines = ["**Skills:**\n"]
            for s in data:
                lines.append(f"- **{s['name']}** — {s['description']}")
            return "\n".join(lines)

        case "memory":
            if not data:
                return "No memory files."
            lines = ["**Memory files:**\n"]
            for f in data:
                lines.append(f"- {f}")
            return "\n".join(lines)

        case "usage":
            costs = data.get("costs", {})
            total = costs.get("total", "?")
            lines = [f"**Token usage** (est. total: {total} USD)\n"]
            for model, usage in data.get("models", {}).items():
                inp = usage.get("input_tokens", 0)
                out = usage.get("output_tokens", 0)
                lines.append(f"- `{model}`: {inp} in / {out} out")
            return "\n".join(lines)

        case _:
            return f"Command result: {json.dumps(data, indent=2, default=str)}"


def _format_domain_escalation(domain: str, command: str, explanation: str) -> str:
    """Format a bouncer-escalated domain request as a Matrix message."""
    parts = [
        f"**🌐 Network Access Request** — domain: `{domain}`",
        f"**Command:** `{command}`",
    ]
    if explanation:
        parts.append(f"**Reason:** {explanation}")
    parts.append(
        "\nThe security bouncer escalated this domain request.\n"
        "React ✅ or type `/allow` / `/yes` to allow.\n"
        "React ❌ or type `/deny` / `/no` to deny."
    )
    return "\n".join(parts)


def _format_approval_request(req: ApprovalRequest) -> str:
    """Format an approval request as a Matrix message."""
    args_text = json.dumps(req.args, indent=2, default=str)

    parts = [
        f"**⚠️ Approval Required** — tool: `{req.tool}`",
    ]
    if req.explanation:
        parts.append(f"**Reason:** {req.explanation}")
    if req.risk_level:
        parts.append(f"**Risk level:** {req.risk_level}")
    parts += [
        f"**Arguments:**\n```json\n{args_text}\n```",
        "",
        "React ✅ or type `/allow` / `/yes` to allow. React ❌ or type `/deny` / `/no` to deny.",
    ]
    return "\n".join(parts)


class _PendingApproval:
    """Tracks a single pending approval message in a room."""

    def __init__(self, event_id: str, tool_call_id: str) -> None:
        self.event_id = event_id
        self.tool_call_id = tool_call_id
        self._future: asyncio.Future[bool] = asyncio.get_running_loop().create_future()

    def resolve(self, approved: bool) -> None:
        if not self._future.done():
            self._future.set_result(approved)

    async def wait(self) -> bool:
        return await self._future


class _PendingDomainApproval:
    """Tracks a pending proxy domain approval message in a room."""

    def __init__(self, event_id: str) -> None:
        self.event_id = event_id
        self._future: asyncio.Future[bool] = asyncio.get_running_loop().create_future()

    def resolve(self, approved: bool) -> None:
        if not self._future.done():
            self._future.set_result(approved)

    async def wait(self) -> bool:
        return await self._future


class MatrixChannel:
    """Matrix channel adapter.

    Lifecycle: call ``start()`` once at startup, ``stop()`` at shutdown.
    """

    def __init__(
        self,
        config: MatrixChannelConfig,
        full_config: Config,
        security_md: str,
        session_mgr: SessionManager,
        skill_catalog: list[SkillInfo],
        agent_model: Any,
        sandbox_mgr: SandboxManager,
    ) -> None:
        self._config = config
        self._full_config = full_config
        self._security_md = security_md
        self._session_mgr = session_mgr
        self._skill_catalog = skill_catalog
        self._agent_model = agent_model
        self._sandbox_mgr = sandbox_mgr

        self._client = nio.AsyncClient(config.homeserver, config.user_id)

        # room_id -> session_id
        self._room_sessions: dict[str, str] = {}
        # room_id -> asyncio.Lock (serialises one agent turn per room)
        self._room_locks: dict[str, asyncio.Lock] = {}
        # event_id of pending tool-approval message -> _PendingApproval
        self._pending_approvals: dict[str, _PendingApproval] = {}
        # event_id of pending domain-approval message -> _PendingDomainApproval
        self._pending_domain_approvals: dict[str, _PendingDomainApproval] = {}
        # room_id -> most recent pending approval of either kind (for command resolution)
        self._room_pending: dict[str, _PendingApproval | _PendingDomainApproval] = {}
        # verbose mode per room (room_id -> bool); controls tool call notifications
        self._verbose: dict[str, bool] = {}

        self._sync_task: asyncio.Task | None = None
        # Server timestamp (ms) at startup — used to ignore backlog messages
        self._started_at_ms: int = 0
        # Holds references to fire-and-forget background tasks to prevent GC
        self._background_tasks: set[asyncio.Task] = set()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Authenticate and start the sync loop."""
        data_dir = self._session_mgr.sessions_dir.parent
        token_file = data_dir / "matrix_token.json"

        await self._authenticate(token_file)
        logger.info(f"Matrix channel logged in as {self._config.user_id} on {self._config.homeserver}")

        # Initial sync: warm up room → session mapping.
        # Done BEFORE registering callbacks so backlog events are not dispatched.
        self._started_at_ms = int(time.time() * 1000)
        resp = await self._client.sync(timeout=5000, full_state=True)
        if isinstance(resp, nio.SyncError):
            if resp.status_code == "M_UNKNOWN_TOKEN":
                logger.warning("Matrix: stored token rejected (M_UNKNOWN_TOKEN), re-authenticating with password")
                token_file.unlink(missing_ok=True)
                await self._password_login(token_file)
                resp = await self._client.sync(timeout=5000, full_state=True)
            if isinstance(resp, nio.SyncError):
                raise RuntimeError(f"Matrix initial sync failed: {resp.status_code}: {resp.message}")

        assert isinstance(resp, nio.SyncResponse)
        for room_id in resp.rooms.join:
            self._get_or_create_session(room_id)
        logger.info(f"Matrix: tracking {len(self._room_sessions)} room(s)")

        # Register event callbacks AFTER the initial sync so backlog is not replayed.
        # type: ignore comments needed due to nio's non-generic callback type.
        self._client.add_event_callback(self._on_message, nio.RoomMessageText)  # type: ignore[arg-type]
        self._client.add_event_callback(self._on_reaction, nio.ReactionEvent)  # type: ignore[arg-type]
        self._client.add_event_callback(self._on_invite, nio.InviteMemberEvent)  # type: ignore[arg-type]

        self._sync_task = asyncio.create_task(self._sync_loop())
        logger.info("Matrix sync loop started")

    async def stop(self) -> None:
        """Stop the sync loop and close the connection."""
        if self._sync_task:
            self._sync_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, TimeoutError):
                await asyncio.wait_for(asyncio.shield(self._sync_task), timeout=5)
        await self._client.close()
        logger.info("Matrix channel stopped")

    # ------------------------------------------------------------------
    # Authentication helpers
    # ------------------------------------------------------------------

    def _load_token(self, token_file: Path) -> tuple[str, str | None]:
        """Return (access_token, device_id) from persisted file or env var, or ("", None)."""
        if token_file.exists():
            try:
                stored = json.loads(token_file.read_text())
                token = stored.get("access_token", "")
                device_id: str | None = stored.get("device_id")
                if token:
                    logger.debug("Matrix: using persisted access token")
                    return token, device_id
            except Exception as exc:
                logger.warning(f"Matrix: could not read persisted token file: {exc}")

        raw = os.environ.get("CARAPACE_MATRIX_TOKEN", "")
        if raw:
            device_id = None
            if ":" in raw:
                raw, dev = raw.split(":", 1)
                device_id = dev
            return raw, device_id

        return "", None

    async def _password_login(self, token_file: Path) -> None:
        """Log in with CARAPACE_MATRIX_PASSWORD and persist the new token. Raises on failure."""
        password = os.environ.get("CARAPACE_MATRIX_PASSWORD", "")
        if not password:
            raise RuntimeError("Matrix channel: no valid token available and CARAPACE_MATRIX_PASSWORD is not set")

        resp = await self._client.login(password, device_name=self._config.device_name)
        if isinstance(resp, nio.LoginError):
            raise RuntimeError(f"Matrix password login failed: {resp.message}")

        token_file.write_text(json.dumps({"access_token": resp.access_token, "device_id": resp.device_id}))
        logger.info(f"Matrix: password login successful, token persisted to {token_file}")

    async def _authenticate(self, token_file: Path) -> None:
        """Resolve credentials and configure the client. Raises on failure."""
        token, device_id = self._load_token(token_file)
        if token:
            self._client.restore_login(
                user_id=self._config.user_id,
                device_id=device_id or "",
                access_token=token,
            )
            return

        await self._password_login(token_file)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _sync_loop(self) -> None:
        """Run sync loop, inspecting each response and escalating errors appropriately."""
        while True:
            try:
                resp = await self._client.sync(timeout=30000)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning(f"Matrix: sync exception (retrying in 5s): {exc}")
                await asyncio.sleep(5)
                continue

            if isinstance(resp, nio.SyncError):
                if resp.status_code == "M_UNKNOWN_TOKEN":
                    logger.error(
                        "Matrix: session token invalidated (M_UNKNOWN_TOKEN) — "
                        "sync loop stopped; restart the service to re-authenticate"
                    )
                    break
                logger.error(f"Matrix: sync error {resp.status_code!r}: {resp.message!r} — retrying in 5s")
                await asyncio.sleep(5)
                continue

            await asyncio.sleep(0.5)

    def _get_or_create_session(self, room_id: str) -> str:
        """Return existing session_id for room, or create a new one."""
        if room_id in self._room_sessions:
            return self._room_sessions[room_id]
        existing = self._session_mgr.find_session("matrix", room_id)
        if existing:
            self._room_sessions[room_id] = existing
            logger.debug(f"Matrix: resuming session {existing} for room {room_id}")
        else:
            state = self._session_mgr.create_session("matrix", room_id)
            self._room_sessions[room_id] = state.session_id
            logger.info(f"Matrix: created session {state.session_id} for room {room_id}")
        return self._room_sessions[room_id]

    def _room_lock(self, room_id: str) -> asyncio.Lock:
        if room_id not in self._room_locks:
            self._room_locks[room_id] = asyncio.Lock()
        return self._room_locks[room_id]

    def _is_allowed(self, room: nio.MatrixRoom, sender: str) -> bool:
        """Return True if the message should be processed."""
        if sender == self._config.user_id:
            return False
        if self._config.allowed_users and sender not in self._config.allowed_users:
            logger.debug(f"Matrix: ignoring message from unlisted user {sender}")
            return False
        if self._config.allowed_rooms and room.room_id not in self._config.allowed_rooms:
            logger.debug(f"Matrix: ignoring message in unlisted room {room.room_id}")
            return False
        return True

    async def _send_text(self, room_id: str, text: str) -> str | None:
        """Send a markdown message; returns the sent event_id or None on error."""
        content = {
            "msgtype": "m.text",
            "body": text,
            "format": "org.matrix.custom.html",
            "formatted_body": _md_to_html(text),
        }
        resp = await self._client.room_send(room_id, "m.room.message", content)
        if isinstance(resp, nio.RoomSendResponse):
            return resp.event_id
        logger.warning(f"Matrix send error in {room_id}: {resp}")
        return None

    async def _send_notice(self, room_id: str, text: str) -> None:
        """Send an m.notice (visually subdued) message to the room."""
        content = {
            "msgtype": "m.notice",
            "body": text,
            "format": "org.matrix.custom.html",
            "formatted_body": _md_to_html(text),
        }
        resp = await self._client.room_send(room_id, "m.room.message", content)
        if not isinstance(resp, nio.RoomSendResponse):
            logger.warning(f"Matrix notice send error in {room_id}: {resp}")

    async def _send_typing(self, room_id: str, typing: bool = True) -> None:
        await self._client.room_typing(room_id, typing_state=typing, timeout=int(_TYPING_INTERVAL * 1000))

    def _build_deps(
        self,
        session_state: SessionState,
        tool_call_callback: Any = None,
        usage_tracker: UsageTracker | None = None,
        verbose: bool = False,
    ) -> Deps:
        return Deps(
            config=self._full_config,
            data_dir=self._session_mgr.sessions_dir.parent,
            session_state=session_state,
            skill_catalog=self._skill_catalog,
            agent_model=self._agent_model,
            verbose=verbose,
            tool_call_callback=tool_call_callback,
            usage_tracker=usage_tracker or self._session_mgr.load_usage(session_state.session_id),
            sandbox=self._sandbox_mgr,
            activated_skills=[],
        )

    # ------------------------------------------------------------------
    # Event callbacks (called by nio from the sync loop)
    # ------------------------------------------------------------------

    async def _on_invite(self, room: nio.MatrixRoom, event: nio.InviteMemberEvent) -> None:
        """Auto-join rooms we're invited to (if allowed by config)."""
        if event.membership != "invite" or event.state_key != self._config.user_id:
            return
        if self._config.allowed_rooms and room.room_id not in self._config.allowed_rooms:
            logger.info(f"Matrix: ignoring invite to unlisted room {room.room_id}")
            return
        logger.info(f"Matrix: joining invited room {room.room_id}")
        await self._client.join(room.room_id)

    async def _on_reaction(self, room: nio.MatrixRoom, event: nio.ReactionEvent) -> None:
        """Resolve pending approvals when the user reacts to an approval message."""
        if event.sender == self._config.user_id:
            return

        key = event.key.strip()
        approved = key in _APPROVE_REACTIONS
        denied = key in _DENY_REACTIONS

        if not (approved or denied):
            return

        # Tool approval
        if (pending := self._pending_approvals.get(event.reacts_to)) is not None:
            logger.info(f"Matrix: tool approval={approved} via reaction from {event.sender} in {room.room_id}")
            pending.resolve(approved)
            return

        # Domain approval
        if (domain_pending := self._pending_domain_approvals.get(event.reacts_to)) is not None:
            logger.info(
                f"Matrix: domain decision={'allow' if approved else 'deny'} "
                + f"via reaction from {event.sender} in {room.room_id}"
            )
            domain_pending.resolve(approved)

    async def _on_message(self, room: nio.MatrixRoom, event: nio.RoomMessageText) -> None:
        """Handle a text message from a room."""
        if not self._is_allowed(room, event.sender):
            return

        # Skip events that predate our startup (avoids replaying backlog if callbacks
        # fire for old events, e.g. during reconnect or after a gap in sync_forever).
        if event.server_timestamp < self._started_at_ms:
            return

        body = event.body.strip()
        if not body:
            return

        room_id = room.room_id
        session_id = self._get_or_create_session(room_id)

        logger.info(f"Matrix [{room_id}] <{event.sender}>: {body[:80]}")

        # Handle slash commands
        if body.startswith("/"):
            await self._handle_command(room_id, session_id, body, event.sender)
            return

        # Regular message — run agent turn as a background task so the sync
        # loop callback returns immediately and keeps receiving new events
        # (e.g. approval commands typed while the agent is waiting).
        task = asyncio.create_task(self._run_turn_locked(room_id, session_id, body))
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    # ------------------------------------------------------------------
    # Slash commands
    # ------------------------------------------------------------------

    async def _handle_command(self, room_id: str, session_id: str, text: str, sender: str) -> None:
        """Dispatch a slash command."""
        parts = text.strip().split(maxsplit=1)
        cmd = parts[0].lower()

        match cmd:
            case "/reset":
                await self._handle_reset(room_id, session_id)
                return
            case _ if cmd in _APPROVE_COMMANDS:
                pending = self._room_pending.get(room_id)
                if pending is None:
                    await self._send_text(room_id, "No pending approval request.")
                elif isinstance(pending, _PendingDomainApproval):
                    pending.resolve(True)
                    await self._send_text(room_id, "✅ Domain access allowed.")
                else:
                    pending.resolve(True)
                    await self._send_text(room_id, "✅ Operation approved.")
                return
            case _ if cmd in _DENY_COMMANDS:
                pending = self._room_pending.get(room_id)
                if pending is None:
                    await self._send_text(room_id, "No pending approval request.")
                elif isinstance(pending, _PendingDomainApproval):
                    pending.resolve(False)
                    await self._send_text(room_id, "❌ Domain access denied.")
                else:
                    pending.resolve(False)
                    await self._send_text(room_id, "❌ Operation denied.")
                return
            case "/verbose":
                verbose = not self._verbose.get(room_id, False)
                self._verbose[room_id] = verbose
                state = "on" if verbose else "off"
                await self._send_text(room_id, f"Tool call display {state}.")
                return
            case "/help":
                reply = (
                    "**Available commands:**\n\n"
                    "- `/reset` — Start a new session (clears history and credentials)\n"
                    "- `/security` — Show security policy summary\n"
                    "- `/approve-context` — Vouch for the current agent context as trustworthy\n"
                    "- `/session` — Show current session state\n"
                    "- `/skills` — List available skills\n"
                    "- `/memory` — List memory files\n"
                    "- `/usage` — Show token usage\n"
                    "- `/verbose` — Toggle tool call notifications\n"
                    "- `/allow` / `/yes` — Approve tool call or allow domain\n"
                    "- `/deny` / `/no` — Deny tool call or block domain\n"
                    "- `/help` — Show this help"
                )
                await self._send_text(room_id, reply)
                return

        # Delegate to the shared slash-command handler (needs a Deps object)
        session_state = self._session_mgr.resume_session(session_id)
        if session_state is None:
            await self._send_text(room_id, "Error: session not found.")
            return

        deps = self._build_deps(session_state, verbose=self._verbose.get(room_id, False))

        from carapace.server import _handle_slash_command  # avoid circular at module level

        result = _handle_slash_command(text, deps)
        if result:
            self._session_mgr.save_state(deps.session_state)
            self._session_mgr.append_events(
                session_id,
                [
                    {"role": "user", "content": text},
                    {"role": "command", "command": result.command, "data": result.data},
                ],
            )
            reply = _format_command_result_text(result)
            await self._send_text(room_id, reply)
        else:
            await self._send_text(room_id, f"Unknown command: `{cmd}`. Type `/help` for a list.")

    async def _handle_reset(self, room_id: str, old_session_id: str) -> None:
        """Create a new session for this room."""
        await self._sandbox_mgr.cleanup_session(old_session_id)
        new_state = self._session_mgr.create_session("matrix", room_id)
        self._room_sessions[room_id] = new_state.session_id
        # Clear any stale room-level pending approval
        self._room_pending.pop(room_id, None)
        logger.info(f"Matrix: reset session for {room_id} → {new_state.session_id}")
        security_mod.cleanup_session(old_session_id)
        await self._send_text(
            room_id,
            f"🔄 Session reset. New session: `{new_state.session_id}`\n"
            "History and approved credentials have been cleared.",
        )

    # ------------------------------------------------------------------
    # Agent turn
    # ------------------------------------------------------------------

    async def _run_turn_locked(self, room_id: str, session_id: str, body: str) -> None:
        """Acquire the per-room lock and run one agent turn."""
        async with self._room_lock(room_id):
            await self._run_turn(room_id, session_id, body)

    async def _run_turn(self, room_id: str, session_id: str, user_input: str) -> None:
        """Run one agent turn for the given room/session."""
        session_state = self._session_mgr.resume_session(session_id)
        if session_state is None:
            await self._send_text(room_id, "Error: session not found — try `/reset`.")
            return

        # Track pending approval futures indexed by tool_call_id → _PendingApproval
        # We also need to map event_id → _PendingApproval for reaction handling.
        approval_futures: dict[str, _PendingApproval] = {}

        async def _send_approval(req: ApprovalRequest) -> None:
            text = _format_approval_request(req)
            event_id = await self._send_text(room_id, text)
            pending = _PendingApproval(event_id or "", req.tool_call_id)
            approval_futures[req.tool_call_id] = pending
            if event_id:
                self._pending_approvals[event_id] = pending
            self._room_pending[room_id] = pending

        async def _collect_approvals(pending_ids: set[str]) -> dict[str, bool | ToolDenied]:
            results: dict[str, bool | ToolDenied] = {}
            for tool_call_id in pending_ids:
                pa = approval_futures.get(tool_call_id)
                if pa is None:
                    results[tool_call_id] = ToolDenied("Approval tracking error.")
                    continue
                approved = await pa.wait()
                results[tool_call_id] = True if approved else ToolDenied("User denied this operation.")
                # Clean up
                if pa.event_id:
                    self._pending_approvals.pop(pa.event_id, None)
            self._room_pending.pop(room_id, None)
            return results

        def _tool_call_info(tool: str, args: dict[str, Any], detail: str) -> None:
            logger.debug(f"Matrix [{room_id}] tool call: {tool}({args}) — {detail}")
            if self._verbose.get(room_id, False):
                args_brief = json.dumps(args, default=str)
                notice = f"🔧 `{tool}({args_brief})`" + (f" — {detail}" if detail else "")
                task = asyncio.create_task(self._send_notice(room_id, notice))
                self._background_tasks.add(task)
                task.add_done_callback(self._background_tasks.discard)

        async def _domain_escalation(
            _session_id: str,
            domain: str,
            context: dict[str, Any],
        ) -> bool:
            text = _format_domain_escalation(
                domain,
                context.get("command", ""),
                context.get("explanation", ""),
            )
            event_id = await self._send_text(room_id, text)
            domain_pending = _PendingDomainApproval(event_id or "")
            if event_id:
                self._pending_domain_approvals[event_id] = domain_pending
            self._room_pending[room_id] = domain_pending
            try:
                return await domain_pending.wait()
            finally:
                if event_id:
                    self._pending_domain_approvals.pop(event_id, None)
                self._room_pending.pop(room_id, None)

        data_dir = self._session_mgr.sessions_dir.parent
        skills_dir = data_dir / "skills"
        audit_dir = data_dir / "sessions" / session_id
        try:
            sec_session = security_mod.get_session(session_id)
        except KeyError:
            sec_session = security_mod.init_session(
                session_id,
                bouncer_model=self._full_config.agent.bouncer_model,
                security_md=self._security_md,
                skills_dir=skills_dir,
                audit_dir=audit_dir,
            )
        sec_session.set_user_escalation_callback(_domain_escalation)

        def _domain_info(domain: str, detail: str) -> None:
            logger.debug(f"Matrix [{room_id}] domain: {domain} {detail}")
            if self._verbose.get(room_id, False):
                notice = f"🌐 `{domain}` — {detail}"
                task = asyncio.create_task(self._send_notice(room_id, notice))
                self._background_tasks.add(task)
                task.add_done_callback(self._background_tasks.discard)

        sec_session.set_domain_info_callback(_domain_info)

        deps = self._build_deps(
            session_state,
            tool_call_callback=_tool_call_info,
            verbose=self._verbose.get(room_id, False),
        )

        await self._send_typing(room_id, True)
        typing_task = asyncio.create_task(self._keep_typing(room_id))

        try:
            message_history = self._session_mgr.load_history(session_id)
            message_history, output = await run_agent_turn(
                user_input,
                deps,
                message_history,
                send_approval_request=_send_approval,
                collect_approvals=_collect_approvals,
            )
            self._session_mgr.save_history(session_id, message_history)
            self._session_mgr.save_state(deps.session_state)
            self._session_mgr.save_usage(session_id, deps.usage_tracker)
            self._session_mgr.append_events(
                session_id,
                [
                    {"role": "user", "content": user_input},
                    {"role": "assistant", "content": output},
                ],
            )
        except Exception as exc:
            logger.exception(f"Matrix agent error in {room_id}: {exc}")
            output = f"Error: {exc}"
        finally:
            typing_task.cancel()
            await self._send_typing(room_id, False)

        await self._send_text(room_id, output)

    async def _keep_typing(self, room_id: str) -> None:
        """Repeatedly renew the typing indicator while the agent is thinking."""
        try:
            while True:
                await asyncio.sleep(_TYPING_INTERVAL - 1)
                await self._send_typing(room_id, True)
        except asyncio.CancelledError:
            pass
