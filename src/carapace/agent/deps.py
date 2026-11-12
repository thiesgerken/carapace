from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models import Model
from pydantic_ai.usage import UsageLimits

from ..git.store import GitStore
from ..models.config import Config
from ..models.credentials import CredentialRegistryProtocol
from ..models.session import SessionState
from ..models.skills import SkillInfo
from ..models.tooling import ToolCallCallback, ToolResult
from ..sandbox.manager import SandboxManager
from ..security.context import SessionSecurity
from ..security.sentinel import Sentinel
from ..usage import UsageTracker
from .autonomy import AutonomyStreak


class TaskDone(BaseModel):
    """Explicit unattended completion output for successful runs."""

    result: str


class TaskFailed(BaseModel):
    """Explicit unattended completion output for blocked or failed runs."""

    problem: str


class Deps(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    config: Config
    data_dir: Path
    knowledge_dir: Path
    session_state: SessionState
    sandbox: SandboxManager
    security: SessionSecurity
    sentinel: Sentinel
    git_store: GitStore
    skill_catalog: list[SkillInfo] = []
    activated_skills: list[str] = []
    agent_model: Model
    agent_model_id: str = Field(
        description="carapace-registered model id (custom id or provider:name); usage keys, not provider wire ids.",
    )

    # Live MCPToolset instances keyed by "<skill>:<server>", built lazily from
    # active context grants. Cached here so per-run-step toolset evaluation
    # reuses connections instead of re-handshaking every step.
    mcp_toolsets: dict[str, Any] = {}

    tool_call_callback: ToolCallCallback | None = None
    tool_result_callback: Callable[[ToolResult], None] | None = None
    append_session_events: Callable[[list[dict[str, Any]]], None] | None = None
    usage_tracker: UsageTracker
    autonomy: AutonomyStreak
    assert_llm_budget_available: Callable[[], None] | None = None
    llm_usage_limits: Callable[[], UsageLimits | None] | None = None
    # Compacts the run's history before a model request, or returns None to keep it.
    compact_history: Callable[[list[ModelMessage]], Awaitable[list[ModelMessage] | None]] | None = None
    credential_registry: CredentialRegistryProtocol
