from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

import yaml
from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from ..api_keys import Access, Scope
from ..auth import AuthStore, UserIdentity, normalize_username
from ..credentials.registry import file_credential_backend_allowed_from_env
from ..memory.models import ModelRole
from ..models.credentials import (
    BitwardenCredentialBackendConfig,
    CredentialsConfig,
    FileCredentialBackendConfig,
)
from ..models.matrix import MatrixChannelConfig, MatrixTokensFile
from ..models.session import SessionBudget
from ..models.user import UserConfig, UserDefaultModelsConfig, UserGitConfig, UserMemoryConfig, validate_timezone
from ..user_defaults import effective_memory_model
from .auth import require
from .state import server_module

server = server_module()
router = APIRouter()


@dataclass(frozen=True)
class MatrixTokenFileBackup:
    path: Path
    content: str | None

    def restore(self) -> None:
        if self.content is None:
            self.path.unlink(missing_ok=True)
            return
        self.path.write_text(self.content, encoding="utf-8")


class SettingsModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# Code points that extend the preceding emoji rather than starting a new one: zero-width
# joiner, the variation selectors, the keycap mark and the skin tone modifiers.
_EMOJI_ZWJ = 0x200D
_EMOJI_EXTENDERS = frozenset({_EMOJI_ZWJ, 0xFE0E, 0xFE0F, 0x20E3}) | frozenset(range(0x1F3FB, 0x1F400))
# Flags are a pair of regional indicators, so the second one continues the first.
_EMOJI_REGIONAL = frozenset(range(0x1F1E6, 0x1F200))
# Long enough for the deepest sequences (a four-person family with skin tones), short
# enough that padding the value with joiners cannot grow it without bound.
MAX_AGENT_ICON_LENGTH = 16


def _emoji_count(value: str) -> int:
    """Number of separate emoji in a string, counting a ZWJ sequence or flag as one."""
    count = 0
    joined = False
    after_regional = False
    for char in value:
        code = ord(char)
        if code in _EMOJI_EXTENDERS:
            joined = code == _EMOJI_ZWJ
            after_regional = False
            continue
        if joined:
            joined = False
            after_regional = False
            continue
        if after_regional and code in _EMOJI_REGIONAL:
            after_regional = False
            continue
        after_regional = code in _EMOJI_REGIONAL
        count += 1
    return count


class UserSettingsCapabilities(SettingsModel):
    file_credential_backend: bool = False


class ServerDefaultModels(SettingsModel):
    agent: str
    sentinel: str
    title: str
    # Effective platform defaults, fallbacks already applied.
    memory_low: str
    memory_high: str


class ServerDefaults(SettingsModel):
    models: ServerDefaultModels
    budget: SessionBudget


class PublicBasicAuth(SettingsModel):
    username: str
    password_set: bool = False


class PublicFileCredentialBackend(SettingsModel):
    type: str = "file"
    path: str = ""
    expose: list[str] = []
    hide: list[str] = []


class PublicBitwardenCredentialBackend(SettingsModel):
    type: str = "bitwarden"
    url: str
    basic_auth: PublicBasicAuth | None = None
    expose: list[str] = []
    hide: list[str] = []


class PublicCredentialsSettings(SettingsModel):
    backends: dict[str, PublicFileCredentialBackend | PublicBitwardenCredentialBackend] = {}


class PublicMatrixSettings(SettingsModel):
    enabled: bool
    homeserver: str
    user_id: str
    device_name: str
    password_set: bool = False
    token_set: bool = False
    allowed_rooms: list[str] = []
    allowed_users: list[str] = []


class PublicGitSettings(SettingsModel):
    remote: str
    branch: str
    author: str
    token_set: bool = False


class PublicUserSettings(SettingsModel):
    agent_name: str = ""
    agent_icon: str = ""
    default_models: UserDefaultModelsConfig
    default_budget: SessionBudget
    timezone: str
    memory: UserMemoryConfig
    matrix: PublicMatrixSettings
    credentials: PublicCredentialsSettings
    git: PublicGitSettings


class UserSettingsResponse(SettingsModel):
    capabilities: UserSettingsCapabilities
    server_defaults: ServerDefaults
    available_models: list[dict[str, Any]]
    settings: PublicUserSettings


class MatrixSettingsPatch(SettingsModel):
    enabled: bool | None = None
    homeserver: str | None = None
    user_id: str | None = None
    device_name: str | None = None
    password: str | None = None
    clear_password: bool = False
    token: str | None = None
    clear_token: bool = False
    allowed_rooms: list[str] | None = None
    allowed_users: list[str] | None = None

    @field_validator("homeserver", "user_id", "device_name", "password", "token", mode="before")
    @classmethod
    def _normalize_string(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("allowed_rooms", "allowed_users", mode="before")
    @classmethod
    def _normalize_string_list(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return [item.strip() for item in value if item.strip()]


class GitSettingsPatch(SettingsModel):
    remote: str | None = None
    branch: str | None = None
    author: str | None = None
    token: str | None = None
    clear_token: bool = False

    @field_validator("remote", "branch", "author", "token", mode="before")
    @classmethod
    def _normalize_string(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class UserSettingsPatch(SettingsModel):
    agent_name: str | None = None
    agent_icon: str | None = None

    @field_validator("agent_icon", mode="after")
    @classmethod
    def _validate_agent_icon(cls, value: str | None) -> str | None:
        if value is None:
            return None
        icon = value.strip()
        # Rendered as a single icon, so text or several emoji would be stored only to be
        # silently replaced by the default. Whether the emoji is one the frontend bundles
        # an asset for is not checked here: that table lives with the frontend, and
        # mirroring it server-side would mean keeping the two in sync forever.
        if icon and (icon.isascii() or len(icon) > MAX_AGENT_ICON_LENGTH or _emoji_count(icon) != 1):
            raise ValueError(
                f"agent_icon must be a single non-ASCII symbol of at most {MAX_AGENT_ICON_LENGTH} code points"
            )
        return icon

    default_models: UserDefaultModelsConfig | None = None
    default_budget: SessionBudget | None = None
    timezone: str | None = None
    memory: UserMemoryConfig | None = None
    matrix: MatrixSettingsPatch | None = None

    @field_validator("timezone", mode="after")
    @classmethod
    def _validate_timezone(cls, value: str | None) -> str | None:
        return None if value is None else validate_timezone(value)

    credentials: CredentialsConfig | None = None
    git: GitSettingsPatch | None = None

    @model_validator(mode="after")
    def _validate_nonempty_patch(self) -> UserSettingsPatch:
        if not self.model_fields_set:
            raise ValueError("settings patch must not be empty")
        return self


def _auth_store() -> AuthStore:
    store = getattr(server, "_auth_store", None)
    if isinstance(store, AuthStore):
        return store
    raise HTTPException(status_code=503, detail="Auth store is not initialized")


def _file_backend_allowed() -> bool:
    try:
        return file_credential_backend_allowed_from_env()
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def _capabilities() -> UserSettingsCapabilities:
    return UserSettingsCapabilities(
        file_credential_backend=_file_backend_allowed(),
    )


def _public_credentials(config: CredentialsConfig) -> PublicCredentialsSettings:
    backends: dict[str, PublicFileCredentialBackend | PublicBitwardenCredentialBackend] = {}
    for name, backend in config.backends.items():
        if isinstance(backend, FileCredentialBackendConfig):
            backends[name] = PublicFileCredentialBackend(
                path=backend.path,
                expose=list(backend.expose),
                hide=list(backend.hide),
            )
            continue
        basic_auth = None
        if backend.basic_auth is not None:
            basic_auth = PublicBasicAuth(
                username=backend.basic_auth.username,
                password_set=backend.basic_auth.password is not None,
            )
        backends[name] = PublicBitwardenCredentialBackend(
            url=backend.url,
            basic_auth=basic_auth,
            expose=list(backend.expose),
            hide=list(backend.hide),
        )
    return PublicCredentialsSettings(backends=backends)


def _public_matrix(config: MatrixChannelConfig) -> PublicMatrixSettings:
    return PublicMatrixSettings(
        enabled=config.enabled,
        homeserver=config.homeserver,
        user_id=config.user_id,
        device_name=config.device_name,
        password_set=config.password is not None,
        token_set=config.token is not None,
        allowed_rooms=list(config.allowed_rooms),
        allowed_users=list(config.allowed_users),
    )


def _public_git(config: UserGitConfig) -> PublicGitSettings:
    return PublicGitSettings(
        remote=config.remote,
        branch=config.branch,
        author=config.author,
        token_set=config.token is not None,
    )


def _matrix_token_path() -> Path | None:
    engine = getattr(server, "_engine", None)
    session_mgr = getattr(engine, "session_mgr", None)
    sessions_dir = getattr(session_mgr, "sessions_dir", None)
    if not isinstance(sessions_dir, Path):
        return None
    return sessions_dir.parent / "matrix_token.yaml"


def _matrix_password_replaces_token(patch: MatrixSettingsPatch | None) -> bool:
    if patch is None:
        return False
    return "password" in patch.model_fields_set and patch.password is not None


def _clear_persisted_matrix_token(username: str, config: UserConfig) -> MatrixTokenFileBackup | None:
    token_path = _matrix_token_path()
    if token_path is None or not token_path.exists():
        return None

    raw_content = token_path.read_text(encoding="utf-8")
    try:
        tokens_file = MatrixTokensFile.model_validate(yaml.safe_load(raw_content) or {})
    except Exception as exc:
        logger.warning(f"Matrix: could not update persisted token file before password login: {exc}")
        return None

    normalized_username = normalize_username(username)
    matrix_user_id = config.channels.matrix.user_id or None
    remaining = []
    removed = False
    for stored in tokens_file.tokens:
        owner_matches = normalize_username(stored.user) == normalized_username
        user_id_matches = stored.user_id is None or stored.user_id == matrix_user_id
        if owner_matches and user_id_matches:
            removed = True
            continue
        remaining.append(stored)

    if not removed:
        return None

    backup = MatrixTokenFileBackup(path=token_path, content=raw_content)
    if remaining:
        token_path.write_text(
            yaml.safe_dump(MatrixTokensFile(tokens=remaining).model_dump(mode="json", exclude_none=True)),
            encoding="utf-8",
        )
    else:
        token_path.unlink(missing_ok=True)
    return backup


def _available_model_ids() -> set[str]:
    return {entry.model_id for entry in server._engine.enabled_model_entries}


def _validate_default_models(default_models: UserDefaultModelsConfig) -> None:
    available = _available_model_ids()
    for field_name in ("agent", "sentinel", "title", "memory_low", "memory_high"):
        model_id = getattr(default_models, field_name)
        if model_id is None:
            continue
        if model_id not in available:
            raise HTTPException(status_code=400, detail=f"Unknown {field_name} model: {model_id}")


def _assert_credentials_supported(existing: CredentialsConfig, credentials: CredentialsConfig) -> None:
    if _file_backend_allowed():
        return
    for name, backend in credentials.backends.items():
        existing_backend = existing.backends.get(name)
        unchanged_file_backend = (
            isinstance(existing_backend, FileCredentialBackendConfig) and existing_backend == backend
        )
        if isinstance(backend, FileCredentialBackendConfig) and not unchanged_file_backend:
            raise HTTPException(
                status_code=400,
                detail=f"File credential backend {name!r} is disabled on this server",
            )


def _credentials_with_preserved_backend_passwords(username: str, credentials: CredentialsConfig) -> CredentialsConfig:
    merged = credentials.model_copy(deep=True)
    existing_user = _auth_store().get_user(username)
    existing_credentials = existing_user.config.credentials if existing_user is not None else CredentialsConfig()

    for backend_name, backend in merged.backends.items():
        if not isinstance(backend, BitwardenCredentialBackendConfig) or backend.basic_auth is None:
            continue
        if backend.basic_auth.password is not None:
            continue
        existing_backend = existing_credentials.backends.get(backend_name)
        if isinstance(existing_backend, BitwardenCredentialBackendConfig) and existing_backend.basic_auth is not None:
            backend.basic_auth.password = existing_backend.basic_auth.password
        if backend.basic_auth.password is None:
            raise HTTPException(
                status_code=400,
                detail=f"basic_auth.password is required for credential backend {backend_name!r}",
            )
    return merged


async def _invalidate_user_credential_registry(username: str) -> None:
    registries = getattr(server, "_user_credential_registries", None)
    if not isinstance(registries, dict):
        return
    cached = registries.pop(normalize_username(username), None)
    if cached is None:
        return
    _, registry = cached
    await registry.close()


async def _reload_matrix_settings(username: str, config: UserConfig) -> None:
    manager = getattr(server, "_matrix_channel_manager", None)
    if manager is None:
        raise HTTPException(status_code=503, detail="Matrix runtime is not initialized")
    try:
        await manager.reload_user(username, config)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(f"Matrix settings reload failed for user {username!r}")
        raise HTTPException(status_code=500, detail=f"Matrix settings reload failed: {exc}") from exc


async def _reload_git_settings(username: str, config: UserGitConfig) -> None:
    runtime = getattr(server, "_knowledge_git_runtime", None)
    if runtime is None:
        raise HTTPException(status_code=503, detail="Git runtime is not initialized")
    try:
        await runtime.apply_user_config(username, config)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Knowledge Git settings reload failed")
        raise HTTPException(status_code=500, detail=f"Git settings reload failed: {exc}") from exc


async def _rollback_settings_runtime(
    username: str,
    config: UserConfig,
    *,
    matrix_changed: bool,
    git_changed: bool,
) -> None:
    if matrix_changed:
        try:
            await _reload_matrix_settings(username, config)
        except HTTPException as exc:
            logger.warning(f"Matrix settings runtime rollback failed for user {username!r}: {exc.detail}")
    if git_changed:
        try:
            await _reload_git_settings(username, config.git)
        except HTTPException as exc:
            logger.warning(f"Git settings runtime rollback failed: {exc.detail}")


def _settings_response(username: str) -> UserSettingsResponse:
    user = _auth_store().get_user(username)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    config = user.config
    return UserSettingsResponse(
        capabilities=_capabilities(),
        server_defaults=ServerDefaults(
            models=ServerDefaultModels(
                agent=server._config.agent.model,
                sentinel=server._config.agent.sentinel_model,
                title=server._config.agent.title_model,
                memory_low=effective_memory_model(server._config, UserConfig(), ModelRole.memory_low),
                memory_high=effective_memory_model(server._config, UserConfig(), ModelRole.memory_high),
            ),
            budget=server._config.agent.default_session_budget,
        ),
        available_models=[
            entry.model_dump(mode="json", by_alias=True) for entry in server._engine.enabled_model_entries
        ],
        settings=PublicUserSettings(
            agent_name=config.agent_name,
            agent_icon=config.agent_icon,
            default_models=config.default_models,
            default_budget=config.budgets,
            timezone=config.timezone,
            memory=config.memory,
            matrix=_public_matrix(config.channels.matrix),
            credentials=_public_credentials(config.credentials),
            git=_public_git(config.git),
        ),
    )


def _apply_matrix_patch(config: UserConfig, patch: MatrixSettingsPatch) -> None:
    matrix = config.channels.matrix.model_copy(deep=True)
    fields = patch.model_fields_set
    if "enabled" in fields and patch.enabled is not None:
        matrix.enabled = patch.enabled
    if "homeserver" in fields:
        matrix.homeserver = patch.homeserver or ""
    if "user_id" in fields:
        matrix.user_id = patch.user_id or ""
    if "device_name" in fields:
        matrix.device_name = patch.device_name or "carapace"
    if patch.clear_password:
        matrix.password = None
    elif "password" in fields:
        matrix.password = patch.password
    if patch.clear_token:
        matrix.token = None
    elif "token" in fields:
        matrix.token = patch.token
    if "allowed_rooms" in fields:
        matrix.allowed_rooms = patch.allowed_rooms or []
    if "allowed_users" in fields:
        matrix.allowed_users = patch.allowed_users or []
    config.channels.matrix = MatrixChannelConfig.model_validate(matrix.model_dump(mode="python"))


def _apply_git_patch(config: UserConfig, patch: GitSettingsPatch) -> None:
    git = config.git.model_copy(deep=True)
    fields = patch.model_fields_set
    if "remote" in fields:
        git.remote = patch.remote or ""
    if "branch" in fields:
        git.branch = patch.branch or "main"
    if "author" in fields:
        git.author = patch.author or "carapace <carapace@%h>"
    if patch.clear_token:
        git.token = None
    elif "token" in fields:
        git.token = patch.token
    config.git = UserGitConfig.model_validate(git.model_dump(mode="python"))


@router.get("/user/settings", response_model=UserSettingsResponse)
async def get_user_settings(
    user: Annotated[UserIdentity, Depends(require(Scope.preferences, Access.read))],
) -> UserSettingsResponse:
    return _settings_response(user.username)


@router.patch("/user/settings", response_model=UserSettingsResponse)
async def update_user_settings(
    body: UserSettingsPatch,
    user: Annotated[UserIdentity, Depends(require(Scope.preferences, Access.write))],
) -> UserSettingsResponse:
    stored_user = _auth_store().get_user(user.username)
    if stored_user is None:
        raise HTTPException(status_code=404, detail="User not found")

    original_config = stored_user.config
    next_config = original_config.model_copy(deep=True)

    if "agent_name" in body.model_fields_set:
        next_config.agent_name = (body.agent_name or "").strip()

    if "agent_icon" in body.model_fields_set:
        next_config.agent_icon = (body.agent_icon or "").strip()

    if "default_models" in body.model_fields_set:
        next_config.default_models = body.default_models or UserDefaultModelsConfig()
        _validate_default_models(next_config.default_models)

    if "default_budget" in body.model_fields_set:
        next_config.budgets = body.default_budget or SessionBudget()

    if body.timezone is not None:
        next_config.timezone = body.timezone

    if "memory" in body.model_fields_set:
        next_config.memory = body.memory or UserMemoryConfig()

    if body.matrix is not None:
        _apply_matrix_patch(next_config, body.matrix)

    if "credentials" in body.model_fields_set:
        credentials = body.credentials or CredentialsConfig()
        _assert_credentials_supported(original_config.credentials, credentials)
        next_config.credentials = _credentials_with_preserved_backend_passwords(user.username, credentials)

    if body.git is not None:
        _apply_git_patch(next_config, body.git)

    credentials_changed = original_config.credentials != next_config.credentials
    matrix_defaults_changed = (
        original_config.default_models != next_config.default_models or original_config.budgets != next_config.budgets
    )
    matrix_changed = original_config.channels.matrix != next_config.channels.matrix or (
        next_config.channels.matrix.enabled and matrix_defaults_changed
    )
    git_changed = original_config.git != next_config.git

    runtime_errors: list[HTTPException] = []
    matrix_token_backup = (
        _clear_persisted_matrix_token(user.username, next_config)
        if _matrix_password_replaces_token(body.matrix)
        else None
    )
    if matrix_changed:
        try:
            await _reload_matrix_settings(user.username, next_config)
        except HTTPException as exc:
            runtime_errors.append(exc)
    if git_changed:
        try:
            await _reload_git_settings(user.username, next_config.git)
        except HTTPException as exc:
            runtime_errors.append(exc)

    if runtime_errors:
        if matrix_token_backup is not None:
            matrix_token_backup.restore()
        await _rollback_settings_runtime(
            user.username,
            original_config,
            matrix_changed=matrix_changed,
            git_changed=git_changed,
        )
        detail = "; ".join(error.detail for error in runtime_errors)
        raise HTTPException(status_code=runtime_errors[0].status_code, detail=detail)

    try:
        _auth_store().update_user(user.username, {"config": next_config})
    except ValueError as exc:
        if matrix_token_backup is not None:
            matrix_token_backup.restore()
        await _rollback_settings_runtime(
            user.username,
            original_config,
            matrix_changed=matrix_changed,
            git_changed=git_changed,
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if credentials_changed:
        await _invalidate_user_credential_registry(user.username)

    return _settings_response(user.username)
