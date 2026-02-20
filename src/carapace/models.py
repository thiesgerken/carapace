from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel
from pydantic_ai.usage import RunUsage

# --- Rules ---


class RuleMode(str, Enum):
    approve = "approve"
    block = "block"


class Rule(BaseModel):
    id: str
    trigger: str
    effect: str
    mode: RuleMode = RuleMode.approve
    description: str = ""


class RulesConfig(BaseModel):
    rules: list[Rule] = []


# --- Operation Classification ---

OperationType = Literal[
    "read_local",
    "write_local",
    "read_external",
    "write_external",
    "read_sensitive",
    "write_sensitive",
    "execute",
    "credential_access",
    "memory_read",
    "memory_write",
    "skill_modify",
]


class OperationClassification(BaseModel):
    operation_type: OperationType
    categories: list[str] = []
    description: str = ""
    confidence: float = 1.0


# --- Rule Engine Results ---


class RuleCheckResult(BaseModel):
    needs_approval: bool = False
    triggered_rules: list[str] = []
    newly_activated_rules: list[str] = []
    descriptions: list[str] = []


# --- Session State ---


class SessionState(BaseModel):
    session_id: str
    channel_type: str = "cli"
    channel_ref: str = ""
    activated_rules: list[str] = []
    disabled_rules: list[str] = []
    approved_credentials: list[str] = []
    approved_operations: list[str] = []
    created_at: datetime = datetime.now()
    last_active: datetime = datetime.now()


# --- Configuration ---


class MatrixChannelConfig(BaseModel):
    enabled: bool = False
    homeserver: str = ""
    user_id: str = ""
    device_name: str = "carapace"
    allowed_rooms: list[str] = []
    allowed_users: list[str] = []


class CronJobConfig(BaseModel):
    id: str
    schedule: str
    instructions: str
    approval_target: dict[str, str] = {}


class CronChannelConfig(BaseModel):
    enabled: bool = False
    jobs: list[CronJobConfig] = []


class ChannelsConfig(BaseModel):
    matrix: MatrixChannelConfig = MatrixChannelConfig()
    cron: CronChannelConfig = CronChannelConfig()


class AgentConfig(BaseModel):
    model: str = "openai:gpt-4o-mini"
    classifier_model: str = "openai:gpt-4o-mini"


class CredentialsConfig(BaseModel):
    backend: str = "mock"


class SandboxConfig(BaseModel):
    base_image: str = "alpine:3.19"
    idle_timeout_minutes: int = 15
    default_network: bool = False


class MemorySearchConfig(BaseModel):
    enabled: bool = False
    provider: str = "local"
    local_model: str = "all-MiniLM-L6-v2"


class MemoryConfig(BaseModel):
    search: MemorySearchConfig = MemorySearchConfig()


class SessionsConfig(BaseModel):
    history_retention_days: int = 90


class ServerConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8321


class CarapaceConfig(BaseModel):
    log_level: str = "info"
    logfire_token: str = ""


class Config(BaseModel):
    carapace: CarapaceConfig = CarapaceConfig()
    server: ServerConfig = ServerConfig()
    channels: ChannelsConfig = ChannelsConfig()
    agent: AgentConfig = AgentConfig()
    credentials: CredentialsConfig = CredentialsConfig()
    sandbox: SandboxConfig = SandboxConfig()
    memory: MemoryConfig = MemoryConfig()
    sessions: SessionsConfig = SessionsConfig()


# --- Skill Catalog Entry ---


class SkillInfo(BaseModel):
    name: str
    description: str = ""
    path: Path


# --- Token Usage Tracking ---


class ModelUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    input_audio_tokens: int = 0
    output_audio_tokens: int = 0
    cache_audio_read_tokens: int = 0
    requests: int = 0


class UsageTracker(BaseModel):
    models: dict[str, ModelUsage] = {}
    categories: dict[str, ModelUsage] = {}

    def record(self, model: str, category: str, usage: RunUsage) -> None:
        for bucket in (
            self.models.setdefault(model, ModelUsage()),
            self.categories.setdefault(category, ModelUsage()),
        ):
            bucket.input_tokens += usage.input_tokens or 0
            bucket.output_tokens += usage.output_tokens or 0
            bucket.cache_read_tokens += usage.cache_read_tokens or 0
            bucket.cache_write_tokens += usage.cache_write_tokens or 0
            bucket.input_audio_tokens += usage.input_audio_tokens or 0
            bucket.output_audio_tokens += usage.output_audio_tokens or 0
            bucket.cache_audio_read_tokens += usage.cache_audio_read_tokens or 0
            bucket.requests += usage.requests

    @property
    def total_input(self) -> int:
        return sum(m.input_tokens for m in self.models.values())

    @property
    def total_output(self) -> int:
        return sum(m.output_tokens for m in self.models.values())


# --- Deps for Pydantic AI RunContext ---


@dataclass
class Deps:
    config: Config
    data_dir: Path
    session_state: SessionState
    rules: list[Rule]
    skill_catalog: list[SkillInfo] = field(default_factory=list)
    activated_skills: list[str] = field(default_factory=list)
    classifier_model: str = "openai:gpt-4o-mini"
    agent_model: Any = None
    verbose: bool = True
    tool_call_callback: Callable[[str, dict[str, Any], str], None] | None = None
    usage_tracker: UsageTracker = field(default_factory=UsageTracker)
