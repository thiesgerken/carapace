from __future__ import annotations

from typing import Protocol

from .models import MemoryTask, ModelRole, Provenance, TaskEstimate, TaskKind, TaskOutcome


class TaskHandler(Protocol):
    """Executes one task kind. The worker dispatches through ``dict[TaskKind, TaskHandler]``."""

    kind: TaskKind
    # None for tasks without an LLM call (mirror): they get no estimate and run with model None.
    model_role: ModelRole | None

    async def estimate(self, task: MemoryTask, model: str) -> TaskEstimate: ...

    async def run(self, task: MemoryTask, model: str | None) -> TaskOutcome: ...


class TaskRunError(Exception):
    """A run that failed after the provider billed it: its usage still counts towards spend.

    Raise this (not a bare exception) once the LLM call has consumed tokens, e.g. when output
    validation retries are exhausted or a usage limit is hit mid-run.
    """

    def __init__(self, message: str, provenance: Provenance) -> None:
        super().__init__(message)
        self.provenance = provenance
