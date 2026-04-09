"""MatrixChannel — main channel adapter class."""

from __future__ import annotations

import asyncio
import contextlib
import time
from pathlib import Path
from typing import Any

import nio
from loguru import logger

from carapace.channels.matrix.approval import (
    APPROVE_COMMANDS,
    APPROVE_REACTIONS,
    DENY_COMMANDS,
    DENY_REACTIONS,
    TYPING_INTERVAL,
    PendingApproval,
    PendingCredentialApproval,
    PendingDomainApproval,
)
from carapace.channels.matrix.formatting import (
    format_command_result_text,
    md_to_html,
)
from carapace.channels.matrix.subscriber import MatrixSubscriber
from carapace.models import Config, MatrixChannelConfig, MatrixTokenFile, SkillInfo
from carapace.sandbox.manager import SandboxManager
from carapace.session import SessionEngine, SessionManager
from carapace.ws_models import ApprovalResponse, CommandResult, EscalationResponse


class MatrixChannel:
    """Matrix channel adapter.

    Lifecycle: call ``start()`` once at startup, ``stop()`` at shutdown.
    """

    def __init__(
        self,
        config: MatrixChannelConfig,
        full_config: Config,
        session_mgr: SessionManager,
        skill_catalog: list[SkillInfo],
        agent_model: Any,
        sandbox_mgr: SandboxManager,
        engine: SessionEngine,
    ) -> None:
        self._config = config
        self._full_config = full_config
        self._session_mgr = session_mgr
        self._skill_catalog = skill_catalog
        self._agent_model = agent_model
        self._sandbox_mgr = sandbox_mgr
        self._engine = engine

        self._client = nio.AsyncClient(config.homeserver, config.user_id)

        # room_id -> session_id
        self._room_sessions: dict[str, str] = {}
        # event_id of pending tool-approval message -> PendingApproval
        self._pending_approvals: dict[str, PendingApproval] = {}
        # event_id of pending domain-approval message -> PendingDomainApproval
        self._pending_domain_approvals: dict[str, PendingDomainApproval] = {}
        # event_id of pending credential-approval message -> PendingCredentialApproval
        self._pending_credential_approvals: dict[str, PendingCredentialApproval] = {}
        # room_id -> most recent pending approval of any kind (for command resolution)
        self._room_pending: dict[str, PendingApproval | PendingDomainApproval | PendingCredentialApproval] = {}
        # verbose mode per room (room_id -> bool); defaults to True (show tool calls)
        self._verbose: dict[str, bool] = {}
        # room_id -> MatrixSubscriber (persistent per room)
        self._room_subscribers: dict[str, MatrixSubscriber] = {}

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

        # Accept any invites that arrived while we were offline.
        for room_id in resp.rooms.invite:
            if self._config.allowed_rooms and room_id not in self._config.allowed_rooms:
                logger.info(f"Matrix: ignoring offline invite to unlisted room {room_id}")
                continue
            logger.info(f"Matrix: accepting offline invite to room {room_id}")
            await self._client.join(room_id)

        # Re-sync after joining so newly joined rooms appear in rooms.join.
        if resp.rooms.invite:
            resp2 = await self._client.sync(timeout=5000, full_state=True)
            if isinstance(resp2, nio.SyncResponse):
                resp = resp2

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
                stored = MatrixTokenFile.model_validate_json(token_file.read_text())
                if stored.user_id != self._config.user_id:
                    logger.warning(
                        f"Matrix: persisted token belongs to {stored.user_id!r}, "
                        f"but config has {self._config.user_id!r} — discarding stale token"
                    )
                    token_file.unlink(missing_ok=True)
                else:
                    logger.debug("Matrix: using persisted access token")
                    return stored.access_token, stored.device_id
            except Exception as exc:
                logger.warning(f"Matrix: could not read persisted token file: {exc}")

        raw = self._config.token.resolve().get_secret_value() if self._config.token else ""
        if raw:
            device_id = None
            if ":" in raw:
                raw, dev = raw.split(":", 1)
                device_id = dev
            return raw, device_id

        return "", None

    async def _password_login(self, token_file: Path) -> None:
        """Log in with the configured password secret and persist the new token. Raises on failure."""
        password = self._config.password.resolve().get_secret_value() if self._config.password else ""
        if not password:
            raise RuntimeError("Matrix channel: no valid token available and no password secret configured")

        resp = await self._client.login(password, device_name=self._config.device_name)
        if isinstance(resp, nio.LoginError):
            raise RuntimeError(f"Matrix password login failed: {resp.message}")

        persisted = MatrixTokenFile(
            access_token=resp.access_token, device_id=resp.device_id, user_id=self._config.user_id
        )
        token_file.write_text(persisted.model_dump_json())
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
            "formatted_body": md_to_html(text),
        }
        resp = await self._client.room_send(room_id, "m.room.message", content)
        if isinstance(resp, nio.RoomSendResponse):
            return resp.event_id
        logger.warning(f"Matrix send error in {room_id}: {resp}")
        return None

    async def _send_notice(self, room_id: str, text: str) -> str | None:
        """Send an m.notice (visually subdued) message; returns event_id or None."""
        content = {
            "msgtype": "m.notice",
            "body": text,
            "format": "org.matrix.custom.html",
            "formatted_body": md_to_html(text),
        }
        resp = await self._client.room_send(room_id, "m.room.message", content)
        if isinstance(resp, nio.RoomSendResponse):
            return resp.event_id
        logger.warning(f"Matrix notice send error in {room_id}: {resp}")
        return None

    async def _edit_message(self, room_id: str, event_id: str, text: str, *, msgtype: str = "m.notice") -> None:
        """Edit a previously sent message using m.replace."""
        content = {
            "msgtype": msgtype,
            "body": f"* {text}",
            "format": "org.matrix.custom.html",
            "formatted_body": md_to_html(text),
            "m.new_content": {
                "msgtype": msgtype,
                "body": text,
                "format": "org.matrix.custom.html",
                "formatted_body": md_to_html(text),
            },
            "m.relates_to": {
                "rel_type": "m.replace",
                "event_id": event_id,
            },
        }
        resp = await self._client.room_send(room_id, "m.room.message", content)
        if not isinstance(resp, nio.RoomSendResponse):
            logger.warning(f"Matrix edit error in {room_id}: {resp}")

    async def _redact(self, room_id: str, event_id: str) -> None:
        """Redact (delete) a previously sent message."""
        resp = await self._client.room_redact(room_id, event_id)
        if not isinstance(resp, nio.RoomRedactResponse):
            logger.warning(f"Matrix redact error in {room_id}: {resp}")

    async def _send_typing(self, room_id: str, typing: bool = True) -> None:
        await self._client.room_typing(room_id, typing_state=typing, timeout=int(TYPING_INTERVAL * 1000))

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
        approved = key in APPROVE_REACTIONS
        denied = key in DENY_REACTIONS

        if not (approved or denied):
            return

        room_id = room.room_id
        session_id = self._room_sessions.get(room_id)

        # Tool approval
        if event.reacts_to in self._pending_approvals:
            logger.info(f"Matrix: tool approval={approved} via reaction from {event.sender} in {room_id}")
            if session_id:
                sub = self._room_subscribers.get(room_id)
                tool_call_id = sub._approval_events.get(event.reacts_to) if sub else None
                if sub and tool_call_id:
                    await self._engine.submit_approval(
                        session_id,
                        ApprovalResponse(tool_call_id=tool_call_id, approved=approved),
                    )
                    sub._approval_events.pop(event.reacts_to, None)
                    self._pending_approvals.pop(event.reacts_to, None)
                    self._room_pending.pop(room_id, None)
            return

        # Domain approval
        if event.reacts_to in self._pending_domain_approvals:
            logger.info(
                f"Matrix: domain decision={'allow' if approved else 'deny'} "
                + f"via reaction from {event.sender} in {room_id}"
            )
            if session_id:
                sub = self._room_subscribers.get(room_id)
                request_id = sub._domain_events.get(event.reacts_to) if sub else None
                if sub and request_id:
                    decision = "allow" if approved else "deny"
                    await self._engine.submit_approval(
                        session_id,
                        EscalationResponse(request_id=request_id, decision=decision),
                    )
                    sub._domain_events.pop(event.reacts_to, None)
                    self._pending_domain_approvals.pop(event.reacts_to, None)
                    self._room_pending.pop(room_id, None)
            return

        # Credential approval
        if event.reacts_to in self._pending_credential_approvals:
            logger.info(
                f"Matrix: credential decision={'allowed' if approved else 'denied'} "
                + f"via reaction from {event.sender} in {room_id}"
            )
            if session_id:
                sub = self._room_subscribers.get(room_id)
                request_id = sub._credential_events.get(event.reacts_to) if sub else None
                if sub and request_id:
                    decision = "allow" if approved else "deny"
                    await self._engine.submit_approval(
                        session_id,
                        EscalationResponse(request_id=request_id, decision=decision),
                    )
                    sub._credential_events.pop(event.reacts_to, None)
                    self._pending_credential_approvals.pop(event.reacts_to, None)
                    self._room_pending.pop(room_id, None)

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

        # Delegate to SessionEngine
        sub = self._room_subscribers.get(room_id)
        if sub is None:
            sub = MatrixSubscriber(self, room_id)
            self._room_subscribers[room_id] = sub
        self._engine.subscribe(session_id, sub)
        sub._start_typing()
        await self._engine.submit_message(session_id, body, origin=sub)

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
            case _ if cmd in APPROVE_COMMANDS:
                await self._resolve_pending(room_id, session_id, approve=True)
                return
            case _ if cmd in DENY_COMMANDS:
                await self._resolve_pending(room_id, session_id, approve=False)
                return
            case "/verbose":
                verbose = not self._verbose.get(room_id, False)
                self._verbose[room_id] = verbose
                state = "on" if verbose else "off"
                await self._send_text(room_id, f"Tool call display {state}.")
                return
            case "/stop" | "/cancel":
                await self._engine.submit_cancel(session_id)
                sub = self._room_subscribers.get(room_id)
                if sub:
                    sub._approval_events.clear()
                    sub._domain_events.clear()
                self._room_pending.pop(room_id, None)
                await self._send_text(room_id, "⛔ Agent cancelled.")
                return
            case "/help":
                reply = (
                    "**Available commands:**\n\n"
                    "- `/reset` — Start a new session (clears history and credentials)\n"
                    "- `/stop` — Cancel the running agent turn\n"
                    "- `/security` — Show security policy summary\n"
                    "- `/approve-context` — Vouch for the current agent context as trustworthy\n"
                    "- `/session` — Show current session state\n"
                    "- `/skills` — List available skills\n"
                    "- `/memory` — List memory files\n"
                    "- `/retitle` — Regenerate title, or `/retitle My title` to set it\n"
                    "- `/usage` — Show token usage\n"
                    "- `/model` — View or switch agent, sentinel, and title models together\n"
                    "- `/model-agent` — View or switch the agent model only\n"
                    "- `/model-sentinel` — View or switch the sentinel model\n"
                    "- `/model-title` — View or switch the title model\n"
                    "- `/verbose` — Toggle tool call notifications\n"
                    "- `/allow` / `/yes` — Approve tool call or allow domain\n"
                    "- `/deny` / `/no` — Deny tool call or block domain\n"
                    "- `/help` — Show this help"
                )
                await self._send_text(room_id, reply)
                return

        # Delegate to engine slash-command handler
        result_data = await self._engine.handle_slash_command(session_id, text)
        if result_data:
            result = CommandResult(command=result_data["command"], data=result_data["data"])
            reply = format_command_result_text(result)
            await self._send_text(room_id, reply)
        else:
            await self._send_text(room_id, f"Unknown command: `{cmd}`. Type `/help` for a list.")

    async def _handle_reset(self, room_id: str, old_session_id: str) -> None:
        """Create a new session for this room."""
        self._engine.deactivate(old_session_id)
        sub = self._room_subscribers.pop(room_id, None)
        if sub:
            self._engine.unsubscribe(old_session_id, sub)
        await self._sandbox_mgr.cleanup_session(old_session_id)
        new_state = self._session_mgr.create_session("matrix", room_id)
        self._room_sessions[room_id] = new_state.session_id
        # Clear any stale room-level pending approval
        self._room_pending.pop(room_id, None)
        logger.info(f"Matrix: reset session for {room_id} → {new_state.session_id}")
        await self._send_text(
            room_id,
            f"🔄 Session reset. New session: `{new_state.session_id}`\n"
            "History and approved credentials have been cleared.",
        )

    async def _resolve_pending(self, room_id: str, session_id: str, *, approve: bool) -> None:
        """Resolve the oldest pending approval (tool or domain) for a room."""
        sub = self._room_subscribers.get(room_id)
        if sub is None:
            await self._send_text(room_id, "No pending approval request.")
            return

        if sub._approval_events:
            event_id, tool_call_id = next(iter(sub._approval_events.items()))
            await self._engine.submit_approval(
                session_id,
                ApprovalResponse(tool_call_id=tool_call_id, approved=approve),
            )
            sub._approval_events.pop(event_id, None)
            self._pending_approvals.pop(event_id, None)
            self._room_pending.pop(room_id, None)
            msg = "✅ Operation approved." if approve else "❌ Operation denied."
            await self._send_text(room_id, msg)
        elif sub._domain_events:
            event_id, request_id = next(iter(sub._domain_events.items()))
            decision = "allow" if approve else "deny"
            await self._engine.submit_approval(
                session_id,
                EscalationResponse(request_id=request_id, decision=decision),
            )
            sub._domain_events.pop(event_id, None)
            self._pending_domain_approvals.pop(event_id, None)
            self._room_pending.pop(room_id, None)
            msg = "✅ Domain access allowed." if approve else "❌ Domain access denied."
            await self._send_text(room_id, msg)
        elif sub._credential_events:
            event_id, request_id = next(iter(sub._credential_events.items()))
            decision = "allow" if approve else "deny"
            await self._engine.submit_approval(
                session_id,
                EscalationResponse(request_id=request_id, decision=decision),
            )
            sub._credential_events.pop(event_id, None)
            self._pending_credential_approvals.pop(event_id, None)
            self._room_pending.pop(room_id, None)
            msg = "✅ Credential access allowed." if approve else "❌ Credential access denied."
            await self._send_text(room_id, msg)
        else:
            await self._send_text(room_id, "No pending approval request.")
