"""Approval tracking classes and decision constants for the Matrix channel."""

from __future__ import annotations

import asyncio

# Reactions used for approval decisions
APPROVE_REACTIONS = {"✅", "👍", "✓", "✔", "✔️", "👍🏻", "👍🏼", "👍🏽", "👍🏾", "👍🏿"}
DENY_REACTIONS = {"❌", "👎", "✗", "🚫", "👎🏻", "👎🏼", "👎🏽", "👎🏾", "👎🏿"}

# Commands that mean "approve" or "deny"
APPROVE_COMMANDS = {"/allow", "/yes"}
DENY_COMMANDS = {"/deny", "/no"}

# Typing notification interval in seconds
TYPING_INTERVAL = 10.0


class PendingApproval:
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


class PendingDomainApproval:
    """Tracks a pending proxy domain approval message in a room."""

    def __init__(self, event_id: str) -> None:
        self.event_id = event_id
        self._future: asyncio.Future[bool] = asyncio.get_running_loop().create_future()

    def resolve(self, approved: bool) -> None:
        if not self._future.done():
            self._future.set_result(approved)

    async def wait(self) -> bool:
        return await self._future
