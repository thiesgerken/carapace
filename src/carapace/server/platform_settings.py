from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from pydantic_ai.exceptions import UserError

from ..api_keys import Access, Scope
from ..auth import UserIdentity
from ..llm import ModelFactory, make_model_factory
from ..models.config import (
    OPENAI_COMPATIBLE_PROVIDERS,
    PROVIDERS_WITH_MODEL_API_KEYS,
    AgentConfig,
    AvailableModelEntry,
    CompactionConfig,
    Config,
    Secret,
    agent_available_model_entries,
)
from ..models.session import SessionBudget
from .auth import require
from .state import server_module

server = server_module()
router = APIRouter()


class PlatformSettingsModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PlatformDefaultModels(PlatformSettingsModel):
    agent: str
    sentinel: str
    title: str
    compaction: str | None = None  # None -> fall back to the title model

    @field_validator("compaction", mode="before")
    @classmethod
    def _normalize_compaction(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class PublicModelSecret(PlatformSettingsModel):
    source: Literal["raw", "env", "file"] | None = None
    value: str | None = None
    configured: bool = False


class PublicPlatformModelEntry(PlatformSettingsModel):
    id: str
    provider: str
    name: str
    max_input_tokens: int | None = None
    thinking: bool | Literal["minimal", "low", "medium", "high", "xhigh"] | None = None
    thinking_budget_tokens: int | None = None
    base_url: str | None = None
    vision: bool = False
    enabled: bool = True
    api_key: PublicModelSecret = PublicModelSecret()


class PlatformCompaction(PlatformSettingsModel):
    """Compaction tuning exposed in the admin UI (mirrors ``agent.compaction``)."""

    keep_turns: int = Field(default=8, ge=1)
    verbatim_tool_turns: int = Field(default=4, ge=0)
    tool_output_floor_tokens: int = Field(default=500, ge=1)


class PlatformSettingsPayload(PlatformSettingsModel):
    default_models: PlatformDefaultModels
    default_budget: SessionBudget
    compaction: PlatformCompaction
    available_models: list[PublicPlatformModelEntry]


class PlatformSettingsResponse(PlatformSettingsModel):
    config_path: str
    config_writable: bool
    settings: PlatformSettingsPayload


class PlatformSecretPatch(PlatformSettingsModel):
    source: Literal["raw", "env", "file"] | None = None
    value: str | None = None

    @field_validator("value", mode="before")
    @classmethod
    def _normalize_value(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class PlatformModelEntryPatch(PlatformSettingsModel):
    provider: str
    name: str
    id: str | None = None
    max_input_tokens: int | None = Field(default=None, ge=1)
    thinking: bool | Literal["minimal", "low", "medium", "high", "xhigh"] | None = None
    thinking_budget_tokens: int | None = Field(default=None, ge=0)
    base_url: str | None = None
    vision: bool = False
    enabled: bool = True
    api_key: PlatformSecretPatch | None = None

    @field_validator("provider", "name", "id", "base_url", mode="before")
    @classmethod
    def _normalize_string(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def _validate_required_strings(self) -> PlatformModelEntryPatch:
        if not self.provider:
            raise ValueError("model provider is required")
        if not self.name:
            raise ValueError("model name is required")
        return self

    @property
    def model_id(self) -> str:
        return self.id if self.id is not None else f"{self.provider}:{self.name}"


class PlatformSettingsPatch(PlatformSettingsModel):
    default_models: PlatformDefaultModels
    default_budget: SessionBudget = SessionBudget()
    compaction: PlatformCompaction = PlatformCompaction()
    available_models: list[PlatformModelEntryPatch]

    @model_validator(mode="after")
    def _validate_available_models_nonempty(self) -> PlatformSettingsPatch:
        if not self.available_models:
            raise ValueError("at least one model must be configured")
        return self


def _config_path() -> Path:
    # No config file anymore; report the data dir (informational only — the catalog is DB-backed).
    data_dir = getattr(server, "_data_dir", None)
    return data_dir if isinstance(data_dir, Path) else Path(".")


def _public_secret(secret: Secret | None) -> PublicModelSecret:
    if secret is None:
        return PublicModelSecret()
    if secret.raw is not None:
        return PublicModelSecret(source="raw", configured=True)
    if secret.env is not None:
        return PublicModelSecret(source="env", value=secret.env, configured=True)
    if secret.file is not None:
        return PublicModelSecret(source="file", value=secret.file, configured=True)
    return PublicModelSecret()


def _public_model_entry(entry: AvailableModelEntry) -> PublicPlatformModelEntry:
    return PublicPlatformModelEntry(
        id=entry.model_id,
        provider=entry.provider,
        name=entry.name,
        max_input_tokens=entry.max_input_tokens,
        thinking=entry.thinking,
        thinking_budget_tokens=entry.thinking_budget_tokens,
        base_url=entry.base_url,
        vision=entry.vision,
        enabled=entry.enabled,
        api_key=_public_secret(entry.api_key),
    )


def _response() -> PlatformSettingsResponse:
    # Platform settings are DB-backed; config_path reports the data dir (informational only) and
    # the catalog is always editable.
    return PlatformSettingsResponse(
        config_path=str(_config_path()),
        config_writable=True,
        settings=PlatformSettingsPayload(
            default_models=PlatformDefaultModels(
                agent=server._config.agent.model,
                sentinel=server._config.agent.sentinel_model,
                title=server._config.agent.title_model,
                compaction=server._config.agent.compaction_model,
            ),
            default_budget=server._config.agent.default_session_budget,
            compaction=PlatformCompaction.model_validate(server._config.agent.compaction.model_dump(mode="json")),
            available_models=[
                _public_model_entry(entry) for entry in agent_available_model_entries(server._config.agent)
            ],
        ),
    )


def _secret_from_patch(patch: PlatformSecretPatch | None, existing: Secret | None) -> Secret | None:
    if patch is None:
        return existing.model_copy(deep=True) if existing is not None else None
    if patch.source is None:
        return None
    if patch.source == "raw":
        if patch.value is not None:
            return Secret(raw=patch.value)
        if existing is not None and existing.raw is not None:
            return existing.model_copy(deep=True)
        raise HTTPException(status_code=400, detail="Raw API key value is required for new raw secrets")
    if patch.value is None:
        raise HTTPException(status_code=400, detail=f"{patch.source} API key value is required")
    if patch.source == "env":
        return Secret(env=patch.value)
    return Secret(file=patch.value)


def _openai_compatible_provider(provider: str) -> bool:
    return provider in OPENAI_COMPATIBLE_PROVIDERS


def _provider_supports_api_key(provider: str) -> bool:
    return provider in PROVIDERS_WITH_MODEL_API_KEYS


def _agent_config_from_patch(body: PlatformSettingsPatch, existing_agent: AgentConfig) -> AgentConfig:
    existing_by_id = {entry.model_id: entry for entry in agent_available_model_entries(existing_agent)}
    entries = []
    for patch in body.available_models:
        existing = existing_by_id.get(patch.model_id)
        openai_compatible = _openai_compatible_provider(patch.provider)
        supports_api_key = _provider_supports_api_key(patch.provider)
        entries.append(
            AvailableModelEntry(
                provider=patch.provider,
                name=patch.name,
                id=patch.id,
                max_input_tokens=patch.max_input_tokens,
                thinking=patch.thinking,
                thinking_budget_tokens=patch.thinking_budget_tokens if openai_compatible else None,
                base_url=patch.base_url if openai_compatible else None,
                vision=patch.vision,
                enabled=patch.enabled,
                api_key=(
                    _secret_from_patch(patch.api_key, existing.api_key if existing is not None else None)
                    if supports_api_key
                    else None
                ),
            )
        )
    return AgentConfig(
        model=body.default_models.agent,
        sentinel_model=body.default_models.sentinel,
        title_model=body.default_models.title,
        compaction_model=body.default_models.compaction,
        compaction=CompactionConfig(
            keep_turns=body.compaction.keep_turns,
            verbatim_tool_turns=body.compaction.verbatim_tool_turns,
            tool_output_floor_tokens=body.compaction.tool_output_floor_tokens,
        ),
        default_session_budget=body.default_budget,
        available_models=entries,
        max_parallel_llm=existing_agent.max_parallel_llm,
        max_sentinel_calls_per_tool_call=existing_agent.max_sentinel_calls_per_tool_call,
        sentinel_domain_batch_window_ms=existing_agent.sentinel_domain_batch_window_ms,
        sentinel_timeout_seconds=existing_agent.sentinel_timeout_seconds,
        tool_output_max_chars=existing_agent.tool_output_max_chars,
    )


def _runtime_model_factory(config: Config, *, user: str) -> ModelFactory:
    """Build the factory for *config* and check its default models construct.

    Built for the requesting admin because models are per user; construction does no credential
    I/O, so a ChatGPT subscription default validates even if that admin never connected one.
    """
    model_factory = make_model_factory(config, server._codex_accounts.provider_for)
    model_factory(config.agent.model, user=user)
    model_factory(config.agent.sentinel_model, user=user)
    model_factory(config.agent.title_model, user=user)
    return model_factory


def _apply_runtime_config(config: Config, *, model_factory: ModelFactory) -> None:
    server.__dict__["_config"] = config
    server._engine.apply_platform_model_config(config, model_factory=model_factory)


@router.get("/admin/platform/settings", response_model=PlatformSettingsResponse)
async def get_platform_settings(
    _admin: Annotated[object, Depends(require(Scope.admin, Access.read))],
) -> PlatformSettingsResponse:
    return _response()


@router.patch("/admin/platform/settings", response_model=PlatformSettingsResponse)
async def update_platform_settings(
    body: PlatformSettingsPatch,
    admin: Annotated[UserIdentity, Depends(require(Scope.admin, Access.write))],
) -> PlatformSettingsResponse:
    # Build + validate the new agent config (AgentConfig() re-runs the defaults∈catalog check),
    # then a candidate Config so the runtime model factory can be built before we persist anything.
    try:
        agent = _agent_config_from_patch(body, server._config.agent)
        config = server._config.model_copy(update={"agent": agent})
        model_factory = _runtime_model_factory(config, user=admin.username)
    except (ValueError, ValidationError, UserError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    # Persist to the DB (model catalog + scalar agent row) in one transaction, then swap runtime.
    server._platform_store.save_agent_config(agent)
    _apply_runtime_config(config, model_factory=model_factory)
    return _response()
