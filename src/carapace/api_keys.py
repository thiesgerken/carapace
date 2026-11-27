from __future__ import annotations

import hashlib
import secrets
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from enum import StrEnum

from loguru import logger
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError

from .auth import AuthStore, UserIdentity, has_admin_role, normalize_username
from .database.engine import SessionFactory, affected_rows
from .database.models import ApiKeyRow

# Non-secret lookup handle prefix; the full token is "<prefix>.<body>".
_TOKEN_PREFIX = "ck_"
# Skip rewriting last_used_at if it was already touched this recently (write contention).
_LAST_USED_COALESCE_SECONDS = 60


class Scope(StrEnum):
    sessions = "sessions"
    jobs = "jobs"
    preferences = "preferences"
    notifications = "notifications"
    history = "history"
    knowledge = "knowledge"
    admin = "admin"


class Access(StrEnum):
    read = "read"
    write = "write"


class ApiKeyGrant(BaseModel, frozen=True):
    scope: Scope
    access: Access

    def satisfies(self, scope: Scope, access: Access) -> bool:
        if self.scope != scope:
            return False
        return self.access is Access.write or access is Access.read

    def to_str(self) -> str:
        return f"{self.scope.value}:{self.access.value}"

    @classmethod
    def parse(cls, raw: str) -> ApiKeyGrant:
        scope_part, _, access_part = raw.partition(":")
        return cls(scope=Scope(scope_part), access=Access(access_part or "read"))


class ApiKeyInfo(BaseModel):
    """Safe-to-expose view of an API key (never carries the secret or its hash)."""

    id: str
    name: str
    prefix: str
    scopes: list[str]
    created_at: datetime
    last_used_at: datetime | None = None
    expires_at: datetime | None = None
    revoked_at: datetime | None = None

    def is_active(self, *, now: datetime | None = None) -> bool:
        current = now or datetime.now(tz=UTC)
        if self.revoked_at is not None:
            return False
        return self.expires_at is None or self.expires_at > current


class ApiKeyStore:
    def __init__(self, session_factory: SessionFactory, auth_store: AuthStore):
        self._session_factory = session_factory
        self._auth = auth_store

    def create_key(
        self,
        *,
        user: str,
        name: str,
        grants: Iterable[ApiKeyGrant],
        expires_at: datetime | None = None,
    ) -> tuple[ApiKeyInfo, str]:
        """Create a key and return its info plus the plaintext token (shown once)."""
        key_user = normalize_username(user)
        owner = self._auth.get_user(key_user)
        if owner is None:
            raise ValueError(f"User {key_user!r} not found")
        grant_set = _normalize_grants(grants)
        if not grant_set:
            raise ValueError("at least one scope is required")
        if any(g.scope is Scope.admin for g in grant_set) and not has_admin_role(owner.roles):
            raise ValueError("admin scope requires the admin role")

        now = datetime.now(tz=UTC)
        prefix = _TOKEN_PREFIX + secrets.token_hex(4)
        full = f"{prefix}.{secrets.token_urlsafe(32)}"
        row = ApiKeyRow(
            id=uuid.uuid4().hex,
            prefix=prefix,
            secret_hash=_hash(full),
            user=key_user,
            name=name.strip(),
            scopes=sorted(g.to_str() for g in grant_set),
            created_at=now,
            last_used_at=None,
            expires_at=expires_at,
            revoked_at=None,
        )
        with self._session_factory.begin() as db:
            db.add(row)
        return _row_to_info(row), full

    def list_keys(self, user: str) -> list[ApiKeyInfo]:
        key_user = normalize_username(user)
        with self._session_factory() as db:
            rows = db.scalars(
                select(ApiKeyRow)
                .where(ApiKeyRow.user == key_user, ApiKeyRow.revoked_at.is_(None))
                .order_by(ApiKeyRow.created_at.desc())
            ).all()
        # Reflect effective grants: admin scopes don't apply once the owner loses the admin role
        # (validate_key strips them too), so don't list them as active.
        owner = self._auth.get_user(key_user)
        keep_admin = owner is not None and has_admin_role(owner.roles)
        return [_row_to_info(row, keep_admin=keep_admin) for row in rows]

    def revoke_key(self, *, user: str, key_id: str) -> bool:
        key_user = normalize_username(user)
        with self._session_factory.begin() as db:
            result = db.execute(
                update(ApiKeyRow)
                .where(ApiKeyRow.id == key_id, ApiKeyRow.user == key_user, ApiKeyRow.revoked_at.is_(None))
                .values(revoked_at=datetime.now(tz=UTC))
            )
            return affected_rows(result) > 0

    def validate_key(self, full_token: str) -> tuple[UserIdentity, set[ApiKeyGrant]] | None:
        """Resolve a plaintext token to its owner identity and effective grants."""
        prefix, sep, _ = full_token.partition(".")
        if not sep or not prefix:
            return None
        now = datetime.now(tz=UTC)
        with self._session_factory() as db:
            row = db.scalar(select(ApiKeyRow).where(ApiKeyRow.prefix == prefix))
            if row is None:
                _hash(full_token)  # keep timing roughly constant whether or not the prefix exists
                return None
            stored_hash = row.secret_hash
            row_id = row.id
            key_user = row.user
            stored_scopes = list(row.scopes)
            revoked_at = row.revoked_at
            expires_at = row.expires_at
            last_used_at = row.last_used_at

        if revoked_at is not None:
            return None
        if expires_at is not None and expires_at <= now:
            return None
        if not secrets.compare_digest(stored_hash, _hash(full_token)):
            return None

        # Key acts as its owner: dies when the user is disabled or deleted. token_version is
        # intentionally ignored so keys survive password changes.
        owner = self._auth.get_user(key_user)
        if owner is None or not owner.enabled:
            return None

        grants = {ApiKeyGrant.parse(scope) for scope in stored_scopes}
        if not has_admin_role(owner.roles):
            grants = {grant for grant in grants if grant.scope is not Scope.admin}

        self._touch_last_used(row_id, last_used_at, now)
        return owner.identity(key_user), grants

    def _touch_last_used(self, key_id: str, last_used_at: datetime | None, now: datetime) -> None:
        if last_used_at is not None and (now - last_used_at).total_seconds() < _LAST_USED_COALESCE_SECONDS:
            return
        # Best-effort, separate transaction, blind UPDATE — never fail the request on a touch error.
        try:
            with self._session_factory.begin() as db:
                db.execute(update(ApiKeyRow).where(ApiKeyRow.id == key_id).values(last_used_at=now))
        except SQLAlchemyError as exc:
            logger.debug(f"api key last_used_at touch failed for {key_id}: {exc}")


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _normalize_grants(grants: Iterable[ApiKeyGrant]) -> set[ApiKeyGrant]:
    """Collapse to one grant per scope, preferring write (which implies read)."""
    by_scope: dict[Scope, Access] = {}
    for grant in grants:
        current = by_scope.get(grant.scope)
        if current is None or grant.access is Access.write:
            by_scope[grant.scope] = grant.access
    return {ApiKeyGrant(scope=scope, access=access) for scope, access in by_scope.items()}


def _row_to_info(row: ApiKeyRow, *, keep_admin: bool = True) -> ApiKeyInfo:
    scopes = list(row.scopes) if keep_admin else [s for s in row.scopes if not s.startswith(f"{Scope.admin.value}:")]
    return ApiKeyInfo(
        id=row.id,
        name=row.name,
        prefix=row.prefix,
        scopes=scopes,
        created_at=row.created_at,
        last_used_at=row.last_used_at,
        expires_at=row.expires_at,
        revoked_at=row.revoked_at,
    )
