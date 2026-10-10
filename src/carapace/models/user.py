from __future__ import annotations

from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .credentials import CredentialsConfig
from .matrix import MatrixChannelConfig
from .session import SessionBudget

DEFAULT_GIT_BRANCH = "main"
DEFAULT_GIT_AUTHOR = "carapace <carapace@%h>"
DEFAULT_TIMEZONE = "Europe/Berlin"


def validate_timezone(value: str) -> str:
    timezone = value.strip()
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"timezone must be an IANA time zone name such as 'Europe/Berlin', got {value!r}") from exc
    return timezone


class UserConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UserChannelsConfig(UserConfigModel):
    matrix: MatrixChannelConfig = MatrixChannelConfig()


class UserGitConfig(UserConfigModel):
    remote: str = ""
    branch: str = DEFAULT_GIT_BRANCH
    author: str = DEFAULT_GIT_AUTHOR
    token: str | None = None

    @model_validator(mode="after")
    def _normalize(self) -> UserGitConfig:
        self.remote = self.remote.strip()
        self.branch = self.branch.strip() or DEFAULT_GIT_BRANCH
        self.author = self.author.strip() or DEFAULT_GIT_AUTHOR
        if self.token is not None:
            self.token = self.token.strip() or None
        return self


class UserDefaultModelsConfig(UserConfigModel):
    agent: str | None = None
    sentinel: str | None = None
    title: str | None = None
    compaction: str | None = None
    memory_low: str | None = None
    memory_high: str | None = None

    @field_validator("agent", "sentinel", "title", "compaction", "memory_low", "memory_high", mode="before")
    @classmethod
    def _normalize_model_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class MemoryBudget(UserConfigModel):
    """Spend limits for memory LLM tasks. ``None`` disables that limit.

    Token limits exist for local models without pricing, where cost limits cannot apply.
    """

    cost_usd_per_day: Decimal | None = Field(default=Decimal("1.00"), ge=Decimal(0))
    cost_usd_per_month: Decimal | None = Field(default=Decimal("10.00"), ge=Decimal(0))
    input_tokens_per_day: int | None = Field(default=None, ge=0)
    input_tokens_per_month: int | None = Field(default=None, ge=0)


class UserMemoryConfig(UserConfigModel):
    auto_mode: bool = False
    budget: MemoryBudget = MemoryBudget()


class UserConfig(UserConfigModel):
    agent_name: str = ""
    agent_icon: str = ""
    credentials: CredentialsConfig = CredentialsConfig()
    channels: UserChannelsConfig = UserChannelsConfig()
    git: UserGitConfig = UserGitConfig()
    default_models: UserDefaultModelsConfig = UserDefaultModelsConfig()
    budgets: SessionBudget = SessionBudget()
    # IANA zone; defines memory week/month boundaries and memory budget windows.
    timezone: str = DEFAULT_TIMEZONE
    memory: UserMemoryConfig = UserMemoryConfig()

    @field_validator("agent_name", "agent_icon", mode="before")
    @classmethod
    def _normalize_agent_name(cls, value: str | None) -> str:
        return (value or "").strip()

    @field_validator("timezone", mode="after")
    @classmethod
    def _validate_timezone(cls, value: str) -> str:
        return validate_timezone(value)
