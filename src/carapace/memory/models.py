from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

# --- Enums ---


class TaskKind(StrEnum):
    session_extract = "session_extract"
    week_digest = "week_digest"
    month_digest = "month_digest"
    mirror = "mirror"


class TaskStatus(StrEnum):
    pending = "pending"
    queued = "queued"
    running = "running"
    done = "done"
    failed = "failed"
    cancelled = "cancelled"


# At most one open task per (user, kind, target); the partial unique index on memory_tasks
# spells out the same set.
OPEN_TASK_STATUSES = frozenset({TaskStatus.pending, TaskStatus.queued, TaskStatus.running})


class BlockedReason(StrEnum):
    budget = "budget"


class SpawnedBy(StrEnum):
    auto = "auto"
    manual = "manual"


class ModelRole(StrEnum):
    memory_low = "memory_low"
    memory_high = "memory_high"


class DigestLevel(StrEnum):
    week = "week"
    month = "month"


class FactCategory(StrEnum):
    user = "user"
    social = "social"
    surroundings = "surroundings"


class FactSourceKind(StrEnum):
    user_said = "user_said"
    observed = "observed"


class Confidence(StrEnum):
    low = "low"
    medium = "medium"
    high = "high"


class Durability(StrEnum):
    durable = "durable"
    dated = "dated"


class OutdatedReason(StrEnum):
    """Why a record no longer matches what a fresh run would produce. Never auto-respawned."""

    prompt_version = "prompt_version"
    model = "model"
    input_format_version = "input_format_version"


class ExtractionState(StrEnum):
    missing = "missing"
    current = "current"
    outdated = "outdated"


# --- LLM output schemas ---


class _FactBase(BaseModel):
    category: FactCategory
    statement: str
    subject: str | None = None
    source_kind: FactSourceKind
    confidence: Confidence
    durability: Durability
    valid_until: date | None = None

    @model_validator(mode="after")
    def _validate_provenance_rules(self) -> Self:
        if self.category is FactCategory.social and not self.subject:
            raise ValueError("social facts need a subject")
        # Tool output must not become facts about the user or their people: those end up in a
        # system prompt later, so they may only come from what the user said.
        if self.source_kind is FactSourceKind.observed and self.category is not FactCategory.surroundings:
            raise ValueError("observed facts may only be surroundings facts")
        return self


class Fact(_FactBase):
    source_seqs: list[int]


class SessionExtraction(BaseModel):
    abstract: str
    outcomes: list[str]
    open_loops: list[str]
    on_my_mind: list[str]
    facts: list[Fact]
    friction: list[str]
    tags: list[str]


class DigestTheme(BaseModel):
    theme: str
    # Session ids (week digests) or week keys (month digests) the theme came from.
    refs: list[str]


class DigestFact(_FactBase):
    """A deduplicated fact; ``user_said`` only if every merged source was."""

    # Session ids (week digests) or week keys (month digests) the fact came from.
    refs: list[str]


class PeriodDigest(BaseModel):
    """LLM output for week and month digests.

    Stats (session count, coverage) are computed from the record's coverage, not generated.
    """

    summary: str
    on_my_mind: list[DigestTheme]
    highlights: list[str]
    open_loops: list[str]
    learned: list[DigestFact]


# --- Provenance, estimates, outcomes ---


class Provenance(BaseModel):
    carapace_version: str
    model: str
    prompt_version: str
    input_format_version: int
    input_hash: str
    input_tokens: int
    output_tokens: int
    # None when the model has no known pricing (local models).
    cost_usd: Decimal | None
    duration_ms: int
    task_id: int
    created_at: datetime


class TaskEstimate(BaseModel):
    model: str
    input_tokens: int
    output_tokens_cap: int
    # None when the model has no known pricing (local models).
    cost_usd: Decimal | None


class CoverageEntry(BaseModel):
    # Session id (week digests) or week key (month digests).
    source_id: str
    source_hash: str


class ExtractionResult(BaseModel):
    kind: Literal["extraction"] = "extraction"
    session_id: str
    week_key: str
    month_key: str
    extraction: SessionExtraction


class DigestResult(BaseModel):
    kind: Literal["digest"] = "digest"
    level: DigestLevel
    period_key: str
    coverage: list[CoverageEntry]
    coverage_hash: str
    digest: PeriodDigest


class MirrorResult(BaseModel):
    kind: Literal["mirror"] = "mirror"
    # None when the rendered files matched the repo and nothing was committed.
    commit: str | None


class TaskOutcome(BaseModel):
    """What a handler returns; the worker persists it together with the task result."""

    # None for mirror tasks, which make no LLM call.
    provenance: Provenance | None
    result: Annotated[ExtractionResult | DigestResult | MirrorResult, Field(discriminator="kind")]


class MemoryTask(BaseModel):
    id: int
    user: str
    kind: TaskKind
    target: str
    status: TaskStatus
    # Period the target falls into: the session's week for extractions, the target for digests.
    week_key: str | None = None
    month_key: str | None = None
    # Model of the latest estimate, replaced by the model that actually ran on completion.
    model: str | None = None
    blocked_reason: BlockedReason | None = None
    spawned_by: SpawnedBy
    model_override: str | None = None
    attempts: int = 0
    # None for mirror tasks (free) and until the task has been estimated.
    estimate: TaskEstimate | None = None
    provenance: Provenance | None = None
    result_id: int | None = None
    error: str | None = None
    created_at: datetime
    queued_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


# --- Stored records ---


class ExtractionRecord(BaseModel):
    id: int
    session_id: str
    week_key: str
    month_key: str
    is_current: bool
    input_hash: str
    provenance: Provenance
    extraction: SessionExtraction
    created_at: datetime


class DigestRecord(BaseModel):
    id: int
    level: DigestLevel
    period_key: str
    is_current: bool
    coverage: list[CoverageEntry]
    coverage_hash: str
    provenance: Provenance
    digest: PeriodDigest
    created_at: datetime


# --- API views (/api/memory) ---


class MemoryApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BudgetWindowStatus(MemoryApiModel):
    window_start: datetime
    spent_cost_usd: Decimal
    spent_input_tokens: int
    limit_cost_usd: Decimal | None
    limit_input_tokens: int | None


class EffectiveMemoryModels(MemoryApiModel):
    memory_low: str
    memory_high: str


class MemoryStatus(MemoryApiModel):
    auto_mode: bool
    timezone: str
    day: BudgetWindowStatus
    month: BudgetWindowStatus
    queue: dict[TaskStatus, int]
    # Queued tasks held back by the budget gate.
    blocked: int
    models: EffectiveMemoryModels


class TaskFilter(MemoryApiModel):
    status: list[TaskStatus] | None = None
    kind: list[TaskKind] | None = None
    # Week (2026-W36) or month (2026-09) key the task's target falls into.
    period: str | None = None
    model: str | None = None


class TaskSelection(MemoryApiModel):
    """Exactly one of explicit ids or a filter; ``newest`` limits a filter to its newest N."""

    ids: list[int] | None = None
    filter: TaskFilter | None = None
    newest: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _validate_selection(self) -> TaskSelection:
        if (self.ids is None) == (self.filter is None):
            raise ValueError("select tasks by either ids or filter")
        if self.newest is not None and self.filter is None:
            raise ValueError("newest requires a filter")
        return self


class TaskRunRequest(MemoryApiModel):
    selection: TaskSelection
    model_override: str | None = None


class TaskIdsRequest(MemoryApiModel):
    ids: list[int] = Field(min_length=1)


class TaskSpawnRequest(MemoryApiModel):
    kind: TaskKind
    targets: list[str] = Field(min_length=1)
    model_override: str | None = None


class TaskCountResponse(MemoryApiModel):
    count: int


class TaskSpawnResponse(MemoryApiModel):
    task_ids: list[int]


class EstimateTotal(MemoryApiModel):
    task_count: int
    input_tokens: int
    output_tokens_cap: int
    # Sum over priced tasks only; unpriced_count says how many had no known pricing.
    cost_usd: Decimal
    unpriced_count: int


class TaskView(MemoryTask):
    # Human label for the target: session title, or the period key for digests.
    target_label: str


class TaskListResponse(MemoryApiModel):
    items: list[TaskView]
    next_cursor: str | None
    total: int
    estimate: EstimateTotal


class TaskRef(MemoryApiModel):
    id: int
    status: TaskStatus
    blocked_reason: BlockedReason | None


class FactCounts(MemoryApiModel):
    user: int
    social: int
    surroundings: int


class ExtractionSummary(MemoryApiModel):
    id: int
    abstract: str
    fact_counts: FactCounts
    model: str
    prompt_version: str
    cost_usd: Decimal | None
    created_at: datetime
    # Empty when current.
    outdated: list[OutdatedReason]


class SessionMemoryFilter(MemoryApiModel):
    week: str | None = None
    state: list[ExtractionState] | None = None
    task_status: list[TaskStatus] | None = None
    model: str | None = None
    channel: str | None = None


class SessionMemoryRow(MemoryApiModel):
    session_id: str
    title: str | None
    channel_type: str
    # First user message; defines the session's period. None if the session has none yet.
    started_at: datetime | None
    week_key: str | None
    extraction: ExtractionSummary | None
    task: TaskRef | None


class SessionMemoryListResponse(MemoryApiModel):
    items: list[SessionMemoryRow]
    next_cursor: str | None
    total: int


class SessionMemoryDetail(MemoryApiModel):
    session: SessionMemoryRow
    current: ExtractionRecord | None
    # Earlier extractions (other models / prompt versions / inputs), newest first.
    history: list[ExtractionRecord]


class DigestSummary(MemoryApiModel):
    id: int
    model: str
    prompt_version: str
    carapace_version: str
    cost_usd: Decimal | None
    created_at: datetime
    # Empty when current.
    outdated: list[OutdatedReason]


class PeriodNode(MemoryApiModel):
    level: DigestLevel
    key: str
    start: date
    end: date
    # Sources with a current record vs. all sources: extracted/eligible sessions for a week,
    # weeks with a current digest/weeks for a month.
    covered: int
    total: int
    digest: DigestSummary | None
    # The current digest's coverage no longer matches the period's current sources.
    stale: bool
    task: TaskRef | None


class MonthNode(PeriodNode):
    weeks: list[PeriodNode]


class PeriodTree(MemoryApiModel):
    months: list[MonthNode]


class PeriodDetail(MemoryApiModel):
    node: PeriodNode
    current: DigestRecord | None
    history: list[DigestRecord]
    # Sources of the period: sessions for a week, weeks for a month (the other list is empty).
    sessions: list[SessionMemoryRow]
    weeks: list[PeriodNode]


class FactFilter(MemoryApiModel):
    category: list[FactCategory] | None = None
    subject: str | None = None
    confidence: list[Confidence] | None = None
    durability: list[Durability] | None = None
    source_kind: list[FactSourceKind] | None = None
    # Week (2026-W36) or month (2026-09) key.
    period: str | None = None


class FactView(MemoryApiModel):
    id: int
    extraction_id: int
    session_id: str
    session_title: str | None
    category: FactCategory
    subject: str | None
    statement: str
    source_kind: FactSourceKind
    confidence: Confidence
    durability: Durability
    valid_until: date | None
    source_seqs: list[int]
    week_key: str
    created_at: datetime


class FactListResponse(MemoryApiModel):
    items: list[FactView]
