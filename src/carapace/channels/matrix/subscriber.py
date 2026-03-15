"""Engine-mode event subscriber that bridges SessionEngine events to Matrix messages."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

from loguru import logger

from carapace.channels.matrix.approval import TYPING_INTERVAL, PendingApproval, PendingDomainApproval
from carapace.channels.matrix.formatting import format_approval_request, format_domain_escalation
from carapace.ws_models import ApprovalRequest, TurnUsage

if TYPE_CHECKING:
    from carapace.channels.matrix.channel import MatrixChannel


class MatrixSubscriber:
    """Bridges ``SessionEngine`` events to Matrix messages for a room."""

    def __init__(self, channel: MatrixChannel, room_id: str) -> None:
        self._channel = channel
        self._room_id = room_id
        self._typing_task: asyncio.Task[None] | None = None
        self._stream_buffer = ""
        self._stream_event_id: str | None = None
        self._stream_last_len = 0
        # event_id → tool_call_id (for reaction-based approval)
        self._approval_events: dict[str, str] = {}
        # event_id → request_id (for reaction-based domain approval)
        self._domain_events: dict[str, str] = {}

    def _start_typing(self) -> None:
        if self._typing_task is None or self._typing_task.done():
            self._typing_task = asyncio.create_task(self._typing_loop())
            self._channel._background_tasks.add(self._typing_task)
            self._typing_task.add_done_callback(self._channel._background_tasks.discard)

    def _stop_typing(self) -> None:
        if self._typing_task and not self._typing_task.done():
            self._typing_task.cancel()
            self._typing_task = None
        t = asyncio.ensure_future(self._channel._send_typing(self._room_id, False))
        self._channel._background_tasks.add(t)
        t.add_done_callback(self._channel._background_tasks.discard)

    async def _typing_loop(self) -> None:
        try:
            await self._channel._send_typing(self._room_id, True)
            while True:
                await asyncio.sleep(TYPING_INTERVAL - 1)
                await self._channel._send_typing(self._room_id, True)
        except asyncio.CancelledError:
            pass

    async def on_user_message(self, content: str, *, from_self: bool) -> None:
        if from_self:
            return  # Matrix client already shows the sender's own message
        # Cross-channel message (e.g. from web UI) — forward to the room
        await self._channel._send_text(self._room_id, f"💬 {content}")

    async def on_tool_call(self, tool: str, args: dict[str, Any], detail: str) -> None:
        logger.debug(f"Matrix [{self._room_id}] tool call: {tool}({args}) — {detail}")
        if self._channel._verbose.get(self._room_id, True):
            args_brief = json.dumps(args, default=str)
            notice = f"🔧 `{tool}({args_brief})`" + (f" {detail}" if detail else "")
            await self._channel._send_notice(self._room_id, notice)

    async def on_tool_result(self, tool: str, result: str) -> None:
        if self._channel._verbose.get(self._room_id, True):
            # Truncate long results to keep Matrix messages manageable
            preview = result[:500] + ("…" if len(result) > 500 else "")
            notice = f"📎 `{tool}` result:\n```\n{preview}\n```"
            await self._channel._send_notice(self._room_id, notice)

    _STREAM_EDIT_THRESHOLD = 200  # min chars between edits

    async def on_token(self, content: str) -> None:
        self._stream_buffer += content
        if len(self._stream_buffer) - self._stream_last_len < self._STREAM_EDIT_THRESHOLD:
            return
        text = self._stream_buffer.rstrip()
        if not text:
            return
        self._stream_last_len = len(self._stream_buffer)
        if self._stream_event_id is None:
            self._stream_event_id = await self._channel._send_notice(self._room_id, text)
        else:
            await self._channel._edit_message(self._room_id, self._stream_event_id, text)

    async def on_done(self, content: str, usage: TurnUsage) -> None:
        if self._stream_event_id is not None:
            await self._channel._edit_message(
                self._room_id,
                self._stream_event_id,
                content,
                msgtype="m.text",
            )
            self._stream_event_id = None
        else:
            await self._channel._send_text(self._room_id, content)
        self._stream_buffer = ""
        self._stream_last_len = 0
        self._stop_typing()

    async def on_error(self, detail: str) -> None:
        self._stream_buffer = ""
        self._stream_last_len = 0
        self._stream_event_id = None
        self._stop_typing()
        await self._channel._send_text(self._room_id, f"Error: {detail}")

    async def on_cancelled(self) -> None:
        self._stream_buffer = ""
        self._stream_last_len = 0
        self._stream_event_id = None
        self._stop_typing()
        # no message needed — handled by the /stop command

    async def on_approval_request(self, req: ApprovalRequest) -> None:
        text = format_approval_request(req)
        event_id = await self._channel._send_text(self._room_id, text)
        if event_id:
            self._approval_events[event_id] = req.tool_call_id
            # Also register in the channel-level pending maps for reaction handling
            pending = PendingApproval(event_id, req.tool_call_id)
            self._channel._pending_approvals[event_id] = pending
            self._channel._room_pending[self._room_id] = pending

    async def on_proxy_approval_request(self, request_id: str, domain: str, command: str) -> None:
        explanation = ""  # not available at this level
        text = format_domain_escalation(domain, command, explanation)
        event_id = await self._channel._send_text(self._room_id, text)
        if event_id:
            self._domain_events[event_id] = request_id
            pending = PendingDomainApproval(event_id)
            self._channel._pending_domain_approvals[event_id] = pending
            self._channel._room_pending[self._room_id] = pending

    async def on_title_update(self, title: str) -> None:
        pass  # Matrix rooms have their own titles

    async def on_domain_info(self, domain: str, detail: str) -> None:
        logger.debug(f"Matrix [{self._room_id}] domain: {domain} {detail}")
        if self._channel._verbose.get(self._room_id, True):
            notice = f"🌐 `{domain}` {detail}"
            await self._channel._send_notice(self._room_id, notice)
