from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict
from pydantic_ai.models import Model
from pydantic_settings import BaseSettings, SettingsConfigDict

from carapace.git.store import GitStore
from carapace.sandbox.manager import SandboxManager
from carapace.security.context import SessionSecurity
from carapace.security.sentinel import Sentinel
from carapace.usage import UsageTracker

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


class CredentialsConfig(BaseModel):
    backend: str = "mock"


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


class MemorySearchConfig(BaseModel):
    enabled: bool = False
    provider: str = "local"
    local_model: str = "all-MiniLM-L6-v2"


class MemoryConfig(BaseModel):
    search: MemorySearchConfig = MemorySearchConfig()


class GitConfig(BaseModel):
    """Git-backed knowledge store configuration."""

    remote: str = ""  # optional external remote URL
    branch: str = "main"
    author: str = "Carapace Agent <%s>"  # %s → session ID


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


class Config(BaseModel):
    carapace: CarapaceConfig = CarapaceConfig()
    server: ServerConfig = ServerConfig()
    channels: ChannelsConfig = ChannelsConfig()
    agent: AgentConfig = AgentConfig()
    credentials: CredentialsConfig = CredentialsConfig()
    sandbox: SandboxConfig = SandboxConfig()
    memory: MemoryConfig = MemoryConfig()
    git: GitConfig = GitConfig()
    data_dir: str = "."  # resolved relative to config file location
    knowledge_dir: str = "./knowledge"  # resolved relative to config file location


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
    tool_result_callback: Callable[[str, str], None] | None = None
    usage_tracker: UsageTracker
