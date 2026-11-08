"""Routing of escalation answers to the callbacks waiting for them."""

from __future__ import annotations

import asyncio
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field

from ..ws_models import EscalationResponse


@dataclass
class EscalationWaiters:
    """One future per open escalation request, so every answer reaches its own waiter.

    Several escalations can wait at once (domain checks from parallel proxy connections, credential
    and git push requests alongside them). A future resolved with ``None`` means the request was
    released without an answer (turn cancelled or finalized) and must be treated as denied.
    """

    _futures: dict[str, asyncio.Future[EscalationResponse | None]] = field(default_factory=dict)

    @contextmanager
    def waiting(self, request_id: str) -> Generator[asyncio.Future[EscalationResponse | None]]:
        future: asyncio.Future[EscalationResponse | None] = asyncio.get_running_loop().create_future()
        self._futures[request_id] = future
        try:
            yield future
        finally:
            del self._futures[request_id]

    def answer(self, response: EscalationResponse) -> bool:
        """Resolve the waiter *response* is addressed to; False when nobody waits for it anymore."""
        future = self._futures.get(response.request_id)
        if future is None or future.done():
            return False
        future.set_result(response)
        return True

    def release_all(self) -> None:
        for future in self._futures.values():
            if not future.done():
                future.set_result(None)
