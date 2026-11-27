from __future__ import annotations

import os
import secrets
import string
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import RLock
from typing import Any

from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import OctKey
from loguru import logger
from pwdlib import PasswordHash
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import delete, select, update

from .database.engine import SessionFactory, affected_rows
from .database.models import AuthSessionRow, User
from .models.config import AuthConfig
from .models.user import UserConfig
from .usernames import normalize_username

_password_hash = PasswordHash.recommended()
ADMIN_ROLE = "admin"
ADMIN_USERNAME = "admin"
BOOTSTRAP_ADMIN_PASSWORD_MIN_LENGTH = 16
BOOTSTRAP_ADMIN_PASSWORD_SUGGESTED_LENGTH = 24
_BOOTSTRAP_ADMIN_PASSWORD_ALPHABET = string.ascii_letters + string.digits


class UserIdentity(BaseModel):
    username: str
    display_name: str = ""
    email: str | None = None
    roles: list[str] = []
    config: UserConfig = UserConfig()


class AuthUser(BaseModel):
    password_hash: str
    enabled: bool = True
    token_version: int = 1
    display_name: str = ""
    email: str | None = None
    roles: list[str] = []
    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))
    password_changed_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))
    last_login_at: datetime | None = None
    config: UserConfig = UserConfig()

    @model_validator(mode="after")
    def _normalize(self) -> AuthUser:
        self.display_name = self.display_name.strip()
        self.email = self.email.strip() or None if self.email is not None else None
        self.roles = normalize_roles(self.roles)
        if self.token_version < 1:
            raise ValueError("token_version must be >= 1")
        return self

    def identity(self, username: str) -> UserIdentity:
        return UserIdentity(
            username=username,
            display_name=self.display_name or username,
            email=self.email,
            roles=list(self.roles),
            config=self.config.model_copy(deep=True),
        )


class UsersFile(BaseModel):
    version: int = 1
    users: dict[str, AuthUser] = {}

    @model_validator(mode="after")
    def _normalize(self) -> UsersFile:
        normalized: dict[str, AuthUser] = {}
        for username, user in self.users.items():
            key = normalize_username(username)
            if key in normalized:
                raise ValueError(f"duplicate username after normalization: {username!r}")
            normalized[key] = user
        self.users = normalized
        return self


class AuthSession(BaseModel):
    id: str
    user: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))
    expires_at: datetime
    revoked_at: datetime | None = None
    user_agent: str = ""

    @model_validator(mode="after")
    def _normalize(self) -> AuthSession:
        self.id = self.id.strip()
        if not self.id:
            raise ValueError("session id must not be empty")
        self.user = normalize_username(self.user)
        if self.expires_at <= self.created_at:
            raise ValueError("session expires_at must be after created_at")
        return self

    def is_active(self, *, now: datetime | None = None) -> bool:
        current = now or datetime.now(tz=UTC)
        return self.revoked_at is None and self.expires_at > current


class SessionsFile(BaseModel):
    version: int = 1
    sessions: dict[str, AuthSession] = {}


class SessionTokenClaims(BaseModel):
    iss: str
    aud: str
    typ: str
    sub: str
    sid: str
    iat: int
    exp: int
    ver: int


def _user_to_row(username: str, user: AuthUser) -> User:
    return User(
        username=username,
        password_hash=user.password_hash,
        enabled=user.enabled,
        token_version=user.token_version,
        display_name=user.display_name,
        email=user.email,
        roles=list(user.roles),
        config=user.config,
        created_at=user.created_at,
        updated_at=user.updated_at,
        password_changed_at=user.password_changed_at,
        last_login_at=user.last_login_at,
    )


def _row_to_user(row: User) -> AuthUser:
    return AuthUser.model_validate(
        {
            "password_hash": row.password_hash,
            "enabled": row.enabled,
            "token_version": row.token_version,
            "display_name": row.display_name,
            "email": row.email,
            "roles": list(row.roles),
            "config": row.config,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            "password_changed_at": row.password_changed_at,
            "last_login_at": row.last_login_at,
        }
    )


def _session_to_row(session: AuthSession) -> AuthSessionRow:
    return AuthSessionRow(
        id=session.id,
        user=session.user,
        created_at=session.created_at,
        expires_at=session.expires_at,
        revoked_at=session.revoked_at,
        user_agent=session.user_agent,
    )


def _row_to_session(row: AuthSessionRow) -> AuthSession:
    return AuthSession(
        id=row.id,
        user=row.user,
        created_at=row.created_at,
        expires_at=row.expires_at,
        revoked_at=row.revoked_at,
        user_agent=row.user_agent,
    )


class AuthStore:
    def __init__(self, session_factory: SessionFactory, config: AuthConfig, data_dir: Path):
        self._session_factory = session_factory
        self._dir = data_dir / "auth"
        self._secret_path = self._dir / "session_secret"
        self._config = config
        self._lock = RLock()
        self._cached_signing_secret: str | None = None
        self._cached_signing_key: OctKey | None = None
        self._dir.mkdir(parents=True, exist_ok=True)

    def load_users(self) -> UsersFile:
        with self._session_factory() as db:
            rows = db.scalars(select(User)).all()
        return UsersFile(users={row.username: _row_to_user(row) for row in rows})

    def save_users(self, users_file: UsersFile) -> UsersFile:
        """Replace the full user set (bulk operations)."""
        with self._session_factory.begin() as db:
            db.execute(delete(User))
            db.add_all(_user_to_row(username, user) for username, user in users_file.users.items())
        return users_file

    def get_user(self, username: str) -> AuthUser | None:
        with self._session_factory() as db:
            row = db.get(User, normalize_username(username))
            return _row_to_user(row) if row is not None else None

    def ensure_bootstrap_admin(self) -> AuthUser | None:
        now = datetime.now(tz=UTC)
        with self._lock, self._session_factory.begin() as db:
            rows = db.scalars(select(User)).all()
            if any(row.enabled and has_admin_role(list(row.roles)) for row in rows):
                return None

            password = validate_bootstrap_admin_password()
            existing = db.get(User, ADMIN_USERNAME)
            if existing is None:
                user = AuthUser(
                    password_hash=hash_password(password),
                    display_name="Administrator",
                    roles=[ADMIN_ROLE],
                    created_at=now,
                    updated_at=now,
                    password_changed_at=now,
                )
            else:
                payload = _row_to_user(existing).model_dump(mode="python")
                payload.update(
                    {
                        "password_hash": hash_password(password),
                        "enabled": True,
                        "display_name": existing.display_name or "Administrator",
                        "roles": normalize_roles([*existing.roles, ADMIN_ROLE]),
                        "token_version": existing.token_version + 1,
                        "updated_at": now,
                        "password_changed_at": now,
                    }
                )
                user = AuthUser.model_validate(payload)
            db.merge(_user_to_row(ADMIN_USERNAME, user))
            return user

    def create_user(
        self,
        *,
        username: str,
        password: str,
        display_name: str = "",
        email: str | None = None,
        roles: list[str] | None = None,
        config: UserConfig | None = None,
    ) -> AuthUser:
        key = normalize_username(username)
        if not key:
            raise ValueError("username must not be empty")
        now = datetime.now(tz=UTC)
        user = AuthUser(
            password_hash=hash_password(password),
            display_name=display_name or key,
            email=email,
            roles=roles or [],
            created_at=now,
            updated_at=now,
            password_changed_at=now,
            config=config or UserConfig(),
        )
        with self._session_factory.begin() as db:
            if db.get(User, key) is not None:
                raise ValueError(f"User {key!r} already exists")
            db.add(_user_to_row(key, user))
        return user

    def update_user(self, username: str, updates: dict[str, Any]) -> AuthUser:
        key = normalize_username(username)
        with self._session_factory.begin() as db:
            existing = db.get(User, key)
            if existing is None:
                raise KeyError(key)
            payload = _row_to_user(existing).model_dump(mode="python")
            payload.update(updates)
            payload["updated_at"] = datetime.now(tz=UTC)
            updated = AuthUser.model_validate(payload)
            _apply_user_to_row(existing, updated)
        return updated

    def delete_user(self, username: str) -> None:
        key = normalize_username(username)
        now = datetime.now(tz=UTC)
        with self._session_factory.begin() as db:
            existing = db.get(User, key)
            if existing is None:
                raise KeyError(key)
            db.delete(existing)  # api_keys cascade-delete via their ON DELETE CASCADE FK
            db.execute(
                update(AuthSessionRow)
                .where(AuthSessionRow.user == key, AuthSessionRow.revoked_at.is_(None))
                .values(revoked_at=now)
            )

    def set_password(self, username: str, password: str) -> AuthUser:
        key = normalize_username(username)
        password_hash = hash_password(password)
        now = datetime.now(tz=UTC)
        with self._session_factory.begin() as db:
            existing = db.get(User, key)
            if existing is None:
                raise KeyError(key)
            payload = _row_to_user(existing).model_dump(mode="python")
            payload.update(
                {
                    "password_hash": password_hash,
                    "password_changed_at": now,
                    "token_version": existing.token_version + 1,
                    "updated_at": now,
                }
            )
            updated = AuthUser.model_validate(payload)
            _apply_user_to_row(existing, updated)
        return updated

    def verify_password(self, username: str, password: str) -> AuthUser | None:
        key = normalize_username(username)
        user = self.get_user(key)
        if user is None:
            logger.debug(f"login failed: unknown user {key!r}")
            return None
        if not user.enabled:
            logger.debug(f"login failed: user {key!r} is disabled")
            return None
        if not verify_password(password, user.password_hash):
            logger.debug(f"login failed: wrong password for user {key!r}")
            return None
        logger.debug(f"login succeeded for user {key!r}")
        return user

    def load_sessions(self) -> SessionsFile:
        with self._session_factory() as db:
            rows = db.scalars(select(AuthSessionRow)).all()
        return SessionsFile(sessions={row.id: _row_to_session(row) for row in rows})

    def save_sessions(self, sessions_file: SessionsFile) -> SessionsFile:
        """Replace the full session set (bulk operations)."""
        with self._session_factory.begin() as db:
            db.execute(delete(AuthSessionRow))
            db.add_all(_session_to_row(session) for session in sessions_file.sessions.values())
        return sessions_file

    def create_session(self, *, username: str, user_agent: str = "") -> AuthSession:
        key = normalize_username(username)
        now = datetime.now(tz=UTC)
        session = AuthSession(
            id=secrets.token_urlsafe(32),
            user=key,
            created_at=now,
            expires_at=now + timedelta(seconds=self._config.cookie.ttl_seconds),
            user_agent=user_agent,
        )
        with self._session_factory.begin() as db:
            user = db.get(User, key)
            if user is None or not user.enabled:
                raise ValueError("User not found or disabled")
            db.execute(delete(AuthSessionRow).where(AuthSessionRow.expires_at <= now))
            db.add(_session_to_row(session))
            user.last_login_at = now
            user.updated_at = now
        return session

    def get_session(self, session_id: str) -> AuthSession | None:
        with self._session_factory() as db:
            row = db.get(AuthSessionRow, session_id)
            return _row_to_session(row) if row is not None else None

    def revoke_session(self, session_id: str) -> bool:
        with self._session_factory.begin() as db:
            result = db.execute(
                update(AuthSessionRow).where(AuthSessionRow.id == session_id).values(revoked_at=datetime.now(tz=UTC))
            )
            return affected_rows(result) > 0

    def revoke_user_sessions(self, username: str) -> int:
        key = normalize_username(username)
        now = datetime.now(tz=UTC)
        with self._session_factory.begin() as db:
            result = db.execute(
                update(AuthSessionRow)
                .where(AuthSessionRow.user == key, AuthSessionRow.revoked_at.is_(None))
                .values(revoked_at=now)
            )
            return affected_rows(result)

    def prune_sessions(self, *, now: datetime | None = None) -> int:
        current = now or datetime.now(tz=UTC)
        with self._session_factory.begin() as db:
            result = db.execute(delete(AuthSessionRow).where(AuthSessionRow.expires_at <= current))
            return affected_rows(result)

    def signing_secret(self) -> str:
        with self._lock:
            if self._cached_signing_secret is not None:
                return self._cached_signing_secret
            if self._secret_path.exists():
                self._cached_signing_secret = self._secret_path.read_text(encoding="utf-8").strip()
                return self._cached_signing_secret
            secret = secrets.token_urlsafe(48)
            self._secret_path.write_text(secret, encoding="utf-8")
            self._secret_path.chmod(0o600)
            self._cached_signing_secret = secret
            return secret

    def issue_session_token(self, session: AuthSession) -> str:
        user = self.get_user(session.user)
        if user is None:
            raise ValueError("User not found")
        claims = {
            "iss": self._config.cookie.issuer,
            "aud": self._config.cookie.audience,
            "typ": "session",
            "sub": session.user,
            "sid": session.id,
            "iat": int(session.created_at.timestamp()),
            "exp": int(session.expires_at.timestamp()),
            "ver": user.token_version,
        }
        return jwt.encode({"alg": "HS256"}, claims, self._signing_key())

    def issue_websocket_token(self, session_token: str) -> str | None:
        session_claims = self._decode_token_claims(session_token, expected_type="session")
        if session_claims is None:
            return None
        if self._identity_from_claims(session_claims) is None:
            return None

        now = datetime.now(tz=UTC)
        try:
            user = self.get_user(session_claims.sub)
        except ValueError:
            return None
        if user is None:
            return None
        claims = {
            "iss": self._config.cookie.issuer,
            "aud": self._config.cookie.audience,
            "typ": "websocket",
            "sub": session_claims.sub,
            "sid": session_claims.sid,
            "iat": int(now.timestamp()),
            "exp": session_claims.exp,
            "ver": user.token_version,
        }
        return jwt.encode({"alg": "HS256"}, claims, self._signing_key())

    def validate_session_token(self, token: str) -> UserIdentity | None:
        claims = self._decode_token_claims(token, expected_type="session")
        if claims is None:
            return None

        return self._identity_from_claims(claims)

    def validate_websocket_token(self, token: str) -> UserIdentity | None:
        claims = self._decode_token_claims(token, expected_type="websocket")
        if claims is None:
            return None
        return self._identity_from_claims(claims)

    def _identity_from_claims(self, claims: SessionTokenClaims) -> UserIdentity | None:
        now = datetime.now(tz=UTC)
        if datetime.fromtimestamp(claims.exp, tz=UTC) <= now:
            return None

        try:
            normalized_subject = normalize_username(claims.sub)
        except ValueError:
            return None

        session = self.get_session(claims.sid)
        if session is None or not session.is_active(now=now) or session.user != normalized_subject:
            return None
        user = self.get_user(session.user)
        if user is None or not user.enabled or user.token_version != claims.ver:
            return None
        return user.identity(session.user)

    def revoke_token(self, token: str) -> bool:
        claims = self._decode_token_claims(token, expected_type="session")
        if claims is None:
            return False
        return self.revoke_session(claims.sid)

    def _decode_token_claims(self, token: str, *, expected_type: str) -> SessionTokenClaims | None:
        try:
            token_obj = jwt.decode(token, self._signing_key(), algorithms=["HS256"])
            claims = SessionTokenClaims.model_validate(token_obj.claims)
        except (JoseError, ValueError):
            return None
        if claims.iss != self._config.cookie.issuer:
            return None
        if claims.aud != self._config.cookie.audience:
            return None
        if claims.typ != expected_type:
            return None
        return claims

    def _signing_key(self) -> OctKey:
        with self._lock:
            if self._cached_signing_key is None:
                self._cached_signing_key = OctKey.import_key(self.signing_secret())
            return self._cached_signing_key


def _apply_user_to_row(row: User, user: AuthUser) -> None:
    row.password_hash = user.password_hash
    row.enabled = user.enabled
    row.token_version = user.token_version
    row.display_name = user.display_name
    row.email = user.email
    row.roles = list(user.roles)
    row.config = user.config
    row.created_at = user.created_at
    row.updated_at = user.updated_at
    row.password_changed_at = user.password_changed_at
    row.last_login_at = user.last_login_at


def normalize_roles(roles: list[str]) -> list[str]:
    return [role.strip().lower() for role in roles if role.strip()]


def has_admin_role(roles: list[str]) -> bool:
    return ADMIN_ROLE in normalize_roles(roles)


def hash_password(password: str) -> str:
    if not password:
        raise ValueError("password must not be empty")
    return _password_hash.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    if not password or not password_hash:
        return False
    return _password_hash.verify(password, password_hash)


def suggest_bootstrap_admin_password() -> str:
    return "".join(
        secrets.choice(_BOOTSTRAP_ADMIN_PASSWORD_ALPHABET) for _ in range(BOOTSTRAP_ADMIN_PASSWORD_SUGGESTED_LENGTH)
    )


def validate_bootstrap_admin_password(password: str | None = None) -> str:
    """Return a validated bootstrap admin password or raise with a replacement suggestion."""
    if password is None:
        password = os.environ.get("CARAPACE_TOKEN", "")
    password = password.strip()
    if not password:
        raise RuntimeError("CARAPACE_TOKEN environment variable is required but not set")
    if len(password) < BOOTSTRAP_ADMIN_PASSWORD_MIN_LENGTH:
        raise RuntimeError(
            "CARAPACE_TOKEN must be at least "
            f"{BOOTSTRAP_ADMIN_PASSWORD_MIN_LENGTH} characters long. "
            f"Suggested replacement: {suggest_bootstrap_admin_password()}"
        )
    return password
