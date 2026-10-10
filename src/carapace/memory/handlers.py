from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from .. import get_version
from ..llm import ModelFactory
from ..models.config import Config
from ..models.user import UserConfig
from .budget import estimate_cost
from .input import ExtractionInput, first_user_message_at, render_extraction_input
from .llm import (
    CallUsage,
    LlmCallError,
    capped_model_settings,
    ensure_fits_context,
    prompt_tokens,
    run_structured,
)
from .models import (
    ExtractionResult,
    MemoryTask,
    ModelRole,
    Provenance,
    SessionExtraction,
    TaskEstimate,
    TaskKind,
    TaskOutcome,
)
from .periods import month_key_for_week, week_key
from .prompts import SESSION_EXTRACT


class TaskHandler(Protocol):
    """Executes one task kind. The worker dispatches through ``dict[TaskKind, TaskHandler]``."""

    # Read-only, so implementations may narrow the types (a class attribute ModelRole.memory_low).
    @property
    def kind(self) -> TaskKind: ...

    # None for tasks without an LLM call (mirror): they get no estimate and run with model None.
    @property
    def model_role(self) -> ModelRole | None: ...

    async def estimate(self, user: str, target: str, model: str) -> TaskEstimate:
        """Called before the task exists: the store only spawns estimated LLM tasks."""
        ...

    async def run(self, task: MemoryTask, model: str | None) -> TaskOutcome: ...


class TaskRunError(Exception):
    """A run that failed after the provider billed it: its usage still counts towards spend.

    Raise this (not a bare exception) once the LLM call has consumed tokens, e.g. when output
    validation retries are exhausted or a usage limit is hit mid-run.
    """

    def __init__(self, message: str, provenance: Provenance) -> None:
        super().__init__(message)
        self.provenance = provenance


# Upper bound for one extraction's output; abstract, lists and facts of a long session fit well below.
SESSION_EXTRACT_OUTPUT_CAP = 4000


@dataclass(frozen=True, slots=True)
class _PreparedExtraction:
    rendered: ExtractionInput
    user_prompt: str
    week_key: str


class SessionExtractHandler:
    kind = TaskKind.session_extract
    model_role = ModelRole.memory_low

    def __init__(
        self,
        *,
        config: Config,
        load_events: Callable[[str], list[dict[str, Any]]],
        user_config_for: Callable[[str], UserConfig],
        model_factory: ModelFactory,
    ) -> None:
        self._config = config
        self._load_events = load_events
        self._user_config_for = user_config_for
        self._model_factory = model_factory

    async def estimate(self, user: str, target: str, model: str) -> TaskEstimate:
        prepared = self._prepare(user, target)
        output_cap = capped_model_settings(self._config, model, SESSION_EXTRACT_OUTPUT_CAP)["max_tokens"]
        input_tokens = prompt_tokens(SESSION_EXTRACT, prepared.user_prompt, model)
        return TaskEstimate(
            model=model,
            input_tokens=input_tokens,
            output_tokens_cap=output_cap,
            cost_usd=estimate_cost(model, input_tokens, output_cap),
        )

    async def run(self, task: MemoryTask, model: str | None) -> TaskOutcome:
        if model is None:
            raise ValueError("session extraction needs a model")
        prepared = self._prepare(task.user, task.target)
        ensure_fits_context(self._config, model, prompt_tokens(SESSION_EXTRACT, prepared.user_prompt, model))
        try:
            call = await run_structured(
                SESSION_EXTRACT,
                SessionExtraction,
                prepared.user_prompt,
                model=model,
                user=task.user,
                model_factory=self._model_factory,
                model_settings=capped_model_settings(self._config, model, SESSION_EXTRACT_OUTPUT_CAP),
            )
        except LlmCallError as exc:
            raise TaskRunError(str(exc), provenance=_provenance(task, model, prepared, exc.usage)) from exc
        result = ExtractionResult(
            session_id=task.target,
            week_key=prepared.week_key,
            month_key=month_key_for_week(prepared.week_key),
            extraction=call.output,
        )
        return TaskOutcome(provenance=_provenance(task, model, prepared, call.usage), result=result)

    def _prepare(self, user: str, session_id: str) -> _PreparedExtraction:
        events = self._load_events(session_id)
        started_at = first_user_message_at(events)
        if started_at is None:
            raise ValueError(f"session {session_id} has no user message to extract")
        tz = ZoneInfo(self._user_config_for(user).timezone)
        rendered = render_extraction_input(events)
        return _PreparedExtraction(
            rendered=rendered,
            user_prompt=SESSION_EXTRACT.user_prompt(
                rendered.text, session_date=started_at.astimezone(tz).date().isoformat()
            ),
            week_key=week_key(started_at, tz),
        )


def _provenance(task: MemoryTask, model: str, prepared: _PreparedExtraction, usage: CallUsage) -> Provenance:
    return Provenance(
        carapace_version=get_version(),
        model=model,
        prompt_version=SESSION_EXTRACT.version(SessionExtraction),
        input_format_version=prepared.rendered.input_format_version,
        input_hash=prepared.rendered.input_hash,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cost_usd=usage.cost_usd,
        duration_ms=usage.duration_ms,
        task_id=task.id,
        created_at=datetime.now(tz=UTC),
    )
