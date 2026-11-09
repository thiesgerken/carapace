"""MatrixChannel — main channel adapter class."""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Protocol, cast

import nio
import yaml
from loguru import logger

from ...auth import normalize_username
from ...models.config import Config
from ...models.matrix import MatrixChannelConfig, MatrixTokenFile, MatrixTokensFile
from ...models.user import UserConfig
from ...notifications.presence import NotificationPresenceRegistry
from ...sandbox.manager import SandboxManager
from ...session import SessionEngine, SessionManager
from ...user_defaults import apply_user_model_defaults, effective_user_budget
from ...ws_models import ApprovalResponse, CommandResult, EscalationResponse
from .approval import (
    APPROVE_COMMANDS,
    APPROVE_REACTIONS,
    DENY_COMMANDS,
    DENY_REACTIONS,
    TYPING_INTERVAL,
    PendingApproval,
    PendingCredentialApproval,
    PendingDomainApproval,
)
from .formatting import (
    format_command_result_text,
    md_to_html,
)
from .subscriber import MatrixSubscriber


class MatrixPasswordMissingError(RuntimeError):
    """Re-authentication needs a password, and none is configured."""


# Pyrefly widens matrix-nio's decorated async methods to
# `AsyncGenerator | Coroutine`, so we pin the subset we use here.
class MatrixClientProtocol(Protocol):
    async def close(self) -> None: ...

    async def join(self, room_id: str) -> nio.JoinResponse | nio.JoinError: ...

    async def login(
        self, password: str | None = None, device_name: str | None = "", token: str | None = None
    ) -> nio.LoginResponse | nio.LoginError: ...

    async def room_redact(
        self, room_id: str, event_id: str, reason: str | None = None, tx_id: str | None = None
    ) -> nio.RoomRedactResponse | nio.RoomRedactError: ...

    async def room_send(
        self,
        room_id: str,
        message_type: str,
        content: dict[Any, Any],
        tx_id: str | None = None,
        ignore_unverified_devices: bool = False,
    ) -> nio.RoomSendResponse | nio.RoomSendError: ...

    async def room_typing(
        self, room_id: str, typing_state: bool = True, timeout: int = 30000
    ) -> nio.RoomTypingResponse | nio.RoomTypingError: ...

    async def sync(
        self,
        timeout: int | None = 0,
        sync_filter: str | dict[Any, Any] | None = None,
        since: str | None = None,
        full_state: bool | None = None,
        set_presence: str | None = None,
    ) -> nio.SyncResponse | nio.SyncError: ...

    def add_event_callback(
        self,
        callback: Callable[..., Awaitable[None]],
        filter: type[Any] | tuple[type[Any], ...] | None = None,
    ) -> None: ...

    def restore_login(self, user_id: str, device_id: str, access_token: str) -> None: ...


class MatrixChannel:
    """Matrix channel adapter.

    Lifecycle: call ``start()`` once at startup, ``stop()`` at shutdown.
    """

    def __init__(
        self,
        config: MatrixChannelConfig,
        full_config: Config,
        session_mgr: SessionManager,
        sandbox_mgr: SandboxManager,
        engine: SessionEngine,
        owner_user: str,
        owner_config: UserConfig | None = None,
        presence_registry: NotificationPresenceRegistry | None = None,
    ) -> None:
        self._config = config
        self._full_config = full_config
        self._session_mgr = session_mgr
        self._sandbox_mgr = sandbox_mgr
        self._engine = engine
        self._presence_registry = presence_registry
        self._owner_user = normalize_username(owner_user)
        self._owner_config = owner_config.model_copy(deep=True) if owner_config is not None else UserConfig()
        self._token_file = session_mgr.sessions_dir.parent / "matrix_token.yaml"
        if not self._owner_user:
            raise ValueError("Matrix channel owner user must not be empty")

        self._client = cast(MatrixClientProtocol, nio.AsyncClient(config.homeserver, config.user_id))

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
        await self._authenticate(self._token_file)
        logger.info(f"Matrix channel logged in as {self._config.user_id} on {self._config.homeserver}")

        # Initial sync: warm up room → session mapping.
        # Done BEFORE registering callbacks so backlog events are not dispatched.
        self._started_at_ms = int(time.time() * 1000)
        resp = await self._client.sync(timeout=5000, full_state=True)
        if isinstance(resp, nio.SyncError):
            if resp.status_code == "M_UNKNOWN_TOKEN":
                await self._reauthenticate()
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
        if self._presence_registry is not None:
            for room_id, session_id in self._room_sessions.items():
                self._presence_registry.remove_presence(
                    session_id=session_id,
                    source_id=f"matrix:{room_id}",
                )
        await self._client.close()
        logger.info("Matrix channel stopped")

    # ------------------------------------------------------------------
    # Authentication helpers
    # ------------------------------------------------------------------

    def _load_token(self, token_file: Path) -> tuple[str, str | None]:
        """Return (access_token, device_id) from persisted file or env var, or ("", None)."""
        if token_file.exists():
            try:
                stored = self._load_persisted_token(token_file)
                if stored is not None:
                    logger.debug("Matrix: using persisted access token")
                    return stored.access_token, stored.device_id
            except Exception as exc:
                logger.warning(f"Matrix: could not read persisted token file: {exc}")

        raw = self._config.token or ""
        if raw:
            device_id = None
            if ":" in raw:
                raw, dev = raw.split(":", 1)
                device_id = dev
            return raw, device_id

        return "", None

    @staticmethod
    def _read_tokens_file(token_file: Path) -> MatrixTokensFile:
        return MatrixTokensFile.model_validate(yaml.safe_load(token_file.read_text(encoding="utf-8")) or {})

    def _load_persisted_token(self, token_file: Path) -> MatrixTokenFile | None:
        tokens_file = self._read_tokens_file(token_file)
        for stored in tokens_file.tokens:
            if stored.user_id != self._config.user_id:
                continue
            if normalize_username(stored.user) != self._owner_user:
                logger.warning(
                    f"Matrix: persisted token for {self._config.user_id!r} is owned by {stored.user!r}, "
                    f"but channel owner is {self._owner_user!r} — ignoring token"
                )
                continue
            return stored
        logger.warning(f"Matrix: no persisted token for {self._config.user_id!r} in {token_file} — ignoring token file")
        return None

    def _require_owner_user(self) -> str:
        return self._owner_user

    async def _password_login(self, token_file: Path) -> None:
        """Log in with the configured password secret and persist the new token. Raises on failure."""
        password = self._config.password or ""
        if not password:
            raise MatrixPasswordMissingError(
                "Matrix channel: no valid token available and no password secret configured"
            )

        resp = await self._client.login(password, device_name=self._config.device_name)
        if isinstance(resp, nio.LoginError):
            raise RuntimeError(f"Matrix password login failed: {resp.message}")

        persisted = MatrixTokenFile(
            access_token=resp.access_token,
            device_id=resp.device_id,
            user_id=self._config.user_id,
            user=self._require_owner_user(),
        )
        # The file holds every user's channel token, so only this channel's entry is replaced.
        tokens_file = self._read_tokens_file(token_file) if token_file.exists() else MatrixTokensFile()
        token_file.write_text(
            yaml.safe_dump(tokens_file.with_token(persisted).model_dump(mode="json", exclude_none=True)),
            encoding="utf-8",
        )
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

    async def _reauthenticate(self) -> None:
        """Replace a token the homeserver rejected (M_UNKNOWN_TOKEN) via password login. Raises on failure.

        The stale entry stays in the token file until the login replaces it. If the login fails,
        the next start just hits M_UNKNOWN_TOKEN again and lands here.
        """
        logger.warning("Matrix: token rejected (M_UNKNOWN_TOKEN), re-authenticating with password")
        await self._password_login(self._token_file)

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
                    try:
                        await self._reauthenticate()
                    except MatrixPasswordMissingError:
                        # Unrecoverable without a config change, and saving the Matrix
                        # settings reloads the channel anyway.
                        logger.error(
                            "Matrix: session token invalidated (M_UNKNOWN_TOKEN) and no password configured — "
                            "sync loop stopped; set a password in the Matrix settings to re-authenticate"
                        )
                        break
                    except Exception as exc:
                        logger.warning(f"Matrix: re-authentication failed (retrying in 5s): {exc}")
                        await asyncio.sleep(5)
                    continue
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
            self._ensure_session_owner(existing)
            self._room_sessions[room_id] = existing
            logger.debug(f"Matrix: resuming session {existing} for room {room_id}")
        else:
            state = self._session_mgr.create_session(
                "matrix",
                room_id,
                budget=effective_user_budget(self._engine.config, self._owner_config),
                user=self._require_owner_user(),
                private=False,
            )
            apply_user_model_defaults(state, self._owner_config)
            self._session_mgr.save_state(state)
            self._room_sessions[room_id] = state.session_id
            logger.info(f"Matrix: created session {state.session_id} for room {room_id}")
        return self._room_sessions[room_id]

    def _ensure_session_owner(self, session_id: str) -> None:
        meta = self._session_mgr.load_meta(session_id)
        if meta.user != self._require_owner_user():
            raise RuntimeError(f"Matrix session {session_id} is not owned by configured Matrix owner")

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

    async def _note_presence(self, room_id: str, session_id: str) -> None:
        if self._presence_registry is None:
            return
        self._presence_registry.update_presence(
            session_id=session_id,
            source_id=f"matrix:{room_id}",
            client_type="matrix",
            focus_state="visible",
        )
        await self._engine.clear_pending_notifications(session_id)

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
        if not self._is_allowed(room, event.sender):
            return

        key = event.key.strip()
        approved = key in APPROVE_REACTIONS
        denied = key in DENY_REACTIONS

        if not (approved or denied):
            return

        room_id = room.room_id
        session_id = self._room_sessions.get(room_id)
        if session_id:
            await self._note_presence(room_id, session_id)

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
        await self._note_presence(room_id, session_id)

        logger.info(f"Matrix [{room_id}] <{event.sender}>: {body[:80]}")

        # Handle slash commands
        if body.startswith("/"):
            await self._handle_command(room_id, session_id, body, event.sender)
            return

        await self._submit_user_message(room_id, session_id, body)

    async def _submit_user_message(self, room_id: str, session_id: str, body: str) -> None:
        """Delegate a Matrix user message to SessionEngine."""
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
        arg = parts[1].strip() if len(parts) > 1 else ""

        match cmd:
            case "/reset":
                await self._handle_reset(room_id, session_id)
                return
            case _ if cmd in APPROVE_COMMANDS:
                await self._resolve_pending(room_id, session_id, approve=True)
                return
            case _ if cmd in DENY_COMMANDS:
                await self._resolve_pending(room_id, session_id, approve=False, message=arg or None)
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
                    "- `/session` — Show current session state\n"
                    "- `/skills` — List available skills\n"
                    "- `/retitle` — Regenerate title, or `/retitle My title` to set it\n"
                    "- `/budget` — Show current budgets; set with `/budget input N`, "
                    "`/budget output N`, `/budget cost N`, or `/budget tools N`\n"
                    "- `/usage` — Show token usage\n"
                    "- `/model` — View models, set all with `/model all NAME`, "
                    + "or target one with `/model sentinel NAME`\n"
                    "- `/verbose` — Toggle tool call notifications\n"
                    "- `/allow` / `/yes` — Approve tool call or allow domain\n"
                    "- `/deny [reason]` / `/no [reason]` — Deny tool call or block domain\n"
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
            await self._submit_user_message(room_id, session_id, text)

    async def _handle_reset(self, room_id: str, old_session_id: str) -> None:
        """Create a new session for this room."""
        self._engine.deactivate(old_session_id)
        sub = self._room_subscribers.pop(room_id, None)
        if sub:
            self._engine.unsubscribe(old_session_id, sub)
        if self._presence_registry is not None:
            self._presence_registry.remove_presence(session_id=old_session_id, source_id=f"matrix:{room_id}")
        await self._sandbox_mgr.cleanup_session(old_session_id)
        new_state = self._session_mgr.create_session(
            "matrix",
            room_id,
            budget=effective_user_budget(self._engine.config, self._owner_config),
            user=self._require_owner_user(),
            private=False,
        )
        apply_user_model_defaults(new_state, self._owner_config)
        self._session_mgr.save_state(new_state)
        self._room_sessions[room_id] = new_state.session_id
        await self._note_presence(room_id, new_state.session_id)
        # Clear any stale room-level pending approval
        self._room_pending.pop(room_id, None)
        logger.info(f"Matrix: reset session for {room_id} → {new_state.session_id}")
        await self._send_text(
            room_id,
            f"🔄 Session reset. New session: `{new_state.session_id}`\n"
            "History and approved credentials have been cleared.",
        )

    async def _resolve_pending(
        self,
        room_id: str,
        session_id: str,
        *,
        approve: bool,
        message: str | None = None,
    ) -> None:
        """Resolve the oldest pending approval (tool or domain) for a room."""
        sub = self._room_subscribers.get(room_id)
        if sub is None:
            await self._send_text(room_id, "No pending approval request.")
            return

        normalized_message = message.strip() if message else None

        if sub._approval_events:
            event_id, tool_call_id = next(iter(sub._approval_events.items()))
            await self._engine.submit_approval(
                session_id,
                ApprovalResponse(
                    tool_call_id=tool_call_id,
                    approved=approve,
                    message=normalized_message,
                ),
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
                EscalationResponse(
                    request_id=request_id,
                    decision=decision,
                    message=normalized_message,
                ),
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
                EscalationResponse(
                    request_id=request_id,
                    decision=decision,
                    message=normalized_message,
                ),
            )
            sub._credential_events.pop(event_id, None)
            self._pending_credential_approvals.pop(event_id, None)
            self._room_pending.pop(room_id, None)
            msg = "✅ Credential access allowed." if approve else "❌ Credential access denied."
            await self._send_text(room_id, msg)
        else:
            await self._send_text(room_id, "No pending approval request.")
