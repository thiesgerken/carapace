from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from .. import get_version
from ..knowledge import KnowledgeRepoResolver
from ..llm import ModelFactory
from ..models.config import Config
from ..models.user import UserConfig
from .budget import estimate_cost
from .coverage import coverage_hash, month_coverage, week_coverage
from .digest_input import render_month_input, render_week_input
from .input import first_user_message_at, render_extraction_input
from .llm import (
    CallUsage,
    LlmCallError,
    capped_model_settings,
    ensure_fits_context,
    prompt_tokens,
    run_structured,
)
from .models import (
    CoverageEntry,
    DigestLevel,
    DigestRecord,
    DigestResult,
    ExtractionRecord,
    ExtractionResult,
    MemoryTask,
    MirrorResult,
    ModelRole,
    PeriodDigest,
    Provenance,
    SessionExtraction,
    TaskEstimate,
    TaskKind,
    TaskOutcome,
)
from .periods import month_key_for_week, month_weeks, period_dates, week_key
from .prompts import MONTH_DIGEST, SESSION_EXTRACT, WEEK_DIGEST, PromptTemplate
from .render import MIRROR_ROOT, render_mirror


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
# A digest restates themes, highlights and deduplicated facts of up to a month of sources.
DIGEST_OUTPUT_CAP = 6000


@dataclass(frozen=True, slots=True)
class _LlmCall:
    """What an LLM task sends, fixed before it is estimated or run."""

    template: PromptTemplate
    user_prompt: str
    output_cap: int
    input_hash: str
    input_format_version: int


def _estimate(config: Config, call: _LlmCall, model: str) -> TaskEstimate:
    output_cap = capped_model_settings(config, model, call.output_cap)["max_tokens"]
    input_tokens = prompt_tokens(call.template, call.user_prompt, model)
    return TaskEstimate(
        model=model,
        input_tokens=input_tokens,
        output_tokens_cap=output_cap,
        cost_usd=estimate_cost(model, input_tokens, output_cap),
    )


async def _run_llm[OutputT: BaseModel](
    task: MemoryTask,
    model: str,
    call: _LlmCall,
    output_type: type[OutputT],
    *,
    config: Config,
    model_factory: ModelFactory,
) -> tuple[OutputT, Provenance]:
    """Run the call; a billed failure raises ``TaskRunError`` carrying what it cost."""
    ensure_fits_context(config, model, prompt_tokens(call.template, call.user_prompt, model))

    def provenance(usage: CallUsage) -> Provenance:
        return Provenance(
            carapace_version=get_version(),
            model=model,
            prompt_version=call.template.version(output_type),
            input_format_version=call.input_format_version,
            input_hash=call.input_hash,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cost_usd=usage.cost_usd,
            duration_ms=usage.duration_ms,
            task_id=task.id,
            created_at=datetime.now(tz=UTC),
        )

    try:
        result = await run_structured(
            call.template,
            output_type,
            call.user_prompt,
            model=model,
            user=task.user,
            model_factory=model_factory,
            model_settings=capped_model_settings(config, model, call.output_cap),
        )
    except LlmCallError as exc:
        raise TaskRunError(str(exc), provenance=provenance(exc.usage)) from exc
    return result.output, provenance(result.usage)


@dataclass(frozen=True, slots=True)
class _PreparedExtraction:
    call: _LlmCall
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
        return _estimate(self._config, self._prepare(user, target).call, model)

    async def run(self, task: MemoryTask, model: str | None) -> TaskOutcome:
        if model is None:
            raise ValueError("session extraction needs a model")
        prepared = self._prepare(task.user, task.target)
        extraction, provenance = await _run_llm(
            task, model, prepared.call, SessionExtraction, config=self._config, model_factory=self._model_factory
        )
        result = ExtractionResult(
            session_id=task.target,
            week_key=prepared.week_key,
            month_key=month_key_for_week(prepared.week_key),
            extraction=extraction,
        )
        return TaskOutcome(provenance=provenance, result=result)

    def _prepare(self, user: str, session_id: str) -> _PreparedExtraction:
        events = self._load_events(session_id)
        started_at = first_user_message_at(events)
        if started_at is None:
            raise ValueError(f"session {session_id} has no user message to extract")
        tz = ZoneInfo(self._user_config_for(user).timezone)
        rendered = render_extraction_input(events)
        session_date = started_at.astimezone(tz).date().isoformat()
        return _PreparedExtraction(
            call=_LlmCall(
                template=SESSION_EXTRACT,
                user_prompt=SESSION_EXTRACT.user_prompt(rendered.text, session_date=session_date),
                output_cap=SESSION_EXTRACT_OUTPUT_CAP,
                input_hash=rendered.input_hash,
                input_format_version=rendered.input_format_version,
            ),
            week_key=week_key(started_at, tz),
        )


@dataclass(frozen=True, slots=True)
class _PreparedDigest:
    call: _LlmCall
    coverage: list[CoverageEntry]


class DigestHandler:
    """Week or month digest, one instance per level.

    A week reads its sessions' current extractions, a month the current digests of its weeks
    (those whose Thursday falls into it). Partial coverage is fine: the digest records what it
    consumed and goes stale when more arrives.
    """

    model_role = ModelRole.memory_high

    def __init__(
        self,
        *,
        level: DigestLevel,
        config: Config,
        current_extractions: Callable[[str, str], list[ExtractionRecord]],
        current_digests: Callable[[str, DigestLevel, list[str]], list[DigestRecord]],
        model_factory: ModelFactory,
    ) -> None:
        self.level = level
        self.kind = TaskKind.week_digest if level is DigestLevel.week else TaskKind.month_digest
        self._config = config
        self._current_extractions = current_extractions
        self._current_digests = current_digests
        self._model_factory = model_factory

    async def estimate(self, user: str, target: str, model: str) -> TaskEstimate:
        return _estimate(self._config, self._prepare(user, target).call, model)

    async def run(self, task: MemoryTask, model: str | None) -> TaskOutcome:
        if model is None:
            raise ValueError(f"{self.level} digests need a model")
        prepared = self._prepare(task.user, task.target)
        digest, provenance = await _run_llm(
            task, model, prepared.call, PeriodDigest, config=self._config, model_factory=self._model_factory
        )
        result = DigestResult(
            level=self.level,
            period_key=task.target,
            coverage=prepared.coverage,
            coverage_hash=coverage_hash(prepared.coverage),
            digest=digest,
        )
        return TaskOutcome(provenance=provenance, result=result)

    def _prepare(self, user: str, period_key: str) -> _PreparedDigest:
        match self.level:
            case DigestLevel.week:
                extractions = self._current_extractions(user, period_key)
                rendered, coverage = render_week_input(extractions), week_coverage(extractions)
                first_day, last_day = period_dates(self.level, period_key)
                template = WEEK_DIGEST
                user_prompt = WEEK_DIGEST.user_prompt(
                    rendered.text,
                    period_key=period_key,
                    first_day=first_day.isoformat(),
                    last_day=last_day.isoformat(),
                )
            case DigestLevel.month:
                weeks = self._current_digests(user, DigestLevel.week, month_weeks(period_key))
                rendered, coverage = render_month_input(weeks), month_coverage(weeks)
                template = MONTH_DIGEST
                user_prompt = MONTH_DIGEST.user_prompt(rendered.text, period_key=period_key)
        if not coverage:
            raise ValueError(f"{self.level} {period_key} has no current sources to digest")
        return _PreparedDigest(
            call=_LlmCall(
                template=template,
                user_prompt=user_prompt,
                output_cap=DIGEST_OUTPUT_CAP,
                input_hash=rendered.input_hash,
                input_format_version=rendered.input_format_version,
            ),
            coverage=coverage,
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
        _sync_mirror(handle.knowledge_dir, files)
        # Always commit, not only after a disk change: a run that wrote files but never committed
        # (crash, failed commit) must be caught up by the next one. `git add memory` stages
        # removals too, so new, changed and deleted files form one commit; GitStore's index lock
        # keeps it apart from concurrent session archive commits.
        commit = await handle.git_store.commit_returning_sha(
            [MIRROR_ROOT], f"🧠 memory: update mirror ({len(files) - 1} records)"
        )
        if commit is not None:
            await self._push_if_configured(task.user)
        return TaskOutcome(provenance=None, result=MirrorResult(commit=commit))


def _sync_mirror(knowledge_dir: Path, files: dict[str, str]) -> None:
    """Make ``memory/`` contain exactly *files*.

    The agent can push anything into the knowledge repo, symlinks included. Every symlink under
    ``memory/`` is removed before writing, so a write can never be redirected outside the mirror.
    """
    mirror_dir = knowledge_dir / MIRROR_ROOT
    if mirror_dir.is_symlink():
        mirror_dir.unlink()
    existing: set[str] = set()
    for dirpath, dirnames, filenames in os.walk(mirror_dir):
        directory = Path(dirpath)
        for name in [*dirnames, *filenames]:
            path = directory / name
            if path.is_symlink():
                path.unlink()
            elif name in filenames:
                existing.add(path.relative_to(knowledge_dir).as_posix())
        dirnames[:] = [name for name in dirnames if (directory / name).is_dir()]

    for stale in existing - files.keys():
        (knowledge_dir / stale).unlink()
    for relative, content in files.items():
        target = knowledge_dir / relative
        if relative in existing and target.read_text(encoding="utf-8") == content:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    for dirpath, _, _ in sorted(os.walk(mirror_dir), key=lambda entry: len(entry[0]), reverse=True):
        if dirpath != str(mirror_dir) and not any(Path(dirpath).iterdir()):
            Path(dirpath).rmdir()
