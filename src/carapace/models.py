from __future__ import annotations

import os
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_serializer, model_validator
from pydantic_ai.models import Model
from pydantic_ai.usage import UsageLimits
from pydantic_settings import BaseSettings, SettingsConfigDict

from carapace.git.store import GitStore
from carapace.sandbox.manager import SandboxManager
from carapace.sandbox.runtime import NetworkTunnel
from carapace.security.context import ApprovalSource, ApprovalVerdict, SessionSecurity
from carapace.security.sentinel import Sentinel
from carapace.usage import UsageTracker

# --- Credentials ---


class CredentialMetadata(BaseModel):
    """Vault credential metadata returned by backends and stored in session state."""

    vault_path: str
    name: str
    description: str = ""


@runtime_checkable
class CredentialRegistryProtocol(Protocol):
    """Structural type for credential registries — avoids importing the concrete class."""

    async def fetch(self, vault_path: str) -> str: ...
    async def fetch_metadata(self, vault_path: str) -> CredentialMetadata: ...
    async def list(self, query: str = "") -> list[CredentialMetadata]: ...


# --- Session State ---


class SessionBudget(BaseModel):
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: Decimal | None = None

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
            if self.cost_usd == 0:
                self.cost_usd = None
        return self

    @property
    def has_any_limit(self) -> bool:
        return any(limit is not None for limit in (self.input_tokens, self.output_tokens, self.cost_usd))


class SessionState(BaseModel):
    session_id: str
    channel_type: str = "cli"
    channel_ref: str | None = None
    title: str | None = None
    private: bool = False
    approved_operations: list[str] = []
    activated_skills: list[str] = []
    context_grants: dict[str, ContextGrant] = {}
    budget: SessionBudget = Field(default_factory=SessionBudget)
    created_at: datetime
    last_active: datetime
    knowledge_last_committed_at: datetime | None = None
    knowledge_last_archive_path: str | None = None
    knowledge_last_export_hash: str | None = None
    knowledge_last_commit_trigger: str | None = None

    @classmethod
    def now(
        cls,
        *,
        session_id: str,
        channel_type: str = "cli",
        channel_ref: str | None = None,
        title: str | None = None,
        private: bool = False,
        approved_operations: list[str] | None = None,
    ) -> SessionState:
        ts = datetime.now(tz=UTC)
        return cls(
            session_id=session_id,
            channel_type=channel_type,
            channel_ref=channel_ref,
            title=title,
            private=private,
            approved_operations=approved_operations or [],
            created_at=ts,
            last_active=ts,
        )


# --- Secrets ---


class Secret(BaseModel):
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


# --- Configuration ---


class MatrixTokenFile(BaseModel):
    """Schema for the persisted ``matrix_token.json`` file."""

    access_token: str
    device_id: str | None = None
    user_id: str | None = None


class MatrixChannelConfig(BaseModel):
    enabled: bool = False
    homeserver: str = ""
    user_id: str = ""
    device_name: str = "carapace"
    password: Secret | None = None
    token: Secret | None = None
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


class AvailableModelEntry(BaseModel):
    """One row in ``agent.available_models``: shorthand ``provider:name`` string or a mapping."""

    model_config = ConfigDict(extra="allow")

    provider: str
    name: str
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
        description="OpenAI-compatible API base URL (openai / openai-chat rows only).",
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
        if self.base_url is None and self.api_key is None and self.thinking_budget_tokens is None:
            return self
        if self.provider not in ("openai", "openai-chat"):
            raise ValueError(
                "base_url/api_key/thinking_budget_tokens are only supported for provider 'openai' or 'openai-chat'"
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


class AgentConfig(BaseModel):
    model: str = "anthropic:claude-sonnet-4-6"
    sentinel_model: str = "anthropic:claude-haiku-4-5"
    title_model: str = "anthropic:claude-haiku-4-5"
    default_session_budget: SessionBudget = Field(default_factory=SessionBudget)

    available_models: list[AvailableModelEntry] = Field(default_factory=_default_agent_available_models)

    max_parallel_llm: int = 2

    # Cap string length returned to the model (and mirrored to tool_result_callback). 0 = no limit.
    tool_output_max_chars: int = 16_000

    @model_validator(mode="after")
    def _defaults_listed_in_available_models(self) -> AgentConfig:
        catalog_ids = {e.model_id for e in self.available_models}
        for field_name in ("model", "sentinel_model", "title_model"):
            mid = getattr(self, field_name)
            if mid not in catalog_ids:
                raise ValueError(
                    f"agent.{field_name}={mid!r} must match an entry in agent.available_models (as id or provider:name)"
                )
        return self


def agent_available_model_entries(agent: AgentConfig) -> list[AvailableModelEntry]:
    """Catalog for API and model factory: YAML order, duplicate ``model_id`` keeps last row; sorted ids."""
    by_id: dict[str, AvailableModelEntry] = {}
    for e in agent.available_models:
        by_id[e.model_id] = e
    return sorted(by_id.values(), key=lambda e: e.model_id)


class SandboxConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CARAPACE_SANDBOX_")

    # Container backend: "docker" for local development, "kubernetes" for cluster deployments.
    runtime: Literal["docker", "kubernetes"] = "docker"
    # Container image used for sandbox pods/containers.
    base_image: str = "carapace-sandbox:latest"
    # Minutes of inactivity before a sandbox is automatically cleaned up.
    idle_timeout_minutes: int = 60
    # Docker network to attach sandbox containers to (docker runtime only).
    network_name: str = "carapace-sandbox"
    # Port of the HTTP proxy sidecar that sandbox traffic is routed through.
    proxy_port: int = 3128
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


class GitConfig(BaseModel):
    """Git-backed knowledge store configuration."""

    remote: str = ""  # optional external remote URL
    branch: str = "main"  # remote branch to fetch/push (local is always "main")
    author: str = "Carapace <carapace@%h>"  # %s → session ID, %h → hostname
    token: Secret | None = None


class SessionCommitConfig(BaseModel):
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


class SessionsConfig(BaseModel):
    default_private: bool = False
    commit: SessionCommitConfig = SessionCommitConfig()


class ServerConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CARAPACE_SERVER_")

    host: str = "0.0.0.0"
    port: int = 8321
    sandbox_port: int = 8322
    internal_port: int = 8320
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:3001", "http://localhost:3002"]


class CarapaceConfig(BaseModel):
    log_level: str = "info"
    logfire_token: str = ""


class FileCredentialBackendConfig(BaseModel):
    """Configuration for the file-based credential backend."""

    type: Literal["file"] = "file"
    path: str = ""
    expose: list[str] = []
    hide: list[str] = []


class BitwardenCredentialBackendConfig(BaseModel):
    """Configuration for a Bitwarden/Vaultwarden credential backend."""

    type: Literal["bitwarden"] = "bitwarden"
    url: str = "http://127.0.0.1:8087"
    expose: list[str] = []
    hide: list[str] = []


CredentialBackendConfig = Annotated[
    FileCredentialBackendConfig | BitwardenCredentialBackendConfig,
    Field(discriminator="type"),
]


class CredentialsConfig(BaseModel):
    """Top-level credential configuration with named backends."""

    backends: dict[str, CredentialBackendConfig] = {}

    @model_validator(mode="after")
    def _validate_backend_names(self) -> CredentialsConfig:
        for name in self.backends:
            if "/" in name:
                raise ValueError(f"Backend name {name!r} must not contain '/' (used as vault_path separator)")
        return self


class Config(BaseModel):
    carapace: CarapaceConfig = CarapaceConfig()
    server: ServerConfig = ServerConfig()
    channels: ChannelsConfig = ChannelsConfig()
    agent: AgentConfig = AgentConfig()
    sessions: SessionsConfig = SessionsConfig()
    sandbox: SandboxConfig = SandboxConfig()
    git: GitConfig = GitConfig()
    credentials: CredentialsConfig = CredentialsConfig()
    data_dir: str = "."  # resolved relative to config file location
    knowledge_dir: str = "./knowledge"  # resolved relative to config file location


# --- Skill Catalog Entry ---


@dataclass(frozen=True, slots=True)
class ToolResult:
    """Structured result passed through ``tool_result_callback``."""

    tool: str
    output: str
    exit_code: int = 0
    tool_id: str | None = None


class SkillCredentialDecl(BaseModel):
    """A credential requirement declared in a skill's Carapace metadata."""

    vault_path: str
    description: str = ""
    env_var: str | None = None
    file: str | None = None
    base64: Annotated[
        bool, Field(description="If true, the stored value is base64-encoded and will be decoded before injection.")
    ] = False


class SkillNetworkConfig(BaseModel):
    domains: list[str] = []
    tunnels: list[NetworkTunnel] = []

    @model_validator(mode="after")
    def _validate_tunnels(self) -> SkillNetworkConfig:
        seen_local_ports: set[int] = set()
        seen_endpoints: set[tuple[str, int]] = set()
        for tunnel in self.tunnels:
            if tunnel.local_port in seen_local_ports:
                raise ValueError(f"network.tunnels local_port {tunnel.local_port} must be unique within a skill")
            endpoint = (tunnel.host, tunnel.remote_port)
            if endpoint in seen_endpoints:
                raise ValueError(
                    f"network.tunnels duplicate endpoint {tunnel.host}:{tunnel.remote_port} is not allowed"
                )
            seen_local_ports.add(tunnel.local_port)
            seen_endpoints.add(endpoint)
        return self


_SKILL_COMMAND_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class SkillCommandDecl(BaseModel):
    """A command alias declared in a skill's Carapace metadata."""

    name: str
    command: str

    @model_validator(mode="after")
    def _validate(self) -> SkillCommandDecl:
        if not _SKILL_COMMAND_NAME_RE.match(self.name):
            raise ValueError(
                "skill command name must start with an alphanumeric character and contain only letters, "
                "numbers, dots, underscores, or hyphens"
            )

        command = self.command.strip()
        if not command:
            raise ValueError("skill command must not be empty")
        if "\n" in command or "\r" in command:
            raise ValueError("skill command must be a single line")

        self.command = command
        return self


class SkillCarapaceConfig(BaseModel):
    """Parsed Carapace config declared inline in SKILL.md or in ``carapace.yaml``."""

    network: SkillNetworkConfig = SkillNetworkConfig()
    credentials: list[SkillCredentialDecl] = []
    commands: list[SkillCommandDecl] = []
    hints: dict[str, str] = {}

    @model_validator(mode="after")
    def _validate_commands(self) -> SkillCarapaceConfig:
        seen_names: set[str] = set()
        for command in self.commands:
            if command.name in seen_names:
                raise ValueError(f"duplicate skill command name {command.name!r} is not allowed")
            seen_names.add(command.name)
        return self


class ContextGrant(BaseModel):
    """Context-scoped grant for a skill's declared domains, tunnels, and credentials.

    Registered at ``use_skill`` time, keyed by skill name.  The agent must pass
    matching ``contexts`` on ``exec`` for these grants to take effect.
    """

    skill_name: str
    domains: set[str] = set()
    tunnels: list[NetworkTunnel] = []
    credential_decls: list[SkillCredentialDecl] = []
    credential_names: dict[str, str] = {}  # vault_path → human-readable name

    @property
    def vault_paths(self) -> set[str]:
        return {c.vault_path for c in self.credential_decls}


def context_grants_session_summary(
    session_id: str,
    context_grants: Mapping[str, ContextGrant],
    get_cached_credential: Callable[[str, str], str | None],
) -> dict[str, dict[str, Any]]:
    """Build per-skill ``context_grants`` payload for ``/session`` (all channels)."""
    summary: dict[str, dict[str, Any]] = {}
    for skill, grant in context_grants.items():
        cached = sum(1 for vp in grant.vault_paths if get_cached_credential(session_id, vp) is not None)
        summary[skill] = {
            "domains": sorted(grant.domains),
            "tunnels": [tunnel.display for tunnel in grant.tunnels],
            "vault_paths": sorted(grant.vault_paths),
            "cached_credentials": cached,
        }
    return summary


class SkillInfo(BaseModel):
    name: str
    description: str = ""
    path: Path


# --- Deps for Pydantic AI RunContext ---


type ToolCallCallback = Callable[
    [str, dict[str, Any], str, ApprovalSource | None, ApprovalVerdict | None, str | None], None
]


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
        description="Carapace-registered model id (custom id or provider:name); usage keys, not provider wire ids.",
    )

    verbose: bool = True
    tool_call_callback: ToolCallCallback | None = None
    tool_result_callback: Callable[[ToolResult], None] | None = None
    append_session_events: Callable[[list[dict[str, Any]]], None] | None = None
    usage_tracker: UsageTracker
    assert_llm_budget_available: Callable[[], None] | None = None
    llm_usage_limits: Callable[[], UsageLimits | None] | None = None
    credential_registry: CredentialRegistryProtocol
