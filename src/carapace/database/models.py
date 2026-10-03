from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..models.compaction import SessionCompaction
from ..models.jobs import JobDefinition
from ..models.session import SessionState
from ..models.user import UserConfig
from ..notifications.models import NotificationSubscription
from ..sandbox.snapshot import SessionSandboxSnapshot
from ..usage import LlmRequestLog, UsageTracker
from .base import Base, JsonType, ModelMessagesJson, PydanticJson, UtcDateTime

# SQLite only autoincrements an "INTEGER PRIMARY KEY" rowid alias; a BIGINT primary key
# does not autoincrement there. Use a 64-bit type on real databases, plain INTEGER on SQLite.
AutoBigInt = BigInteger().with_variant(Integer(), "sqlite")


class User(Base):
    __tablename__ = "users"

    username: Mapped[str] = mapped_column(String(256), primary_key=True)
    password_hash: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    token_version: Mapped[int] = mapped_column(Integer, default=1)
    display_name: Mapped[str] = mapped_column(Text, default="")
    email: Mapped[str | None] = mapped_column(Text, nullable=True)
    roles: Mapped[list[str]] = mapped_column(JsonType, default=list)
    # Full per-user settings (credentials, channels, git, default models, budgets).
    config: Mapped[UserConfig] = mapped_column(PydanticJson(UserConfig))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime)
    password_changed_at: Mapped[datetime] = mapped_column(UtcDateTime)
    last_login_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)


class AuthSessionRow(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[str] = mapped_column(String(256), primary_key=True)
    user: Mapped[str] = mapped_column(String(256), index=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    user_agent: Mapped[str] = mapped_column(Text, default="")


class JobRow(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(256), primary_key=True)
    user: Mapped[str] = mapped_column(String(256), index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    name: Mapped[str] = mapped_column(Text)
    prompt: Mapped[str] = mapped_column(Text)
    # Full job definition (triggers, modes, model overrides); id/user/enabled/name/prompt
    # above are queryable projections kept in sync on write.
    data: Mapped[JobDefinition] = mapped_column(PydanticJson(JobDefinition))


class NotificationSubscriptionRow(Base):
    __tablename__ = "notification_subscriptions"

    id: Mapped[str] = mapped_column(String(256), primary_key=True)
    user: Mapped[str] = mapped_column(String(256), index=True)
    endpoint: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime, index=True)
    # Full subscription (keys, prefs, device, timestamps); columns above are the index.
    data: Mapped[NotificationSubscription] = mapped_column(PydanticJson(NotificationSubscription))

    __table_args__ = (UniqueConstraint("user", "endpoint", name="uq_subscription_user_endpoint"),)


class SessionRow(Base):
    __tablename__ = "sessions"

    session_id: Mapped[str] = mapped_column(String(256), primary_key=True)
    user: Mapped[str] = mapped_column(String(256), index=True)
    channel_type: Mapped[str] = mapped_column(String(64), index=True)
    channel_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)
    last_active: Mapped[datetime] = mapped_column(UtcDateTime, index=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    favorite: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    # Full session state (attributes, budget, model names, context grants, knowledge
    # bookkeeping); the scalar columns above are queryable projections kept in sync on write.
    # Nullable only for the rare owner-before-state placeholder (see SessionManager.save_meta).
    state: Mapped[SessionState | None] = mapped_column(PydanticJson(SessionState), nullable=True)
    # Latest sandbox/container status snapshot for this session (UI display).
    sandbox_snapshot: Mapped[SessionSandboxSnapshot | None] = mapped_column(
        PydanticJson(SessionSandboxSnapshot), nullable=True
    )

    __table_args__ = (Index("ix_sessions_channel", "channel_type", "channel_ref"),)


class SessionHistoryRow(Base):
    __tablename__ = "session_history"

    session_id: Mapped[str] = mapped_column(
        String(256), ForeignKey("sessions.session_id", ondelete="CASCADE"), primary_key=True
    )
    # pydantic-ai conversation history, read/written as a whole.
    messages: Mapped[list[Any]] = mapped_column(ModelMessagesJson, default=list)


class SessionEventRow(Base):
    __tablename__ = "session_events"

    id: Mapped[int] = mapped_column(AutoBigInt, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        String(256), ForeignKey("sessions.session_id", ondelete="CASCADE"), index=True
    )
    seq: Mapped[int] = mapped_column(Integer)
    timestamp: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    # Heterogeneous UI/display event payload (slash commands, tool calls, approvals, ...).
    data: Mapped[dict[str, Any]] = mapped_column(JsonType)

    __table_args__ = (Index("ix_session_events_session_seq", "session_id", "seq"),)


class SessionUsageRow(Base):
    __tablename__ = "session_usage"

    session_id: Mapped[str] = mapped_column(
        String(256), ForeignKey("sessions.session_id", ondelete="CASCADE"), primary_key=True
    )
    tracker: Mapped[UsageTracker] = mapped_column(PydanticJson(UsageTracker))


class SessionLlmRequestRow(Base):
    __tablename__ = "session_llm_requests"

    session_id: Mapped[str] = mapped_column(
        String(256), ForeignKey("sessions.session_id", ondelete="CASCADE"), primary_key=True
    )
    log: Mapped[LlmRequestLog] = mapped_column(PydanticJson(LlmRequestLog))


class SessionCompactionRow(Base):
    __tablename__ = "session_compaction"

    session_id: Mapped[str] = mapped_column(
        String(256), ForeignKey("sessions.session_id", ondelete="CASCADE"), primary_key=True
    )
    # Compaction summary tree (folded-turn summaries + consolidation nodes).
    tree: Mapped[SessionCompaction] = mapped_column(PydanticJson(SessionCompaction))


class SessionAuditRow(Base):
    __tablename__ = "session_audit"

    id: Mapped[int] = mapped_column(AutoBigInt, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        String(256), ForeignKey("sessions.session_id", ondelete="CASCADE"), index=True
    )
    timestamp: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    # Security audit entry payload (AuditEntry dump; stored loosely for append-only logging).
    data: Mapped[dict[str, Any]] = mapped_column(JsonType)


class SandboxTokenRow(Base):
    __tablename__ = "sandbox_tokens"

    session_id: Mapped[str] = mapped_column(
        String(256), ForeignKey("sessions.session_id", ondelete="CASCADE"), primary_key=True
    )
    token: Mapped[str] = mapped_column(String(128), unique=True, index=True)


class ApiKeyRow(Base):
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # uuid4 hex
    prefix: Mapped[str] = mapped_column(String(16), unique=True, index=True)  # non-secret lookup handle
    secret_hash: Mapped[str] = mapped_column(String(128))  # sha256 hex of the full token
    # Owning user; ON DELETE CASCADE drops keys with their user so a reused username can't inherit them.
    user: Mapped[str] = mapped_column(String(256), ForeignKey("users.username", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(Text, default="")
    # Granted scopes as "scope:access" strings (e.g. "sessions:write", "jobs:read").
    scopes: Mapped[list[str]] = mapped_column(JsonType, default=list)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)
    last_used_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)


class UserCodexCredentialsRow(Base):
    """A user's ChatGPT subscription (OpenAI Codex) OAuth credentials.

    Its own table rather than part of ``User.config``: settings saves read-modify-write that blob
    and would clobber a refresh token rotated in between, and refresh tokens are single-use.
    """

    __tablename__ = "user_codex_credentials"

    user: Mapped[str] = mapped_column(String(256), ForeignKey("users.username", ondelete="CASCADE"), primary_key=True)
    access_token: Mapped[str] = mapped_column(Text)
    refresh_token: Mapped[str] = mapped_column(Text)
    account_id: Mapped[str] = mapped_column(Text)
    # Display only: the ChatGPT login is not guaranteed to carry an email claim.
    email: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime)


class ModelRow(Base):
    __tablename__ = "models"

    # PK is the model_id (id override or provider:name); provider/name are queryable projections.
    id: Mapped[str] = mapped_column(String(256), primary_key=True)
    provider: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[str] = mapped_column(Text)
    # Full AvailableModelEntry as a plain dict (model_entry_to_dict — keeps the excluded api_key).
    data: Mapped[dict[str, Any]] = mapped_column(JsonType)


class PlatformSettingRow(Base):
    __tablename__ = "platform_settings"

    # Section key ('agent' scalar settings, 'sessions' SessionsConfig dump).
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    data: Mapped[dict[str, Any]] = mapped_column(JsonType)
