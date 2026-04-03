from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from pydantic_ai.models import Model
from pydantic_settings import BaseSettings, SettingsConfigDict

from carapace.git.store import GitStore
from carapace.sandbox.manager import SandboxManager
from carapace.security.context import SessionSecurity
from carapace.security.sentinel import Sentinel
from carapace.usage import UsageTracker

# --- Credentials ---


class CredentialMetadata(BaseModel):
    """Vault credential metadata returned by backends and stored in session state."""

    vault_path: str
    name: str
    description: str = ""


# --- Session State ---


class SessionState(BaseModel):
    session_id: str
    channel_type: str = "cli"
    channel_ref: str | None = None
    title: str | None = None
    approved_credentials: list[CredentialMetadata] = []
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
        approved_credentials: list[CredentialMetadata] | None = None,
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


class AgentConfig(BaseModel):
    model: str = "anthropic:claude-sonnet-4-6"
    sentinel_model: str = "anthropic:claude-haiku-4-5"
    title_model: str = "anthropic:claude-haiku-4-5"

    # the default models are added automatically + this is only used for autocomplete, not enforced.
    available_models: list[str] = []

    max_parallel_llm: int = 2


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
    # Set an ownerReference on sandbox pods pointing to the carapace Deployment.
    # When True, deleting the Deployment garbage-collects all sandboxes.
    # When False, sandbox pods appear as standalone resources under the ArgoCD app.
    k8s_owner_ref: bool = True
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
    author: str = "Carapace Session %s <%s@carapace.local>"  # %s → session ID
    token: Secret | None = None


class ServerConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CARAPACE_SERVER_")

    host: str = "0.0.0.0"
    port: int = 8321
    sandbox_port: int = 8322
    internal_port: int = 8320
    cors_origins: list[str] = ["http://localhost:3000"]


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

    backends: dict[str, FileCredentialBackendConfig | BitwardenCredentialBackendConfig] = {}


class Config(BaseModel):
    carapace: CarapaceConfig = CarapaceConfig()
    server: ServerConfig = ServerConfig()
    channels: ChannelsConfig = ChannelsConfig()
    agent: AgentConfig = AgentConfig()
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


class SkillCredentialDecl(BaseModel):
    """A credential requirement declared in a skill's ``carapace.yaml``."""

    vault_path: str
    description: str = ""
    env_var: str | None = None
    file: str | None = None


class SkillNetworkConfig(BaseModel):
    domains: list[str] = []


class SkillCarapaceConfig(BaseModel):
    """Parsed contents of a skill's ``carapace.yaml``."""

    network: SkillNetworkConfig = SkillNetworkConfig()
    credentials: list[SkillCredentialDecl] = []
    hints: dict[str, str] = {}


class SkillInfo(BaseModel):
    name: str
    description: str = ""
    path: Path


# --- Deps for Pydantic AI RunContext ---


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
    verbose: bool = True
    tool_call_callback: Callable[[str, dict[str, Any], str], None] | None = None
    tool_result_callback: Callable[[ToolResult], None] | None = None
    usage_tracker: UsageTracker
    credential_registry: Any = None  # CredentialRegistry — Any to avoid circular import
