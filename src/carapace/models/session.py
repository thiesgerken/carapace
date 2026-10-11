from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .skills import ContextGrant


class SessionBudget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: Decimal | None = None
    tool_calls: int | None = None

    @model_validator(mode="after")
    def _normalize_limits(self) -> SessionBudget:
        if self.input_tokens is not None:
            if self.input_tokens < 0:
                raise ValueError("budget.input_tokens must be >= 0")
            if self.input_tokens == 0:
                self.input_tokens = None
        if self.output_tokens is not None:
            if self.output_tokens < 0:
                raise ValueError("budget.output_tokens must be >= 0")
            if self.output_tokens == 0:
                self.output_tokens = None
        if self.cost_usd is not None:
            if self.cost_usd < 0:
                raise ValueError("budget.cost_usd must be >= 0")
            if self.cost_usd == Decimal(0):
                self.cost_usd = None
        if self.tool_calls is not None:
            if self.tool_calls < 0:
                raise ValueError("budget.tool_calls must be >= 0")
            if self.tool_calls == 0:
                self.tool_calls = None
        return self

    @property
    def has_any_limit(self) -> bool:
        return any(
            limit is not None for limit in (self.input_tokens, self.output_tokens, self.cost_usd, self.tool_calls)
        )


class SessionAttributes(BaseModel):
    private: bool = Field(default=False, description="Exclude this session from knowledge commits.")
    archived: bool = Field(default=False, description="Hide this session from the default active session list.")
    pinned: bool = Field(default=False, description="Keep this session pinned to the top of session lists.")
    favorite: bool = Field(default=False, description="Mark this session as a favorite in the UI.")
    unattended: bool = Field(
        default=False,
        description="Run without a user approval path. This is set on creation or fork and cannot be changed in place.",
    )
    ask_mode: bool = Field(
        default=False,
        description=(
            "Restrict the agent to read-only operations outside the sandbox while " + "keeping sentinel review enabled."
        ),
    )
    yolo_mode: bool = Field(
        default=False,
        description="Bypass sentinel review and allow operations immediately.",
    )

    @model_validator(mode="after")
    def _validate_modes(self) -> SessionAttributes:
        if self.ask_mode and self.yolo_mode:
            raise ValueError("session attributes ask_mode and yolo_mode are mutually exclusive")
        return self


class MemorySnapshot(BaseModel):
    """The memory block of the agent's system prompt, frozen for a session.

    A changed system prompt invalidates the whole cached conversation behind it, so the block is
    rendered once and only refreshed when compaction rewrites the history anyway.
    """

    # Empty when memory in the prompt is off or nothing was selected.
    text: str
    as_of: datetime


class SessionJobRunContext(BaseModel):
    job_id: str
    trigger_kind: Literal["api", "cron", "manual"]
    triggered_at: datetime
    data: str | None = None
    cron_expression: str | None = None


class SessionState(BaseModel):
    session_id: str
    channel_type: str = "cli"
    channel_ref: str | None = None
    title: str | None = None
    agent_model_name: str | None = None
    sentinel_model_name: str | None = None
    title_model_name: str | None = None
    compaction_model_name: str | None = None
    attributes: Annotated[SessionAttributes, Field(default_factory=SessionAttributes)]
    approved_operations: Annotated[list[str], Field(default_factory=list)]
    activated_skills: Annotated[list[str], Field(default_factory=list)]
    context_grants: Annotated[dict[str, ContextGrant], Field(default_factory=dict)]
    budget: Annotated[SessionBudget, Field(default_factory=SessionBudget)]
    created_at: datetime
    last_active: datetime
    latest_job_run: SessionJobRunContext | None = None
    knowledge_last_committed_at: datetime | None = None
    knowledge_last_archive_path: str | None = None
    knowledge_last_export_hash: str | None = None
    knowledge_last_commit_trigger: str | None = None
    # None until the session's first agent prompt is built, and again after compaction.
    memory: MemorySnapshot | None = None

    @classmethod
    def now(
        cls,
        *,
        session_id: str,
        channel_type: str = "cli",
        channel_ref: str | None = None,
        title: str | None = None,
        private: bool = False,
        unattended: bool = False,
        ask_mode: bool = False,
        yolo_mode: bool = False,
        approved_operations: list[str] | None = None,
    ) -> SessionState:
        ts = datetime.now(tz=UTC)
        return cls(
            session_id=session_id,
            channel_type=channel_type,
            channel_ref=channel_ref,
            title=title,
            attributes=SessionAttributes(
                private=private,
                unattended=unattended,
                ask_mode=ask_mode,
                yolo_mode=yolo_mode,
            ),
            approved_operations=approved_operations or [],
            activated_skills=[],
            context_grants={},
            budget=SessionBudget(),
            created_at=ts,
            last_active=ts,
        )
