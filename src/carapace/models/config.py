from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_serializer, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from ..notifications.models import NotificationsConfig
from .session import SessionBudget

OPENAI_COMPATIBLE_PROVIDERS = {"openai", "openai-chat", "openai-responses"}
PROVIDERS_WITH_MODEL_API_KEYS = OPENAI_COMPATIBLE_PROVIDERS | {"openrouter"}


class ConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Secret(ConfigModel):
    """Flexible secret source: raw value, environment variable, or file.

    Accepts a plain string as shorthand for ``Secret(raw="...")``.
    Resolution priority: raw > env > file.
    """

    raw: str | None = None
    env: str | None = None
    file: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _accept_plain_string(cls, data: Any) -> Any:
        if isinstance(data, str):
            return {"raw": data}
        return data

    def resolve(self) -> SecretStr:
        """Return the resolved secret value.

        Raises ``ValueError`` when no source is configured or the
        configured source (env var / file) does not exist.
        """
        if self.raw is not None:
            return SecretStr(self.raw)
        if self.env is not None:
            val = os.environ.get(self.env)
            if val is None:
                raise ValueError(f"Environment variable {self.env!r} is not set")
            return SecretStr(val)
        if self.file is not None:
            path = Path(self.file)
            if not path.exists():
                raise ValueError(f"Secret file {self.file!r} does not exist")
            return SecretStr(path.read_text().strip())
        raise ValueError("Secret has no source configured (set raw, env, or file)")


class JwtCookieConfig(ConfigModel):
    name: str = "carapace_session"
    issuer: str = "carapace"
    audience: str = "carapace-web"
    ttl_seconds: int = Field(default=60 * 60 * 24 * 14, ge=60)
    secure: bool = False
    same_site: Literal["lax", "strict", "none"] = "lax"


class AuthConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CARAPACE_AUTH_", env_nested_delimiter="__", extra="forbid")

    cookie: JwtCookieConfig = JwtCookieConfig()


class AvailableModelEntry(ConfigModel):
    """One row in ``agent.available_models``: shorthand ``provider:name`` string or a mapping."""

    provider: str = Field(
        description=(
            "API kind used to access the model, such as anthropic, openai, "
            "openai-chat, openai-responses, or openrouter."
        ),
    )
    name: str = Field(
        description="Provider-specific model name sent to that API.",
    )
    id: str | None = Field(
        default=None,
        description="Stable id for this row (slash commands, API). Defaults to provider:name.",
    )
    max_input_tokens: int | None = None
    thinking: bool | Literal["minimal", "low", "medium", "high", "xhigh"] | None = Field(
        default=None,
        description="Enable model thinking/reasoning. true/false to toggle, or an effort level.",
    )
    thinking_budget_tokens: int | None = Field(
        default=None,
        ge=0,
        description="Optional llama.cpp reasoning budget for OpenAI-compatible rows.",
    )
    base_url: str | None = Field(
        default=None,
        description="OpenAI-compatible API base URL (openai / openai-chat / openai-responses rows only).",
    )
    vision: bool = Field(
        default=False,
        description="Model accepts image input; enables raw-image read-tool results.",
    )
    enabled: bool = Field(
        default=True,
        description="Disabled models are hidden from pickers and rejected by the LLM call.",
    )
    api_key: Secret | None = Field(default=None, exclude=True)

    @model_validator(mode="before")
    @classmethod
    def _coerce_shorthand_string(cls, data: Any) -> Any:
        if isinstance(data, str):
            if ":" not in data:
                msg = f"model string must be 'provider:name', got {data!r}"
                raise ValueError(msg)
            provider, name = data.split(":", 1)
            return {"provider": provider, "name": name}
        return data

    @model_validator(mode="after")
    def _validate_openai_compatible_fields(self) -> AvailableModelEntry:
        if self.base_url is not None and self.provider not in OPENAI_COMPATIBLE_PROVIDERS:
            raise ValueError("base_url is only supported for provider 'openai', 'openai-chat', or 'openai-responses'")
        if self.thinking_budget_tokens is not None and self.provider not in OPENAI_COMPATIBLE_PROVIDERS:
            raise ValueError(
                "thinking_budget_tokens is only supported for provider 'openai', 'openai-chat', or 'openai-responses'"
            )
        if self.api_key is not None and self.provider not in PROVIDERS_WITH_MODEL_API_KEYS:
            raise ValueError(
                "api_key is only supported for provider 'openai', 'openai-chat', 'openai-responses', or 'openrouter'"
            )
        return self

    @property
    def model_id(self) -> str:
        return self.id if self.id is not None else f"{self.provider}:{self.name}"

    @model_serializer(mode="wrap")
    def _serialize(self, handler: Callable[..., Any]) -> dict[str, Any]:
        data = handler(self)
        data["id"] = self.model_id
        return data


def _default_agent_available_models() -> list[AvailableModelEntry]:
    return [
        AvailableModelEntry.model_validate("anthropic:claude-sonnet-4-6"),
        AvailableModelEntry.model_validate("anthropic:claude-haiku-4-5"),
    ]


class CompactionConfig(ConfigModel):
    """Session compaction tuning (manual `/compact` in v1)."""

    # Default number of recent completed turns kept verbatim when folding.
    keep_turns: int = Field(default=8, ge=1)
    # Number of most-recent completed turns whose tool outputs stay fully verbatim (never
    # summarized), so the agent keeps exact fidelity on its latest work. 0 disables the hot zone.
    verbatim_tool_turns: int = Field(default=4, ge=0)
    # Tool returns below this token count are left alone (marker overhead would exceed the saving).
    tool_output_floor_tokens: int = Field(default=500, ge=1)


class AgentConfig(ConfigModel):
    model: str = "anthropic:claude-sonnet-4-6"
    sentinel_model: str = "anthropic:claude-haiku-4-5"
    title_model: str = "anthropic:claude-haiku-4-5"
    # Model used for compaction summaries. None -> fall back to title_model.
    compaction_model: str | None = None
    compaction: CompactionConfig = Field(default_factory=CompactionConfig)
    default_session_budget: SessionBudget = Field(default_factory=SessionBudget)

    available_models: list[AvailableModelEntry] = Field(default_factory=_default_agent_available_models)

    max_parallel_llm: int = 2

    # Maximum number of sentinel-backed proxy domain review batches one tool call can trigger.
    # 0 disables the cap.
    max_sentinel_calls_per_tool_call: int = 10

    # Debounce window for coalescing proxy domain requests within a tool call.
    sentinel_domain_batch_window_ms: int = 100

    # Max wall-clock time for one sentinel LLM review.
    sentinel_timeout_seconds: int = Field(default=600, ge=1)

    # Cap string length returned to the model (and mirrored to tool_result_callback). 0 = no limit.
    tool_output_max_chars: int = 16_000

    @model_validator(mode="after")
    def _defaults_listed_in_available_models(self) -> AgentConfig:
        if self.max_sentinel_calls_per_tool_call < 0:
            raise ValueError("agent.max_sentinel_calls_per_tool_call must be >= 0")
        if self.sentinel_domain_batch_window_ms < 0:
            raise ValueError("agent.sentinel_domain_batch_window_ms must be >= 0")
        catalog = {e.model_id: e for e in self.available_models}
        for field_name in ("model", "sentinel_model", "title_model", "compaction_model"):
            mid = getattr(self, field_name)
            if mid is None:
                continue
            entry = catalog.get(mid)
            if entry is None:
                raise ValueError(
                    f"agent.{field_name}={mid!r} must match an entry in agent.available_models (as id or provider:name)"
                )
            if not entry.enabled:
                raise ValueError(f"agent.{field_name}={mid!r} refers to a disabled model")
        return self


def agent_available_model_entries(agent: AgentConfig) -> list[AvailableModelEntry]:
    """Catalog for API and model factory: YAML order, duplicate ``model_id`` keeps last row; sorted ids."""
    by_id: dict[str, AvailableModelEntry] = {}
    for e in agent.available_models:
        by_id[e.model_id] = e
    return sorted(by_id.values(), key=lambda e: e.model_id)


def secret_to_dict(secret: Secret | None) -> dict[str, str] | None:
    """Serialize a Secret to its single-source mapping (raw/env/file).

    ``AvailableModelEntry.api_key`` is ``Field(exclude=True)``, so ``model_dump`` drops
    it; persistence and the admin handler use this to round-trip the key explicitly.
    """
    if secret is None:
        return None
    if secret.raw is not None:
        return {"raw": secret.raw}
    if secret.env is not None:
        return {"env": secret.env}
    if secret.file is not None:
        return {"file": secret.file}
    return None


def model_entry_to_dict(entry: AvailableModelEntry) -> dict[str, Any]:
    """Serialize an AvailableModelEntry to a plain dict, including the api_key source."""
    data: dict[str, Any] = {
        "provider": entry.provider,
        "name": entry.name,
    }
    if entry.id is not None:
        data["id"] = entry.id
    if entry.max_input_tokens is not None:
        data["max_input_tokens"] = entry.max_input_tokens
    if entry.thinking is not None:
        data["thinking"] = entry.thinking
    if entry.thinking_budget_tokens is not None:
        data["thinking_budget_tokens"] = entry.thinking_budget_tokens
    if entry.base_url is not None:
        data["base_url"] = entry.base_url
    if entry.vision:
        data["vision"] = entry.vision
    if not entry.enabled:
        data["enabled"] = False
    secret = secret_to_dict(entry.api_key)
    if secret is not None:
        data["api_key"] = secret
    return data


class SandboxConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CARAPACE_SANDBOX_", extra="forbid")

    # Container backend: "docker" for local development, "kubernetes" for cluster deployments.
    runtime: Literal["docker", "kubernetes"] = "docker"
    # Container image used for sandbox pods/containers.
    base_image: str = "carapace-sandbox:latest"
    # Absolute path to the optional skill activator inside the sandbox image.
    skill_activator: str | None = None
    # Maximum duration of one whole-skill activator invocation.
    skill_activator_timeout_seconds: int = Field(default=600, ge=1)
    # Minutes of inactivity before a sandbox is automatically cleaned up.
    idle_timeout_minutes: int = 60
    # Docker network to attach sandbox containers to (docker runtime only).
    network_name: str = "carapace-sandbox"
    # Port of the HTTP proxy sidecar that sandbox traffic is routed through.
    proxy_port: int = 3128
    # Number of generic warm sandboxes to keep ready ahead of assignment (Kubernetes runtime only).
    warm_pool_size: int = Field(default=0, ge=0)
    # Kubernetes namespace where sandbox pods are created.
    k8s_namespace: str = "carapace"
    # PVC claim name for the shared data volume mounted into sandbox pods.
    k8s_pvc_claim: str = "carapace-data"
    # ServiceAccount assigned to sandbox pods (None = namespace default).
    k8s_service_account: str | None = None
    # PriorityClass for sandbox pods (None = cluster default).
    k8s_priority_class: str | None = None
    # Attach ownerReferences on sandbox StatefulSets (and legacy pod sandboxes).
    # When False, resources rely on labels + argocd.argoproj.io/tracking-id only.
    k8s_owner_ref: bool = True
    # Server Deployment name for ownerReference fallback (Helm: release name).
    k8s_server_deployment_name: str = "carapace"
    # Preferred owner for sandbox resources (namespaced Sandboxes CRD singleton).
    # Set to null or an empty string to use k8s_server_deployment_name instead.
    # When set, the named Sandboxes object must exist.
    k8s_sandboxes_name: str | None = "carapace-sandboxes"
    # ArgoCD application / Helm release name. Used for the app.kubernetes.io/instance
    # label and the argocd.argoproj.io/tracking-id annotation so that sandbox pods
    # appear in the ArgoCD resource tree even without an ownerReference.
    k8s_app_instance: str = "carapace"
    # Size of per-session PVCs created via StatefulSet volumeClaimTemplates.
    k8s_session_pvc_size: str = "1Gi"
    # StorageClass for per-session PVCs (empty = cluster default).
    k8s_session_pvc_storage_class: str = ""
    # Resource requests/limits for sandbox containers (empty = no constraint).
    k8s_resource_requests_cpu: str = ""
    k8s_resource_requests_memory: str = ""
    k8s_resource_limits_cpu: str = ""
    k8s_resource_limits_memory: str = ""
    # Remove sandbox resources for sessions that no longer exist on disk at startup.
    cleanup_orphans_on_startup: bool = True

    @field_validator("skill_activator", mode="before")
    @classmethod
    def _validate_skill_activator(cls, value: object) -> object:
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        value = value.strip()
        if not value:
            return None

        path = PurePosixPath(value)
        if not path.is_absolute() or ".." in path.parts:
            raise ValueError("sandbox skill activator must be an absolute normalized path")
        writable_roots = (
            PurePosixPath("/workspace"),
            PurePosixPath("/tmp"),
            PurePosixPath("/var/tmp"),
            PurePosixPath("/dev/shm"),
        )
        if any(path == root or root in path.parents for root in writable_roots):
            raise ValueError("sandbox skill activator must be outside writable workspace and temporary directories")
        return str(path)


class SessionCommitConfig(ConfigModel):
    enabled: bool = True
    path_prefix: str = "sessions"
    autosave_enabled: bool = True
    autosave_inactivity_hours: int = 4
    delete_from_knowledge_on_session_delete: bool = True

    @model_validator(mode="after")
    def _validate_commit_settings(self) -> SessionCommitConfig:
        if self.autosave_inactivity_hours <= 0:
            raise ValueError("sessions.commit.autosave_inactivity_hours must be > 0")
        prefix = Path(self.path_prefix)
        if prefix.is_absolute() or ".." in prefix.parts:
            raise ValueError("sessions.commit.path_prefix must stay inside the knowledge directory")
        normalized = str(prefix).strip("/")
        self.path_prefix = normalized or "sessions"
        return self


class SessionsConfig(ConfigModel):
    commit: SessionCommitConfig = SessionCommitConfig()


class CacheConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CARAPACE_CACHE_", extra="forbid")

    ttl_seconds: int = 1800
    redis_url: str = "redis://localhost:6379/0"

    @model_validator(mode="after")
    def _validate(self) -> CacheConfig:
        if self.ttl_seconds <= 0:
            raise ValueError("cache.ttl_seconds must be > 0")
        if not self.redis_url.strip():
            raise ValueError("cache.redis_url must not be empty")
        return self


class DatabaseConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CARAPACE_DATABASE_", extra="forbid")

    # SQLAlchemy URL. The default SQLite file is resolved under the data dir (see
    # carapace.database.engine.resolve_database_url), so it lands beside the data tree.
    # For Postgres use e.g. "postgresql+psycopg://carapace:carapace@postgres:5432/carapace".
    url: str = "sqlite+pysqlite:///carapace.db"
    # Connection pool sizing (ignored for SQLite).
    pool_size: int = 5
    max_overflow: int = 10
    # Echo SQL statements to the logger.
    echo: bool = False

    @model_validator(mode="after")
    def _validate(self) -> DatabaseConfig:
        if not self.url.strip():
            raise ValueError("database.url must not be empty")
        return self


class ServerConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CARAPACE_SERVER_", extra="forbid")

    host: str = "0.0.0.0"
    port: int = 8321
    sandbox_port: int = 8322
    internal_port: int = 8320
    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://localhost:3001",
        "http://localhost:3002",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3001",
        "http://127.0.0.1:3002",
    ]


class CarapaceConfig(BaseSettings):
    # Operator/bootstrap config: read from CARAPACE_LOG_LEVEL / CARAPACE_LOGFIRE_TOKEN env vars.
    model_config = SettingsConfigDict(env_prefix="CARAPACE_", extra="forbid")

    log_level: str = "info"
    logfire_token: str = ""


class Config(ConfigModel):
    # default_factory (not a shared instance) so the BaseSettings sections re-read their
    # CARAPACE_* env vars every time a Config is built — i.e. at build_config() call time,
    # after load_dotenv() — rather than once at import.
    carapace: CarapaceConfig = Field(default_factory=CarapaceConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    notifications: NotificationsConfig = Field(default_factory=NotificationsConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    sessions: SessionsConfig = Field(default_factory=SessionsConfig)
    sandbox: SandboxConfig = Field(default_factory=SandboxConfig)
    # Absolute data root (sessions, auth secrets, sqlite, vapid keys, knowledges/). Sourced
    # from CARAPACE_DATA_DIR via config.build_config; default "./data".
    data_dir: str = "./data"
