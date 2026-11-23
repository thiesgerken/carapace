from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import logging  # stdlib logging used only for _InterceptHandler → loguru bridge
import os
import re
import sys
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import logfire
import loguru
import uvicorn
from dotenv import load_dotenv
from fastapi import (
    APIRouter,
    FastAPI,
    HTTPException,
    Request,
    Response,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from genai_prices import UpdatePrices
from loguru import logger
from pydantic import BaseModel
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.models import Model
from sqlalchemy import Engine

from .. import get_version
from ..api_keys import ApiKeyStore
from ..artifact_shares import ArtifactShareStore
from ..auth import AuthStore
from ..bootstrap import ensure_data_dir, ensure_knowledge_dir
from ..builder.client import BuilderClient
from ..cache import SessionListCache
from ..codex_auth import CodexAccounts, CodexCredentialStore
from ..config import build_config
from ..credentials import CredentialBackendError, CredentialRegistry, build_credential_registry
from ..credentials.oauth import NotOAuthStateError, OAuthStateRefusedError, fetch_for_sandbox
from ..credentials.oauth import access_token as oauth_access_token
from ..credentials.protocol import UnsupportedCredentialValueKindError
from ..database.engine import SessionFactory, create_engine_and_factory, run_migrations
from ..git.flake_lock import summarize_lock_change
from ..git.http import GitHttpHandler
from ..jobs import JobsScheduler, JobsStore
from ..knowledge import KnowledgeRepoRegistry
from ..llm import ModelFactory, make_model_factory
from ..memory.handlers import DigestHandler, MirrorHandler, SessionExtractHandler
from ..memory.models import DigestLevel, TaskKind
from ..memory.service import MemoryService
from ..memory.store import MemoryStore
from ..models.config import BuilderConfig, Config, SandboxConfig
from ..models.credentials import CredentialMetadata, CredentialValueKind
from ..models.user import UserConfig
from ..notifications.presence import NotificationPresenceRegistry
from ..notifications.router import NotificationRouter
from ..notifications.sender import WebPushSender
from ..notifications.store import NotificationStore
from ..notifications.vapid import ensure_vapid_config
from ..platform_store import PlatformSettingsStore
from ..prompt_prefix import shared_prompt_prefix
from ..sandbox.destinations import DestinationPolicy
from ..sandbox.egress_check import EgressCheckError, EgressProbeError
from ..sandbox.exec_flow import EXEC_ENDED_REJECTION, ORPHANED_REQUEST_REJECTION
from ..sandbox.exec_scope import CredentialGrant
from ..sandbox.manager import SandboxLimitError, SandboxManager
from ..sandbox.proxy import ProxyServer, domain_allowed
from ..sandbox.runtime import ContainerRuntime
from ..security import (
    CREDENTIAL_LISTING_PATH,
    CredentialAccessEvaluation,
    SessionSecurity,
    evaluate_credential_listing_with,
    evaluate_credential_with,
    evaluate_push_with,
    evaluate_upfront_request_with,
)
from ..security.context import UpfrontRequest
from ..security.sentinel import Sentinel
from ..session import SessionEngine, SessionManager
from ..session.archive import SessionArchiveService
from ..session.types import ActiveSession
from ..usage import SessionBudgetExceededError
from .api_keys import router as api_keys_router
from .artifacts import router as artifacts_router
from .auth import router as auth_router
from .auth import verify_ws_token
from .codex_auth import router as codex_auth_router
from .history import router as history_router
from .home import router as home_router
from .jobs import _jobs_scheduler_loop
from .jobs import router as jobs_router
from .knowledge import router as knowledge_router
from .memory import router as memory_router
from .notifications import _set_notification_presence as _set_notification_presence
from .notifications import router as notifications_router
from .platform_settings import router as platform_settings_router
from .prompts import router as prompts_router
from .runtime import KnowledgeGitConfig, KnowledgeGitRuntime, MatrixChannelHandle, MatrixChannelManager
from .session_sandbox import router as session_sandbox_router
from .sessions import router as sessions_router
from .user_settings import router as user_settings_router
from .websocket import ServerMeta as ServerMeta
from .websocket import VapidPublicKeyResponse as VapidPublicKeyResponse
from .websocket import WebSocketSubscriber as WebSocketSubscriber
from .websocket import _llm_activity_payload as _llm_activity_payload
from .websocket import _send as _send
from .websocket import router as websocket_router

load_dotenv()

# --- Shared state populated in lifespan ---

_data_dir: Path
_config: Config
_model_factory: ModelFactory
_engine_db: Engine
_session_factory: SessionFactory
_engine: SessionEngine
_git_handler: GitHttpHandler
_knowledge_repo_registry: KnowledgeRepoRegistry
_knowledge_git_runtime: KnowledgeGitRuntime
_matrix_channel_manager: MatrixChannelManager
_user_credential_registries: dict[str, tuple[str, CredentialRegistry]]
_session_archive: SessionArchiveService
_session_list_cache: SessionListCache
_jobs_store: JobsStore
_jobs_scheduler: JobsScheduler
_notification_store: NotificationStore
_notification_presence: NotificationPresenceRegistry
_notification_router: NotificationRouter
_auth_store: AuthStore
_api_key_store: ApiKeyStore
_artifact_share_store: ArtifactShareStore
_platform_store: PlatformSettingsStore
_codex_accounts: CodexAccounts
_memory_service: MemoryService
_builder: BuilderClient | None


def _enabled_user_git_configs(auth_store: AuthStore) -> dict[str, KnowledgeGitConfig]:
    configs: dict[str, KnowledgeGitConfig] = {}
    for username, user in sorted(auth_store.load_users().users.items()):
        if not user.enabled:
            continue
        configs[username] = KnowledgeGitConfig(
            owner=username,
            remote=user.config.git.remote,
            branch=user.config.git.branch,
            author=user.config.git.author,
            token=user.config.git.token,
        )
    return configs


async def _bootstrap_user_knowledge_repo(
    repo_registry: KnowledgeRepoRegistry,
    username: str,
    config: KnowledgeGitConfig,
) -> None:
    handle = repo_registry.ensure_user_repo(username)
    git_store = handle.git_store
    git_store.remote_branch = config.branch
    git_store.author_template = config.author
    await git_store.ensure_repo()

    if config.remote:
        logger.info(f"Using knowledge Git remote from user {username}")
        await git_store.add_remote(config.remote, config.token)
        try:
            summary = await git_store.pull_from_remote()
            logger.info(f"Pulled from remote for user {username}: {summary}")
        except RuntimeError as exc:
            # An unreachable or diverged remote must not keep the server from starting. Seeding
            # is skipped too: on a fresh repo the pull would have adopted the remote branch, and
            # a local seed commit instead would fork the history so later pulls never fast-forward.
            logger.error(
                f"Pulling knowledge Git remote for user {username} failed, continuing with the local repo: {exc}"
            )
            return
    else:
        await git_store.remove_remote()

    seeded = ensure_knowledge_dir(handle.knowledge_dir)
    if not seeded:
        return
    try:
        committed = await git_store.commit(seeded, "🔧 bootstrap: seed default files")
    except RuntimeError as exc:
        logger.warning(f"Bootstrap knowledge seed commit failed for user {username}: {exc}")
        return
    if committed and git_store.remote_configured:
        await git_store.push_to_remote()


_SESSION_COMMIT_SWEEP_SECONDS = 15 * 60
_APP_VERSION = get_version()
_verify_ws_token = verify_ws_token


async def _connect_builder(config: BuilderConfig) -> BuilderClient | None:
    if config.url is None:
        logger.warning("No skill builder configured (CARAPACE_BUILDER_URL); skills with commands are not built")
        return None
    assert config.token is not None, "BuilderConfig requires a token with a URL"
    client = BuilderClient(config.url, config.token.get_secret_value(), config.timeout_seconds)
    try:
        await client.check_system()
    except httpx.HTTPError as exc:
        # Not fatal: the builder may come up after the server, and the first build checks again.
        # A builder for another architecture is: BuilderSystemMismatchError stops the start.
        logger.warning(f"Skill builder at {config.url} is unreachable ({exc}); checking again on first use")
    return client


def _destination_policy(config: SandboxConfig, server_addresses: list[str]) -> DestinationPolicy:
    own = {ipaddress.ip_address(address) for address in server_addresses}
    # The Kubernetes API, as the service address every pod sees.
    if kubernetes_api := os.environ.get("KUBERNETES_SERVICE_HOST"):
        own.add(ipaddress.ip_address(kubernetes_api))
    return DestinationPolicy(
        allowed_networks=tuple(config.proxy_allowed_networks),
        allowed_hosts=frozenset(host.lower() for host in config.proxy_allowed_hosts),
        own_addresses=frozenset(own),
    )


def _create_sandbox_runtime(config: Config, data_dir: Path) -> ContainerRuntime:
    """Instantiate the sandbox container runtime based on config."""
    if config.sandbox.runtime == "kubernetes":
        from ..sandbox.kubernetes import KubernetesRuntime

        return KubernetesRuntime(
            namespace=config.sandbox.k8s_namespace,
            pvc_claim=config.sandbox.k8s_pvc_claim,
            data_dir=data_dir,
            service_account=config.sandbox.k8s_service_account,
            priority_class=config.sandbox.k8s_priority_class,
            owner_ref=config.sandbox.k8s_owner_ref,
            server_deployment_name=config.sandbox.k8s_server_deployment_name,
            sandboxes_name=config.sandbox.k8s_sandboxes_name,
            app_instance=config.sandbox.k8s_app_instance,
            session_pvc_size=config.sandbox.k8s_session_pvc_size,
            session_pvc_storage_class=config.sandbox.k8s_session_pvc_storage_class,
            resource_requests_cpu=config.sandbox.k8s_resource_requests_cpu,
            resource_requests_memory=config.sandbox.k8s_resource_requests_memory,
            resource_limits_cpu=config.sandbox.k8s_resource_limits_cpu,
            resource_limits_memory=config.sandbox.k8s_resource_limits_memory,
        )

    from ..sandbox.docker import DockerRuntime

    host_data_dir_env = os.environ.get("CARAPACE_HOST_DATA_DIR")
    return DockerRuntime(
        data_dir=data_dir,
        host_data_dir=Path(host_data_dir_env) if host_data_dir_env else None,
        network_name=config.sandbox.network_name,
    )


def _enabled_usernames() -> list[str]:
    return [name for name, user in _auth_store.load_users().users.items() if user.enabled]


# Admins swap ``_config`` and ``_model_factory`` at runtime (platform settings). Memory reads them
# through these on every use, so a model added or removed applies without a restart.
def _live_config() -> Config:
    return _config


def _live_model_factory(model_name: str, *, user: str) -> Model:
    return _model_factory(model_name, user=user)


def _user_config(username: str) -> UserConfig:
    user = _auth_store.get_user(username)
    if user is None:
        raise KeyError(username)
    return user.config


def _credential_config_fingerprint(username: str) -> str:
    user = _auth_store.get_user(username)
    if user is None:
        raise KeyError(username)
    return user.config.credentials.model_dump_json(exclude_none=True)


async def _credential_registry_for_user(username: str) -> CredentialRegistry:
    fingerprint = _credential_config_fingerprint(username)

    cached = _user_credential_registries.get(username)
    if cached is not None:
        cached_fingerprint, cached_registry = cached
        if cached_fingerprint == fingerprint:
            return cached_registry
        await cached_registry.close()

    user = _auth_store.get_user(username)
    if user is None:
        raise KeyError(username)
    registry = await build_credential_registry(
        user.config.credentials,
        _data_dir,
    )
    _user_credential_registries[username] = (fingerprint, registry)
    if registry.backend_names:
        logger.info(f"Credential backends for user {username!r}: {', '.join(registry.backend_names)}")
    return registry


async def _credential_registry_for_session(session_id: str) -> CredentialRegistry:
    meta = _engine.session_mgr.load_meta(session_id)
    return await _credential_registry_for_user(meta.user)


async def _idle_cleanup_loop(sandbox_mgr: SandboxManager) -> None:
    """Periodically clean up idle sandbox containers."""
    while True:
        await asyncio.sleep(60)
        try:
            await sandbox_mgr.cleanup_idle()
        except Exception as exc:
            logger.warning(f"Sandbox idle cleanup error: {exc}")


async def _warm_pool_loop(sandbox_mgr: SandboxManager, target_size: int) -> None:
    """Keep the warm sandbox pool at its target size.

    Runs an initial pass immediately (in the background, so it never blocks API
    startup) and then maintains the pool on an interval.
    """
    while True:
        try:
            await sandbox_mgr.ensure_warm_pool(target_size)
        except Exception as exc:
            logger.warning(f"Warm sandbox pool maintenance error: {exc}")
        await asyncio.sleep(60)


async def _session_archive_loop() -> None:
    """Periodically archive inactive sessions into the knowledge repo."""
    while True:
        await asyncio.sleep(_SESSION_COMMIT_SWEEP_SECONDS)
        try:
            await _autosave_inactive_sessions()
        except Exception as exc:
            logger.warning(f"Session archive autosave loop error: {exc}")


async def _autosave_inactive_sessions() -> None:
    if not _session_archive.enabled or not _config.sessions.commit.autosave_enabled:
        return

    cutoff = datetime.now(tz=UTC) - timedelta(hours=_config.sessions.commit.autosave_inactivity_hours)
    try:
        session_ids = _engine.session_mgr.list_sessions()
    except Exception as exc:
        logger.warning(f"Session archive autosave error while listing sessions: {exc}")
        return

    for session_id in session_ids:
        try:
            state = _engine.session_mgr.load_state(session_id)
            if state is None or state.attributes.private or state.last_active > cutoff:
                continue
            if state.knowledge_last_committed_at is not None and state.knowledge_last_committed_at >= state.last_active:
                continue
            if _engine.is_agent_running(session_id):
                continue
            await _session_archive.commit_session(
                session_id,
                trigger="autosave",
                autosave_cutoff=cutoff,
                is_agent_running=lambda session_id=session_id: _engine.is_agent_running(session_id),
            )
        except Exception as exc:
            logger.warning(f"Session archive autosave error for {session_id}: {exc}")


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None]:
    global \
        _data_dir, \
        _config, \
        _model_factory, \
        _engine_db, \
        _session_factory, \
        _engine, \
        _git_handler, \
        _knowledge_repo_registry, \
        _knowledge_git_runtime, \
        _matrix_channel_manager, \
        _user_credential_registries, \
        _session_archive, \
        _session_list_cache, \
        _jobs_store, \
        _jobs_scheduler, \
        _notification_store, \
        _notification_presence, \
        _notification_router, \
        _auth_store, \
        _api_key_store, \
        _artifact_share_store, \
        _platform_store, \
        _codex_accounts, \
        _memory_service, \
        _builder

    # 1. Build config from env (CARAPACE_DATA_DIR + CARAPACE_* subsections; no config file)
    _config = build_config()
    _data_dir = Path(_config.data_dir).resolve()

    # 2. Bootstrap directories + database
    ensure_data_dir(_data_dir)
    _engine_db, _session_factory = create_engine_and_factory(_config.database, _data_dir)
    run_migrations(_engine_db)

    # Runtime platform config (model catalog + scalar agent/sessions settings) lives in the DB.
    # Overlay the DB values onto the in-memory Config. An empty catalog falls back to the
    # AgentConfig code defaults, so a fresh DB boots until an admin configures the catalog.
    _platform_store = PlatformSettingsStore(_session_factory)
    _config = _platform_store.overlay_config(_config)

    _auth_store = AuthStore(_session_factory, _config.auth, _data_dir)
    _api_key_store = ApiKeyStore(_session_factory, _auth_store)
    _artifact_share_store = ArtifactShareStore(_session_factory)
    _codex_accounts = CodexAccounts(CodexCredentialStore(_session_factory))
    if _auth_store.ensure_bootstrap_admin() is not None:
        logger.warning("Created bootstrap admin user 'admin' with password from CARAPACE_TOKEN")
    _knowledge_repo_registry = KnowledgeRepoRegistry(_data_dir)
    user_git_configs = _enabled_user_git_configs(_auth_store)
    for username, git_config in user_git_configs.items():
        await _bootstrap_user_knowledge_repo(_knowledge_repo_registry, username, git_config)

    if _config.carapace.logfire_token:
        logfire.configure(token=_config.carapace.logfire_token, console=False)
        logfire.instrument_pydantic_ai()

    _session_list_cache = SessionListCache(_config.cache)
    session_mgr = SessionManager(_session_factory, _data_dir, on_change=_session_list_cache.invalidate_sync)
    # No eager default-model construction: a fresh install has no provider credentials yet, and
    # the admin needs the server up to configure them. SessionEngine resolves on first use.
    _model_factory = make_model_factory(_config, _codex_accounts.provider_for)

    runtime = _create_sandbox_runtime(_config, _data_dir)

    network_info = await runtime.get_self_network_info()
    if network_info:
        for net_name, ip in network_info.items():
            logger.info(f"Network interface: {net_name} → {ip}")
    else:
        logger.warning("Could not determine any network addresses")

    base_image = _config.sandbox.base_image

    if not runtime.image_exists(base_image):
        logger.error(
            f"Sandbox image '{base_image}' not found. "
            f"Build it with: docker compose build sandbox\n"
            f"Or pull it with: docker pull {base_image}"
        )
        raise SystemExit(1)

    _builder = await _connect_builder(_config.builder)

    sandbox_network = _config.sandbox.network_name
    if _config.sandbox.runtime == "docker":
        # Resolve the actual Docker network name once at startup.
        # Docker Compose prefixes networks with the project name, so the logical
        # name "carapace-sandbox" may be "carapace_carapace-sandbox" in Docker.
        sandbox_network = await runtime.resolve_self_network_name(sandbox_network)
        if sandbox_network != _config.sandbox.network_name:
            logger.info(f"Resolved sandbox network '{_config.sandbox.network_name}' → '{sandbox_network}'")

        # Pre-create the network when not already managed by docker-compose,
        # always as internal so sandbox containers have no direct internet egress.
        await runtime.ensure_network(sandbox_network, internal=True)

    proxy_port = _config.sandbox.proxy_port

    def resolve_session_owner(session_id: str) -> str:
        return session_mgr.load_meta(session_id).user

    def knowledge_repo_for_session(session_id: str):
        return _knowledge_repo_registry.get_for_session(session_id, resolve_session_owner)

    def prompt_prefix_for_user(user: str) -> str:
        handle = _knowledge_repo_registry.get_for_user(user)
        return shared_prompt_prefix(handle.knowledge_dir, handle.skill_registry.scan())

    _sandbox_mgr = SandboxManager(
        runtime=runtime,
        data_dir=_data_dir,
        session_factory=_session_factory,
        base_image=base_image,
        network_name=sandbox_network,
        idle_timeout_minutes=_config.sandbox.idle_timeout_minutes,
        proxy_port=proxy_port,
        sandbox_port=_config.server.sandbox_port,
        warm_pool_size=_config.sandbox.warm_pool_size,
        skill_activator_timeout_seconds=_config.sandbox.skill_activator_timeout_seconds,
        max_sandboxes_per_user=_config.sandbox.max_per_user,
        knowledge_repo_for_session=knowledge_repo_for_session,
    )
    logger.info(f"Sandbox enabled (image={base_image}, network={sandbox_network})")

    _knowledge_git_runtime = KnowledgeGitRuntime(
        repo_registry=_knowledge_repo_registry,
        sandbox_mgr=_sandbox_mgr,
        current_configs=user_git_configs,
    )

    if _config.sandbox.cleanup_orphans_on_startup:
        known = set(session_mgr.list_sessions())
        removed = await _sandbox_mgr.cleanup_orphaned_sandboxes(known)
        if removed:
            logger.info(f"Cleaned up {removed} orphaned sandbox(es)")

    # Warm pool is provisioned by _warm_pool_loop (background task) so it never
    # blocks API startup; its first iteration runs immediately.

    _user_credential_registries = {}

    _config.notifications = ensure_vapid_config(_config.notifications, _data_dir)

    _notification_store = NotificationStore(_session_factory)
    _notification_presence = NotificationPresenceRegistry(
        ttl=timedelta(seconds=_config.notifications.presence_ttl_seconds)
    )
    _notification_router = NotificationRouter(
        store=_notification_store,
        presence=_notification_presence,
        sender=WebPushSender(
            store=_notification_store,
            vapid_private_key=_config.notifications.vapid_private_key,
            vapid_subject=_config.notifications.vapid_subject,
            timeout_seconds=_config.notifications.send_timeout_seconds,
            retry_attempts=_config.notifications.retry_attempts,
            retry_backoff_seconds=_config.notifications.retry_backoff_seconds,
            max_payload_bytes=_config.notifications.max_payload_bytes,
            delivery_ttl_seconds=_config.notifications.delivery_ttl_seconds,
        ),
        owner_for_session=resolve_session_owner,
    )

    _engine = SessionEngine(
        config=_config,
        data_dir=_data_dir,
        session_mgr=session_mgr,
        sandbox_mgr=_sandbox_mgr,
        credential_registry_for_session=_credential_registry_for_session,
        knowledge_repo_for_session=knowledge_repo_for_session,
        # Late-bound: the memory service is built after the engine, and only turns call this.
        memory_block_for=lambda user, state: _memory_service.session_prompt_block(user, state).text,
        model_factory=_model_factory,
        notification_router=_notification_router,
    )
    # A restart kills turns without running their finalization, so their open approval
    # requests are closed here, before any channel or job can activate a session.
    _engine.close_orphaned_approval_requests()
    _session_archive = SessionArchiveService(
        session_mgr=session_mgr,
        config=_config.sessions.commit,
        knowledge_repo_for_session=knowledge_repo_for_session,
    )
    _jobs_store = JobsStore(_session_factory)
    _jobs_scheduler = JobsScheduler(_jobs_store)
    memory_store = MemoryStore(_session_factory)
    _memory_service = MemoryService(
        current_config=_live_config,
        store=memory_store,
        sessions=session_mgr,
        jobs=_jobs_store,
        handlers={
            TaskKind.session_extract: SessionExtractHandler(
                current_config=_live_config,
                load_state=session_mgr.load_state,
                load_events=session_mgr.load_events,
                user_config_for=_user_config,
                prompt_prefix_for=prompt_prefix_for_user,
                model_factory=_live_model_factory,
            ),
            TaskKind.week_digest: DigestHandler(
                level=DigestLevel.week,
                current_config=_live_config,
                current_extractions=memory_store.current_extractions,
                current_digests=memory_store.current_digests,
                prompt_prefix_for=prompt_prefix_for_user,
                model_factory=_live_model_factory,
            ),
            TaskKind.month_digest: DigestHandler(
                level=DigestLevel.month,
                current_config=_live_config,
                current_extractions=memory_store.current_extractions,
                current_digests=memory_store.current_digests,
                prompt_prefix_for=prompt_prefix_for_user,
                model_factory=_live_model_factory,
            ),
            TaskKind.mirror: MirrorHandler(
                current_extractions=memory_store.current_extractions,
                current_digests=memory_store.current_digests,
                knowledge_repo_for_user=_knowledge_repo_registry.ensure_user_repo,
                push_if_configured=_knowledge_git_runtime.push_if_configured,
            ),
        },
        user_config_for=_user_config,
        users=_enabled_usernames,
        is_agent_running=_engine.is_agent_running,
    )

    # Git HTTP handler — serves the knowledge repo on the sandbox API
    _git_handler = GitHttpHandler(
        knowledge_root=_knowledge_repo_registry.knowledge_repos_dir,
        owner_for_session=resolve_session_owner,
        default_branch="main",
        api_port=_config.server.internal_port,
        verify_session_token=_sandbox_mgr.verify_session_token,
        on_push_success=_knowledge_git_runtime.push_if_configured,
    )

    proxy = ProxyServer(
        verify_session_token=_sandbox_mgr.verify_session_token,
        get_allowed_domains=_sandbox_mgr.get_effective_domains,
        attach_sandbox_call=_engine.attach_sandbox_call,
        request_approval=_sandbox_mgr.request_domain_approval,
        notify_domain_access=_sandbox_mgr.notify_domain_access,
        destinations=_destination_policy(_config.sandbox, list(network_info.values())),
        host="0.0.0.0",
        port=proxy_port,
    )
    await proxy.start()

    # After the proxy starts, which the probe connects to as its positive control; before anything is served.
    try:
        await _sandbox_mgr.verify_no_direct_egress(Path("/etc/resolv.conf"))
    except EgressCheckError as exc:
        logger.error(_egress_check_failure(exc, _config.sandbox.runtime, sandbox_network))
        raise SystemExit(1) from exc
    except EgressProbeError as exc:
        logger.error(str(exc))
        raise SystemExit(1) from exc

    # Start sandbox-facing API server (Basic Auth, accessible by containers)
    sandbox_server = uvicorn.Server(
        uvicorn.Config(
            sandbox_app,
            host="0.0.0.0",
            port=_config.server.sandbox_port,
            log_level=_config.carapace.log_level,
            log_config=None,
        )
    )
    sandbox_task = asyncio.create_task(sandbox_server.serve())
    logger.info(f"Sandbox API listening on 0.0.0.0:{_config.server.sandbox_port}")

    # Start internal API server (loopback only, no auth)
    internal_server = uvicorn.Server(
        uvicorn.Config(
            internal_app,
            host="127.0.0.1",
            port=_config.server.internal_port,
            log_level=_config.carapace.log_level,
            log_config=None,
        )
    )
    internal_task = asyncio.create_task(internal_server.serve())
    logger.info(f"Internal API listening on 127.0.0.1:{_config.server.internal_port}")

    await _session_list_cache.start()

    price_updater = UpdatePrices()
    price_updater.start()

    cleanup_task = asyncio.create_task(_idle_cleanup_loop(_sandbox_mgr))
    warm_pool_task = None
    # Run on Kubernetes regardless of size: a target of 0 tears down any
    # leftover pool StatefulSets after the feature is disabled or shrunk.
    if _config.sandbox.runtime == "kubernetes":
        warm_pool_task = asyncio.create_task(_warm_pool_loop(_sandbox_mgr, _config.sandbox.warm_pool_size))
    archive_task = asyncio.create_task(_session_archive_loop())
    jobs_task = asyncio.create_task(_jobs_scheduler_loop())
    memory_task = asyncio.create_task(_memory_service.run())

    def matrix_channel_factory(username: str, user_config: UserConfig) -> MatrixChannelHandle:
        from ..channels.matrix import MatrixChannel

        return MatrixChannel(
            config=user_config.channels.matrix,
            full_config=_config,
            session_mgr=session_mgr,
            sandbox_mgr=_sandbox_mgr,
            engine=_engine,
            owner_user=username,
            owner_config=user_config,
            presence_registry=_notification_presence,
        )

    _matrix_channel_manager = MatrixChannelManager(matrix_channel_factory)
    for username, stored_user in sorted(_auth_store.load_users().users.items()):
        if stored_user.enabled and stored_user.config.channels.matrix.enabled:
            await _matrix_channel_manager.reload_user_with_retry(username, stored_user.config)

    logger.info(
        f"carapace server ready — model={_config.agent.model}, "
        f"user_repos={len(user_git_configs)}, proxy_port={proxy_port}"
        + (
            f", matrix=on ({_matrix_channel_manager.channel_count} user channel(s))"
            if _matrix_channel_manager.channel_count
            else ""
        )
    )
    yield
    logger.info("Server shutting down…")
    cleanup_task.cancel()
    if warm_pool_task is not None:
        warm_pool_task.cancel()
    archive_task.cancel()
    jobs_task.cancel()
    memory_task.cancel()
    await _matrix_channel_manager.stop_all()
    sandbox_server.should_exit = True
    internal_server.should_exit = True
    sandbox_task.cancel()
    internal_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await sandbox_task
    with contextlib.suppress(asyncio.CancelledError):
        await internal_task
    await proxy.stop()
    for _, registry in _user_credential_registries.values():
        await registry.close()
    await _sandbox_mgr.cleanup_all()
    if _builder is not None:
        await _builder.aclose()
    await _session_list_cache.close()
    _engine_db.dispose()
    price_updater.stop()
    logger.info("Shutdown complete")


app = FastAPI(title="carapace", version=_APP_VERSION, lifespan=_lifespan)

router = APIRouter(prefix="/api")

# CORS must be added before the app starts (Starlette forbids it in lifespan).
# Read the allowed origins from env early (no config file).
_cors_config = build_config()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_config.server.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(SandboxLimitError)
async def _sandbox_limit_reached(_request: Request, exc: SandboxLimitError) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(exc)})


_NO_STORE_API_PREFIX = "/api"


def _should_disable_cache(path: str, method: str) -> bool:
    if method not in {"GET", "HEAD"}:
        return False
    return path == _NO_STORE_API_PREFIX or path.startswith(f"{_NO_STORE_API_PREFIX}/")


@app.middleware("http")
async def add_cache_control_headers(request: Request, call_next) -> Response:
    response = await call_next(request)
    if _should_disable_cache(request.url.path, request.method):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    return response


class _InterceptHandler(logging.Handler):
    """Route stdlib logging records to loguru."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        frame, depth = logging.currentframe(), 0
        while frame and (depth == 0 or frame.f_code.co_filename == logging.__file__):
            frame = frame.f_back
            depth += 1
        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def _setup_logging(level: str = "INFO") -> None:
    logging.root.handlers = [_InterceptHandler()]
    logging.root.setLevel(logging.DEBUG)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi"):
        log = logging.getLogger(name)
        log.handlers = [_InterceptHandler()]
        log.propagate = False

    for name in (
        "httpcore",
        "httpx",
        "docker",
        "anthropic",
        "openai",
        "openai._base_client",
        "websockets",
        "websockets.server",
        "urllib3",
        "nio",
        "markdown.core",
    ):
        logging.getLogger(name).setLevel(logging.WARNING)

    def _abbrev_patcher(record: loguru.Record) -> None:
        if record["name"]:
            record["name"] = record["name"].replace("carapace.", "cp.").replace("sandbox.", "sndbx.")

    logger.remove()
    logger.add(
        sys.stderr,
        colorize=True,
        level=level.upper(),
        backtrace=True,
        diagnose=True,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}:{function}:{line}</cyan> | "
            "<level>{message}</level>"
        ),
    )
    logger.configure(patcher=_abbrev_patcher)


def main() -> None:
    """Entry point for `python -m carapace` / `carapace-server`."""
    load_dotenv()

    config = build_config()
    ensure_data_dir(Path(config.data_dir).resolve())
    _setup_logging(config.carapace.log_level)
    logger.info(f"Starting carapace server on {config.server.host}:{config.server.port}")
    logger.info(f"Sandbox API on 0.0.0.0:{config.server.sandbox_port}")
    logger.info(f"Internal API on 127.0.0.1:{config.server.internal_port}")

    uvicorn.run(
        "carapace.server:app",
        host=config.server.host,
        port=config.server.port,
        log_level=config.carapace.log_level,
        log_config=None,
    )


# --- Internal endpoint for pre-receive hook sentinel evaluation ---
# Bound to 127.0.0.1 only — unreachable from sandbox containers.

internal_app = FastAPI(title="carapace Internal")


class FlakeLockChange(BaseModel):
    path: str
    # None where the lock does not exist on that side of the push.
    old: str | None
    new: str | None


class PushEvalRequest(BaseModel):
    session_id: str
    ref: str
    is_default_branch: bool
    commits: str
    diff: str
    flake_locks: list[FlakeLockChange]


@internal_app.post("/internal/sentinel/evaluate-push")
async def evaluate_push(req: PushEvalRequest) -> dict[str, str]:
    """Evaluate a Git push via the sentinel. Called by the pre-receive hook."""
    try:
        active = _engine.get_or_activate(req.session_id)
    except KeyError:
        return {"verdict": "deny", "reason": "Session not found"}
    if active.security is None or active.sentinel is None:
        return {"verdict": "deny", "reason": "Session not initialized"}

    # The pre-receive hook runs in its own request, outside the git push that triggered it.
    with _engine.llm_request_recording(active), _engine.attach_sandbox_call(req.session_id):
        try:
            evaluation = await evaluate_push_with(
                active.security,
                active.sentinel,
                req.ref,
                req.is_default_branch,
                req.commits,
                req.diff,
                shared_artifacts=_artifact_share_store.shared_slugs(active.owner),
                flake_input_changes=[
                    line for lock in req.flake_locks for line in summarize_lock_change(lock.path, lock.old, lock.new)
                ],
                usage_tracker=active.usage_tracker,
                assert_llm_budget_available=lambda: _engine._assert_llm_budget_available(active),
                usage_limits=_engine._remaining_aux_usage_limits(active),
            )
        except SessionBudgetExceededError as exc:
            return {"verdict": "deny", "reason": str(exc)}
        except UsageLimitExceeded as exc:
            return {"verdict": "deny", "reason": str(exc)}
    if evaluation.allowed:
        return {"verdict": "allow"}
    return {"verdict": "deny", "reason": evaluation.rejection}


router.include_router(sessions_router)
router.include_router(history_router)
router.include_router(jobs_router)
router.include_router(knowledge_router)
router.include_router(artifacts_router)
router.include_router(memory_router)
router.include_router(prompts_router)
router.include_router(home_router)
router.include_router(session_sandbox_router)
router.include_router(notifications_router)
router.include_router(platform_settings_router)
router.include_router(user_settings_router)
router.include_router(codex_auth_router)
router.include_router(websocket_router)
router.include_router(auth_router)
router.include_router(api_keys_router)
app.include_router(router)


# --- Sandbox-facing API (Basic Auth, serves git HTTP backend) ---

sandbox_app = FastAPI(title="carapace Sandbox API")


@sandbox_app.middleware("http")
async def attach_sandbox_call_to_turn(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Sandbox API calls come from an exec in a running turn: their spans (credential, sentinel, waits) belong to it."""
    session_id = _authenticate_sandbox(request.headers.get("authorization"))
    if session_id is None:
        return await call_next(request)
    with _engine.attach_sandbox_call(session_id):
        return await call_next(request)


@sandbox_app.api_route("/git/{path:path}", methods=["GET", "POST"])
async def git_http_backend(request: Request, path: str) -> Response:
    """Proxy Git HTTP Smart Protocol requests to ``git http-backend``."""
    auth = request.headers.get("authorization")
    session_id = _git_handler.authenticate(auth)
    if session_id is None:
        return Response(
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="carapace git"'},
        )

    full_path = f"/git/{path}"
    query = str(request.query_params)
    body = await request.body()

    status_code, headers, response_body = await _git_handler.handle(
        session_id=session_id,
        method=request.method,
        path=full_path,
        query_string=query,
        content_type=request.headers.get("content-type"),
        body=body,
    )
    return Response(content=response_body, status_code=status_code, headers=headers)


def _egress_check_failure(exc: EgressCheckError, runtime: str, sandbox_network: str) -> str:
    """Why carapace refuses to start when a sandbox can reach the network directly, and how to fix it."""
    fix = (
        "On Kubernetes this usually means the CNI does not enforce NetworkPolicy (standalone Flannel ignores "
        + "it; Calico, Cilium and k3s' built-in policy controller enforce it), or another NetworkPolicy in the "
        + "namespace grants sandbox pods wider egress. Install an enforcing CNI or remove the wider policy."
        if runtime == "kubernetes"
        else f"On Docker the sandbox network '{sandbox_network}' must be internal: check `docker network inspect "
        + f'{sandbox_network}` for "Internal": true, and recreate the network as internal if it is not '
        + "(docker-compose.yml declares it with `internal: true`)."
    )
    return (
        "Sandbox egress self-test failed: "
        + "; ".join(exc.leaks)
        + ". Sandbox commands are only safe while their traffic has to pass the session proxy, so carapace "
        + "refuses to start. "
        + fix
        + " See docs/security.md, section 'Start-up egress self-test'."
    )


def _authenticate_sandbox(auth: str | None) -> str | None:
    """Extract and verify session_id from Basic Auth on the sandbox API."""
    if not auth or not auth.startswith("Basic "):
        return None
    import base64

    try:
        decoded = base64.b64decode(auth.removeprefix("Basic ")).decode()
    except Exception:
        return None
    session_id, _, token = decoded.partition(":")
    if not session_id or not token:
        return None
    if _engine.sandbox_mgr.verify_session_token(session_id, token):
        return session_id
    return None


def _credential_backend_unavailable(exc: CredentialBackendError) -> Response:
    return Response(status_code=503, content=str(exc), media_type="text/plain")


async def _gate_credential_request(
    active: ActiveSession,
    grant: CredentialGrant,
    review: Callable[[SessionSecurity, Sentinel, str, bool], Awaitable[CredentialAccessEvaluation]],
) -> Response | None:
    """Review a credential request of the running exec; returns the denial, or None to go ahead.

    An approval holds for the rest of that exec, so a script asking again does not cost another review.
    """
    sandbox_mgr = _engine.sandbox_mgr
    running = sandbox_mgr.running_exec(active.state.session_id)
    if running is None:
        return _boundary_denied(ORPHANED_REQUEST_REJECTION)
    if grant in running.credentials:
        return None
    if active.security is None or active.sentinel is None:
        return _boundary_denied("Session not initialized")

    with _engine.llm_request_recording(active):
        try:
            evaluation = await review(active.security, active.sentinel, running.command, running.boundary_reviewed)
        except (SessionBudgetExceededError, UsageLimitExceeded) as exc:
            return _boundary_denied(str(exc))
    if not sandbox_mgr.is_running(running):
        return _boundary_denied(EXEC_ENDED_REJECTION)
    running.boundary_reviewed = True
    if not evaluation.allowed:
        return _boundary_denied(evaluation.rejection)
    running.credentials.add(grant)
    return None


def _boundary_denied(rejection: str) -> Response:
    # ccred and cgate print the body on stderr: the command that asked reads why and decides how to continue.
    return Response(status_code=403, content=rejection, media_type="text/plain")


@sandbox_app.get("/credentials")
async def list_credentials(request: Request, q: str = "") -> Response:
    """List/search available credentials (metadata only, no values, still sentinel-gated)."""
    session_id = _authenticate_sandbox(request.headers.get("authorization"))
    if session_id is None:
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        credential_registry = await _credential_registry_for_session(session_id)
    except KeyError:
        raise HTTPException(status_code=403, detail="Session owner is not configured") from None

    active = _engine.get_or_activate(session_id)
    denial = await _gate_credential_request(
        active,
        (CREDENTIAL_LISTING_PATH, None),
        lambda security, sentinel, command, follow_up: evaluate_credential_listing_with(
            security,
            sentinel,
            q,
            command,
            follow_up=follow_up,
            usage_tracker=active.usage_tracker,
            assert_llm_budget_available=lambda: _engine._assert_llm_budget_available(active),
            usage_limits=_engine._remaining_aux_usage_limits(active),
        ),
    )
    if denial is not None:
        return denial

    try:
        items = await credential_registry.list(q)
    except CredentialBackendError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return JSONResponse([i.model_dump() for i in items])


class UpfrontRequestBody(BaseModel):
    """What ``cgate request`` sends; see the contract in docs/sandbox.md."""

    domains: list[str] = []
    credentials: list[str] = []
    oauth: list[str] = []
    store_path: str | None = None


# A host name, or `*.` plus a name of at least two labels. A bare `*` would open the proxy to everything,
# and `*.com` almost as much.
_DECLARABLE_DOMAIN = re.compile(r"\*\.[a-z0-9-]+(\.[a-z0-9-]+)+|[a-z0-9-]+(\.[a-z0-9-]+)*")
# The caller's store path reaches the sentinel prompt, so it must not carry text of its own.
_STORE_PATH = re.compile(r"/nix/store/[0-9a-z]{32}-[^\s/]+")


@sandbox_app.post("/gate")
async def gate_request(request: Request, body: UpfrontRequestBody) -> Response:
    """Review what a command declares before its work (``cgate request``); one decision for all of it.

    Approved domains and credentials hold for the rest of the running exec. Credentials are approved as
    the password kind, the one generated wrappers fetch with ``ccred get``.
    """
    session_id = _authenticate_sandbox(request.headers.get("authorization"))
    if session_id is None:
        raise HTTPException(status_code=401, detail="Unauthorized")

    domains = sorted({domain.strip().lower() for domain in body.domains})
    if invalid := [domain for domain in domains if not _DECLARABLE_DOMAIN.fullmatch(domain)]:
        return Response(status_code=400, content=f"not a domain: {invalid[0]}", media_type="text/plain")
    if body.store_path is not None and not _STORE_PATH.fullmatch(body.store_path):
        return Response(status_code=400, content="not a Nix store path", media_type="text/plain")
    vault_paths = sorted(set(body.credentials))
    token_paths = sorted(set(body.oauth))
    if not domains and not vault_paths and not token_paths:
        return Response(status_code=400, content="nothing requested", media_type="text/plain")

    try:
        credential_registry = await _credential_registry_for_session(session_id)
    except KeyError:
        raise HTTPException(status_code=403, detail="Session owner is not configured") from None

    active = _engine.get_or_activate(session_id)
    sandbox_mgr = _engine.sandbox_mgr
    running = sandbox_mgr.running_exec(session_id)
    if running is None:
        return _boundary_denied(ORPHANED_REQUEST_REJECTION)
    effective_domains = sandbox_mgr.get_effective_domains(session_id)
    pending_domains = [domain for domain in domains if not domain_allowed(domain, effective_domains)]
    pending_paths = [path for path in vault_paths if (path, "password") not in running.credentials]
    pending_tokens = [path for path in token_paths if (path, "oauth_access_token") not in running.credentials]
    if not pending_domains and not pending_paths and not pending_tokens:
        return Response(status_code=200)

    metadata: dict[str, CredentialMetadata] = {}
    for path in sorted({*pending_paths, *pending_tokens}):
        try:
            metadata[path] = await credential_registry.fetch_metadata(path)
        except KeyError:
            return Response(status_code=404, content=f"credential not found: {path}", media_type="text/plain")
        except CredentialBackendError as exc:
            return _credential_backend_unavailable(exc)
    credentials = [metadata[path] for path in pending_paths]
    access_tokens = [metadata[path] for path in pending_tokens]
    if active.security is None or active.sentinel is None:
        return _boundary_denied("Session not initialized")

    with _engine.llm_request_recording(active):
        try:
            evaluation = await evaluate_upfront_request_with(
                active.security,
                active.sentinel,
                UpfrontRequest(
                    domains=pending_domains,
                    credentials=credentials,
                    access_tokens=access_tokens,
                    store_path=body.store_path,
                ),
                running.command,
                follow_up=running.boundary_reviewed,
                usage_tracker=active.usage_tracker,
                assert_llm_budget_available=lambda: _engine._assert_llm_budget_available(active),
                usage_limits=_engine._remaining_aux_usage_limits(active),
            )
        except (SessionBudgetExceededError, UsageLimitExceeded) as exc:
            return _boundary_denied(str(exc))
    if not sandbox_mgr.is_running(running):
        return _boundary_denied(EXEC_ENDED_REJECTION)
    running.boundary_reviewed = True
    if not evaluation.allowed:
        return _boundary_denied(evaluation.rejection)
    running.domains.update(pending_domains)
    running.credentials.update((path, "password") for path in pending_paths)
    running.credentials.update((path, "oauth_access_token") for path in pending_tokens)
    return Response(status_code=200)


@sandbox_app.get("/credentials/{vault_path:path}")
async def fetch_credential(
    request: Request,
    vault_path: str,
    kind: CredentialValueKind = "password",
) -> Response:
    """Fetch a credential value (sentinel-gated, may escalate to user).

    Fast path: the default password/value may use an active skill context.
    """
    session_id = _authenticate_sandbox(request.headers.get("authorization"))
    if session_id is None:
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        credential_registry = await _credential_registry_for_session(session_id)
    except KeyError:
        raise HTTPException(status_code=403, detail="Session owner is not configured") from None

    try:
        meta = await credential_registry.fetch_metadata(vault_path)
        credential_registry.require_supported(vault_path, kind)
    except KeyError:
        return Response(status_code=404, content="Credential not found")
    except UnsupportedCredentialValueKindError as exc:
        return Response(status_code=400, content=str(exc), media_type="text/plain")
    except CredentialBackendError as exc:
        return _credential_backend_unavailable(exc)

    active = _engine.get_or_activate(session_id)

    # Context fast path: check if the credential is covered by active contexts
    current_contexts = _engine.sandbox_mgr.get_current_contexts(session_id)
    skill_covered = False
    if kind == "password" and current_contexts:
        grants = active.state.context_grants
        for ctx_name in current_contexts:
            grant = grants.get(ctx_name)
            if grant is not None and vault_path in grant.vault_paths:
                skill_covered = True
                break

    if skill_covered:
        # Allowed by skill context — must still record; same bar as the sentinel path
        if active.security is None:
            return Response(status_code=403, content="Session not initialized")
        explanation = "skill-declared credential under active context"
        active.security.record_credential_access(
            vault_paths=[vault_path],
            names=[meta.name],
            decision="approved",
            explanation=explanation,
            ui_label=f"[skill] {meta.name}",
            approval_source="skill",
            approval_verdict="allow",
            audit_final="auto_allowed",
            audit_args={
                "operation": "fetch",
                "vault_path": vault_path,
                "value_kind": kind,
                "source": "skill_context",
            },
        )
    else:
        denial = await _gate_credential_request(
            active,
            (vault_path, kind),
            lambda security, sentinel, command, follow_up: evaluate_credential_with(
                security,
                sentinel,
                vault_path,
                meta.name,
                meta.description,
                f"`ccred get` ({kind})",
                command,
                follow_up=follow_up,
                usage_tracker=active.usage_tracker,
                assert_llm_budget_available=lambda: _engine._assert_llm_budget_available(active),
                usage_limits=_engine._remaining_aux_usage_limits(active),
                audit_args={"operation": "fetch", "vault_path": vault_path, "value_kind": kind},
            ),
        )
        if denial is not None:
            return denial

    try:
        # After the review, so a denial reads nothing from the vault.
        value = await fetch_for_sandbox(credential_registry, vault_path, kind)
    except KeyError:
        return Response(status_code=404, content="Credential not found")
    except (UnsupportedCredentialValueKindError, OAuthStateRefusedError) as exc:
        return Response(status_code=400, content=str(exc), media_type="text/plain")
    except CredentialBackendError as exc:
        return _credential_backend_unavailable(exc)

    return Response(content=value, media_type="application/json" if kind == "json" else "text/plain")


# A forced refresh mints a new token at the provider; the bridge needs one after a 401, a loop would need many.
_SECOND_REFRESH_REJECTION = (
    "Denied: this exec already refreshed this access token once. A new exec asks again, with its own review."
)


@sandbox_app.get("/oauth-token/{vault_path:path}")
async def fetch_oauth_access_token(request: Request, vault_path: str, refresh: bool = False) -> Response:
    """A short-lived access token from an OAuth vault entry (``ccred get --access-token``).

    Carapace refreshes the entry; its refresh token never leaves the server. Reviewed like a credential and
    granted for the rest of the exec. *refresh* forces a new token, once per exec and entry.
    """
    session_id = _authenticate_sandbox(request.headers.get("authorization"))
    if session_id is None:
        raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        credential_registry = await _credential_registry_for_session(session_id)
    except KeyError:
        raise HTTPException(status_code=403, detail="Session owner is not configured") from None
    try:
        meta = await credential_registry.fetch_metadata(vault_path)
    except KeyError:
        return Response(status_code=404, content="Credential not found")
    except CredentialBackendError as exc:
        return _credential_backend_unavailable(exc)

    active = _engine.get_or_activate(session_id)
    audit_args = {"operation": "fetch", "vault_path": vault_path, "value_kind": "oauth_access_token"}
    denial = await _gate_credential_request(
        active,
        (vault_path, "oauth_access_token"),
        lambda security, sentinel, command, follow_up: evaluate_credential_with(
            security,
            sentinel,
            vault_path,
            meta.name,
            meta.description,
            "`ccred get --access-token` (short-lived OAuth access token; the refresh token stays with Carapace)",
            command,
            follow_up=follow_up,
            usage_tracker=active.usage_tracker,
            assert_llm_budget_available=lambda: _engine._assert_llm_budget_available(active),
            usage_limits=_engine._remaining_aux_usage_limits(active),
            audit_args=audit_args,
        ),
    )
    if denial is not None:
        return denial
    if refresh:
        running = _engine.sandbox_mgr.running_exec(session_id)
        if running is None:
            return _boundary_denied(EXEC_ENDED_REJECTION)
        if vault_path in running.oauth_refreshed:
            return _boundary_denied(_SECOND_REFRESH_REJECTION)
        running.oauth_refreshed.add(vault_path)

    try:
        token = await oauth_access_token(credential_registry, vault_path, refresh=refresh)
    except NotOAuthStateError as exc:
        return Response(status_code=400, content=str(exc), media_type="text/plain")
    except CredentialBackendError as exc:
        return _credential_backend_unavailable(exc)
    return Response(content=token, media_type="text/plain")


if __name__ == "__main__":
    main()
