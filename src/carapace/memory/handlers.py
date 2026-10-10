from __future__ import annotations

from typing import Protocol

from .models import MemoryTask, ModelRole, TaskEstimate, TaskKind, TaskOutcome


class TaskHandler(Protocol):
    """Executes one task kind. The worker dispatches through ``dict[TaskKind, TaskHandler]``."""

    kind: TaskKind
    # None for tasks without an LLM call (mirror).
    model_role: ModelRole | None

    async def estimate(self, task: MemoryTask, model: str) -> TaskEstimate: ...

    async def run(self, task: MemoryTask, model: str) -> TaskOutcome: ...
