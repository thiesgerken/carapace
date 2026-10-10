from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from .. import get_version
from ..knowledge import KnowledgeRepoResolver
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
    DigestLevel,
    DigestRecord,
    ExtractionRecord,
    ExtractionResult,
    MemoryTask,
    MirrorResult,
    ModelRole,
    Provenance,
    SessionExtraction,
    TaskEstimate,
    TaskKind,
    TaskOutcome,
)
from .periods import month_key_for_week, week_key
from .prompts import SESSION_EXTRACT
from .render import MIRROR_ROOT, render_mirror


class TaskHandler(Protocol):
    """Executes one task kind. The worker dispatches through ``dict[TaskKind, TaskHandler]``."""

    kind: TaskKind
    # None for tasks without an LLM call (mirror): they get no estimate and run with model None.
    model_role: ModelRole | None

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


class MirrorHandler:
    """Writes the user's current memory records into ``memory/`` of their knowledge repo.

    One commit per run however many records changed; the worker debounces runs, so a backfill of
    many extractions ends up in few commits.
    """

    kind = TaskKind.mirror
    model_role = None

    def __init__(
        self,
        *,
        current_extractions: Callable[[str], list[ExtractionRecord]],
        current_digests: Callable[[str, DigestLevel], list[DigestRecord]],
        knowledge_repo_for_user: KnowledgeRepoResolver,
        push_if_configured: Callable[[str], Awaitable[None]],
    ) -> None:
        self._current_extractions = current_extractions
        self._current_digests = current_digests
        self._knowledge_repo_for_user = knowledge_repo_for_user
        self._push_if_configured = push_if_configured

    async def estimate(self, user: str, target: str, model: str) -> TaskEstimate:
        raise ValueError("mirror tasks are free and never estimated")

    async def run(self, task: MemoryTask, model: str | None) -> TaskOutcome:
        if model is not None:
            raise ValueError("mirror tasks run without a model")
        digests = [
            *self._current_digests(task.user, DigestLevel.week),
            *self._current_digests(task.user, DigestLevel.month),
        ]
        files = render_mirror(self._current_extractions(task.user), digests)

        handle = self._knowledge_repo_for_user(task.user)
        if not (handle.knowledge_dir / ".git").exists():
            await handle.git_store.ensure_repo()
        commit = None
        # `git add memory` stages removals too, so new, changed and deleted files form one commit;
        # GitStore's index lock keeps it apart from concurrent session archive commits.
        if _sync_mirror(handle.knowledge_dir, files) and await handle.git_store.commit(
            [MIRROR_ROOT], f"🧠 memory: update mirror ({len(files) - 1} records)"
        ):
            commit = await handle.git_store.head_sha()
            await self._push_if_configured(task.user)
        return TaskOutcome(provenance=None, result=MirrorResult(commit=commit))


def _sync_mirror(knowledge_dir: Path, files: dict[str, str]) -> bool:
    """Make ``memory/`` contain exactly *files*. Returns whether anything on disk changed.

    The agent can push anything into the knowledge repo, symlinks included. Every symlink under
    ``memory/`` is removed before writing, so a write can never be redirected outside the mirror.
    """
    mirror_dir = knowledge_dir / MIRROR_ROOT
    changed = False
    if mirror_dir.is_symlink():
        mirror_dir.unlink()
        changed = True
    existing: set[str] = set()
    for dirpath, dirnames, filenames in os.walk(mirror_dir):
        directory = Path(dirpath)
        for name in [*dirnames, *filenames]:
            path = directory / name
            if path.is_symlink():
                path.unlink()
                changed = True
            elif name in filenames:
                existing.add(path.relative_to(knowledge_dir).as_posix())
        dirnames[:] = [name for name in dirnames if (directory / name).is_dir()]

    for stale in existing - files.keys():
        (knowledge_dir / stale).unlink()
        changed = True
    for relative, content in files.items():
        target = knowledge_dir / relative
        if relative in existing and target.read_text(encoding="utf-8") == content:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        changed = True

    for dirpath, _, _ in sorted(os.walk(mirror_dir), key=lambda entry: len(entry[0]), reverse=True):
        if dirpath != str(mirror_dir) and not any(Path(dirpath).iterdir()):
            Path(dirpath).rmdir()
    return changed
