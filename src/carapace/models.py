from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from genai_prices import Usage as PriceUsage
from genai_prices import calc_price
from loguru import logger
from pydantic import BaseModel, ConfigDict
from pydantic_ai.usage import RunUsage

from carapace.sandbox.manager import SandboxManager
from carapace.security.context import SessionSecurity

# --- Session State ---


class SessionState(BaseModel):
    session_id: str
    channel_type: str = "cli"
    channel_ref: str | None = None
    title: str | None = None
    approved_credentials: list[str] = []
    approved_operations: list[str] = []
    activated_skills: list[str] = []
    created_at: datetime
    last_active: datetime

    @classmethod
    def now(
        cls,
        *,
        session_id: str,
        channel_type: str = "cli",
        channel_ref: str | None = None,
        title: str | None = None,
        approved_credentials: list[str] | None = None,
        approved_operations: list[str] | None = None,
    ) -> SessionState:
        ts = datetime.now(tz=UTC)
        return cls(
            session_id=session_id,
            channel_type=channel_type,
            channel_ref=channel_ref,
            title=title,
            approved_credentials=approved_credentials or [],
            approved_operations=approved_operations or [],
            created_at=ts,
            last_active=ts,
        )


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
    model: str = "anthropic:claude-sonnet-4-6"
    sentinel_model: str = "anthropic:claude-haiku-4-5"
    title_model: str = "anthropic:claude-haiku-4-5"
    max_parallel_llm: int = 2


class CredentialsConfig(BaseModel):
    backend: str = "mock"


_SANDBOX_IMAGE_VERSION = "0.25.0"


class SandboxConfig(BaseModel):
    runtime: Literal["docker", "kubernetes"] = "docker"
    base_image: str = f"carapace-sandbox:{_SANDBOX_IMAGE_VERSION}"
    idle_timeout_minutes: int = 15
    network_name: str = "carapace-sandbox"
    proxy_port: int = 3128
    k8s_namespace: str = "carapace"
    k8s_pvc_claim: str = "carapace-data"
    k8s_service_account: str | None = None


class MemorySearchConfig(BaseModel):
    enabled: bool = False
    provider: str = "local"
    local_model: str = "all-MiniLM-L6-v2"


class MemoryConfig(BaseModel):
    search: MemorySearchConfig = MemorySearchConfig()


class SessionsConfig(BaseModel):
    history_retention_days: int = 90


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8321
    cors_origins: list[str] = ["http://localhost:3000"]


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


class SkillNetworkConfig(BaseModel):
    domains: list[str] = []


class SkillCarapaceConfig(BaseModel):
    """Parsed contents of a skill's ``carapace.yaml``."""

    network: SkillNetworkConfig = SkillNetworkConfig()
    credentials: list[dict[str, str]] = []
    hints: dict[str, str] = {}


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

    def estimated_cost(self) -> dict[str, Decimal]:
        """Return estimated USD cost per model and total. Keys: model names + 'total'."""
        costs: dict[str, Decimal] = {}
        total = Decimal(0)
        for model_key, u in self.models.items():
            provider_id, _, model_ref = model_key.partition(":")
            if not model_ref:
                model_ref, provider_id = provider_id, None
            try:
                price = calc_price(
                    PriceUsage(
                        input_tokens=u.input_tokens,
                        output_tokens=u.output_tokens,
                        cache_read_tokens=u.cache_read_tokens,
                        cache_write_tokens=u.cache_write_tokens,
                        input_audio_tokens=u.input_audio_tokens,
                        output_audio_tokens=u.output_audio_tokens,
                        cache_audio_read_tokens=u.cache_audio_read_tokens,
                    ),
                    model_ref=model_ref,
                    provider_id=provider_id,
                )
                costs[model_key] = price.total_price
                total += price.total_price
            except LookupError:
                logger.debug(f"No pricing data for model {model_key}")
        costs["total"] = total
        return costs


# --- Deps for Pydantic AI RunContext ---


class Deps(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    config: Config
    data_dir: Path
    session_state: SessionState
    sandbox: SandboxManager
    security: SessionSecurity
    sentinel: Any  # Sentinel (can't import here — circular dep via UsageTracker)
    skill_catalog: list[SkillInfo] = []
    activated_skills: list[str] = []
    agent_model: Any = None
    verbose: bool = True
    tool_call_callback: Callable[[str, dict[str, Any], str], None] | None = None
    tool_result_callback: Callable[[str, str], None] | None = None
    usage_tracker: UsageTracker
