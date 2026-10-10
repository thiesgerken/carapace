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
from ..usage import count_text_tokens
from .budget import estimate_cost
from .input import ExtractionInput, first_user_message_at, render_extraction_input
from .llm import capped_model_settings, run_structured
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

    kind: TaskKind
    # None for tasks without an LLM call (mirror).
    model_role: ModelRole | None

    async def estimate(self, task: MemoryTask, model: str) -> TaskEstimate: ...

    async def run(self, task: MemoryTask, model: str) -> TaskOutcome: ...


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

    async def estimate(self, task: MemoryTask, model: str) -> TaskEstimate:
        prepared = self._prepare(task)
        output_cap = capped_model_settings(self._config, model, SESSION_EXTRACT_OUTPUT_CAP)["max_tokens"]
        input_tokens = count_text_tokens(f"{SESSION_EXTRACT.system}\n\n{prepared.user_prompt}", model_name=model)
        return TaskEstimate(
            model=model,
            input_tokens=input_tokens,
            output_tokens_cap=output_cap,
            cost_usd=estimate_cost(model, input_tokens, output_cap),
        )

    async def run(self, task: MemoryTask, model: str) -> TaskOutcome:
        prepared = self._prepare(task)
        call = await run_structured(
            SESSION_EXTRACT,
            SessionExtraction,
            prepared.user_prompt,
            model=model,
            user=task.user,
            model_factory=self._model_factory,
            model_settings=capped_model_settings(self._config, model, SESSION_EXTRACT_OUTPUT_CAP),
        )
        provenance = Provenance(
            carapace_version=get_version(),
            model=model,
            prompt_version=SESSION_EXTRACT.version(SessionExtraction),
            input_format_version=prepared.rendered.input_format_version,
            input_hash=prepared.rendered.input_hash,
            input_tokens=call.input_tokens,
            output_tokens=call.output_tokens,
            cost_usd=call.cost_usd,
            duration_ms=call.duration_ms,
            task_id=task.id,
            created_at=datetime.now(tz=UTC),
        )
        result = ExtractionResult(
            session_id=task.target,
            week_key=prepared.week_key,
            month_key=month_key_for_week(prepared.week_key),
            extraction=call.output,
        )
        return TaskOutcome(provenance=provenance, result=result)

    def _prepare(self, task: MemoryTask) -> _PreparedExtraction:
        events = self._load_events(task.target)
        started_at = first_user_message_at(events)
        if started_at is None:
            raise ValueError(f"session {task.target} has no user message to extract")
        tz = ZoneInfo(self._user_config_for(task.user).timezone)
        rendered = render_extraction_input(events)
        return _PreparedExtraction(
            rendered=rendered,
            user_prompt=SESSION_EXTRACT.user_prompt(
                rendered.text, session_date=started_at.astimezone(tz).date().isoformat()
            ),
            week_key=week_key(started_at, tz),
        )
