from __future__ import annotations

import secrets
import shutil
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any

import yaml
from loguru import logger
from pydantic import BaseModel, field_validator
from pydantic_ai import ModelMessage
from sqlalchemy import and_, case, delete, func, or_, select

from ..database.engine import SessionFactory
from ..database.models import (
    SandboxTokenRow,
    SessionAuditRow,
    SessionCompactionRow,
    SessionEventRow,
    SessionHistoryRow,
    SessionLlmRequestRow,
    SessionRow,
    SessionUsageRow,
)
from ..models.compaction import SessionCompaction
from ..models.session import SessionAttributes, SessionBudget, SessionState
from ..sandbox.state import SessionSandboxSnapshot
from ..usage import LlmRequestLog, LlmRequestState, UsageTracker
from ..usernames import normalize_username
from .open_approvals import ESCALATION_RESPONSE_FIELDS, TOOL_APPROVAL_REQUEST_ROLE, TOOL_APPROVAL_RESPONSE_ROLE


class SessionMeta(BaseModel):
    user: str

    @field_validator("user", mode="before")
    @classmethod
    def _normalize_user(cls, value: str) -> str:
        return normalize_username(value)


def _to_json_safe(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _to_json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set):
        return [_to_json_safe(item) for item in value]
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return repr(value)


def _timestamped_event(event: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    if event.get("timestamp"):
        return event
    stamped = dict(event)
    stamped["timestamp"] = (now or datetime.now(tz=UTC)).isoformat()
    return stamped


def _parse_timestamp(value: Any) -> datetime | None:
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _state_columns(state: SessionState) -> dict[str, Any]:
    return {
        "channel_type": state.channel_type,
        "channel_ref": state.channel_ref,
        "title": state.title,
        "created_at": state.created_at,
        "last_active": state.last_active,
        "archived": state.attributes.archived,
        "pinned": state.attributes.pinned,
        "favorite": state.attributes.favorite,
        "state": state,
    }


class SessionManager:
    def __init__(
        self,
        session_factory: SessionFactory,
        data_dir: Path,
        on_change: Callable[[], None] | None = None,
    ):
        self._session_factory = session_factory
        self.data_dir = data_dir
        # Per-session workspace dirs (used by the sandbox/git layer) still live on disk.
        self.sessions_dir = data_dir / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self._events_lock = RLock()
        self._on_change = on_change

    @property
    def session_factory(self) -> SessionFactory:
        return self._session_factory

    def create_session(
        self,
        channel_type: str = "cli",
        channel_ref: str = "",
        budget: SessionBudget | None = None,
        *,
        user: str,
        private: bool = False,
        unattended: bool = False,
        ask_mode: bool = False,
        yolo_mode: bool = False,
    ) -> SessionState:
        now = datetime.now(tz=UTC)
        session_id = f"{now:%Y-%m-%d-%H-%M}-{secrets.token_hex(4)}"
        state = SessionState(
            session_id=session_id,
            channel_type=channel_type,
            channel_ref=channel_ref or None,
            attributes=SessionAttributes(
                private=private,
                unattended=unattended,
                ask_mode=ask_mode,
                yolo_mode=yolo_mode,
            ),
            approved_operations=[],
            activated_skills=[],
            context_grants={},
            budget=budget.model_copy(deep=True) if budget is not None else SessionBudget(),
            created_at=now,
            last_active=now,
        )
        (self.sessions_dir / session_id).mkdir(parents=True, exist_ok=True)
        with self._session_factory.begin() as db:
            db.add(SessionRow(session_id=session_id, user=normalize_username(user), **_state_columns(state)))
        return state

    def load_meta(self, session_id: str) -> SessionMeta:
        with self._session_factory() as db:
            row = db.get(SessionRow, session_id)
            if row is None or not row.user:
                raise FileNotFoundError(f"Session {session_id} has no owner metadata")
            return SessionMeta(user=row.user)

    def save_meta(self, session_id: str, meta: SessionMeta) -> None:
        (self.sessions_dir / session_id).mkdir(parents=True, exist_ok=True)
        now = datetime.now(tz=UTC)
        with self._session_factory.begin() as db:
            row = db.get(SessionRow, session_id)
            if row is not None:
                row.user = meta.user
                return
            # No state persisted yet — create a placeholder row carrying just the owner.
            db.add(
                SessionRow(
                    session_id=session_id,
                    user=meta.user,
                    channel_type="cli",
                    channel_ref=None,
                    title=None,
                    created_at=now,
                    last_active=now,
                    archived=False,
                    pinned=False,
                    favorite=False,
                    state=None,
                )
            )

    def is_owned_by(self, session_id: str, user: str) -> bool:
        return self.load_meta(session_id).user == user

    def load_state(self, session_id: str) -> SessionState | None:
        with self._session_factory() as db:
            row = db.get(SessionRow, session_id)
            if row is None or row.state is None:
                return None
            return row.state

    def resume_session(self, session_id: str) -> SessionState | None:
        state = self.load_state(session_id)
        if state is not None:
            state.last_active = datetime.now(tz=UTC)
        return state

    def list_sessions(self, *, user: str | None = None) -> list[str]:
        stmt = select(SessionRow.session_id).order_by(SessionRow.last_active.desc())
        if user is not None:
            stmt = stmt.where(SessionRow.user == user)
        with self._session_factory() as db:
            return list(db.scalars(stmt).all())

    def find_session(self, channel_type: str, channel_ref: str) -> str | None:
        stmt = (
            select(SessionRow.session_id)
            .where(
                SessionRow.channel_type == channel_type,
                SessionRow.channel_ref == channel_ref,
            )
            .order_by(SessionRow.last_active.desc())
            .limit(1)
        )
        with self._session_factory() as db:
            return db.scalars(stmt).first()

    def find_sessions(self, channel_type: str, channel_ref: str) -> list[str]:
        stmt = (
            select(SessionRow.session_id)
            .where(
                SessionRow.channel_type == channel_type,
                SessionRow.channel_ref == channel_ref,
            )
            .order_by(SessionRow.last_active.desc())
        )
        with self._session_factory() as db:
            return list(db.scalars(stmt).all())

    def delete_session(self, session_id: str) -> bool:
        with self._session_factory.begin() as db:
            row = db.get(SessionRow, session_id)
            deleted = row is not None
            if row is not None:
                db.delete(row)  # FK cascade drops history/events/usage/llm/audit/token rows
        session_dir = self.sessions_dir / session_id
        if session_dir.exists():
            deleted = True
            try:
                shutil.rmtree(session_dir)
            except OSError as exc:
                # The DB row (source of truth) is already gone; a failed workspace
                # removal only leaves orphan files, which the sandbox orphan cleanup
                # sweeps. Don't fail the delete over it.
                logger.warning(f"Failed to remove workspace dir for session {session_id}: {exc}")
        if deleted:
            self._notify_change()
        return deleted

    def save_state(self, state: SessionState) -> None:
        self._save_state(state)

    def _save_state(self, state: SessionState) -> None:
        (self.sessions_dir / state.session_id).mkdir(parents=True, exist_ok=True)
        with self._session_factory.begin() as db:
            row = db.get(SessionRow, state.session_id)
            columns = _state_columns(state)
            if row is None:
                # Owner is set separately via save_meta (fork saves state first).
                db.add(SessionRow(session_id=state.session_id, user="", **columns))
            else:
                for key, value in columns.items():
                    setattr(row, key, value)
        self._notify_change()

    def _notify_change(self) -> None:
        if self._on_change is not None:
            self._on_change()

    def load_history(self, session_id: str) -> list[ModelMessage]:
        with self._session_factory() as db:
            row = db.get(SessionHistoryRow, session_id)
            return list(row.messages) if row is not None else []

    def save_history(self, session_id: str, messages: list[ModelMessage]) -> None:
        with self._session_factory.begin() as db:
            row = db.get(SessionHistoryRow, session_id)
            if row is None:
                db.add(SessionHistoryRow(session_id=session_id, messages=messages))
            else:
                row.messages = messages
        self._notify_change()

    # --- Usage tracking persistence ---

    def load_usage(self, session_id: str) -> UsageTracker:
        with self._session_factory() as db:
            row = db.get(SessionUsageRow, session_id)
            return row.tracker if row is not None else UsageTracker()

    def save_usage(self, session_id: str, tracker: UsageTracker) -> None:
        with self._session_factory.begin() as db:
            row = db.get(SessionUsageRow, session_id)
            if row is None:
                db.add(SessionUsageRow(session_id=session_id, tracker=tracker))
            else:
                row.tracker = tracker

    # --- Per-LLM-request log (API tokens + input-shape ratios) ---

    def load_llm_request_log(self, session_id: str) -> LlmRequestLog:
        with self._session_factory() as db:
            row = db.get(SessionLlmRequestRow, session_id)
            return row.log if row is not None else LlmRequestLog()

    def save_llm_request_log(self, session_id: str, log: LlmRequestLog) -> None:
        with self._session_factory.begin() as db:
            row = db.get(SessionLlmRequestRow, session_id)
            if row is None:
                db.add(SessionLlmRequestRow(session_id=session_id, log=log))
            else:
                row.log = log

    # --- Compaction summary tree ---

    def load_compaction(self, session_id: str) -> SessionCompaction:
        with self._session_factory() as db:
            row = db.get(SessionCompactionRow, session_id)
            return row.tree if row is not None else SessionCompaction()

    def save_compaction(self, session_id: str, tree: SessionCompaction) -> None:
        with self._session_factory.begin() as db:
            row = db.get(SessionCompactionRow, session_id)
            if row is None:
                db.add(SessionCompactionRow(session_id=session_id, tree=tree))
            else:
                row.tree = tree
        self._notify_change()

    # --- In-flight LLM request activity (transient — stays on disk) ---

    def load_llm_request_state(self, session_id: str) -> LlmRequestState | None:
        path = self.sessions_dir / session_id / "llm_activity.yaml"
        if not path.exists():
            return None
        with open(path) as f:
            raw = yaml.safe_load(f)
        if not raw:
            return None
        return LlmRequestState.model_validate(raw)

    def save_llm_request_state(self, session_id: str, state: LlmRequestState) -> None:
        session_dir = self.sessions_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        path = session_dir / "llm_activity.yaml"
        with open(path, "w") as f:
            yaml.dump(state.model_dump(mode="json"), f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    def clear_llm_request_state(self, session_id: str) -> None:
        path = self.sessions_dir / session_id / "llm_activity.yaml"
        path.unlink(missing_ok=True)

    # --- Sandbox snapshot persistence (column on the session row) ---

    def load_sandbox_snapshot(self, session_id: str) -> SessionSandboxSnapshot | None:
        with self._session_factory() as db:
            row = db.get(SessionRow, session_id)
            return row.sandbox_snapshot if row is not None else None

    def save_sandbox_snapshot(self, session_id: str, snapshot: SessionSandboxSnapshot) -> None:
        with self._session_factory.begin() as db:
            row = db.get(SessionRow, session_id)
            if row is None:
                raise FileNotFoundError(f"Session {session_id} not found")
            row.sandbox_snapshot = snapshot
        self._notify_change()

    def clear_sandbox_snapshot(self, session_id: str) -> None:
        with self._session_factory.begin() as db:
            row = db.get(SessionRow, session_id)
            if row is not None:
                row.sandbox_snapshot = None
        self._notify_change()

    # --- Event log (ordered display history including slash commands) ---
    #
    # Single-process assumption: all event writes are serialized by the in-process
    # ``_events_lock``. ``append_events`` allocates seq via ``MAX(seq)+1`` and
    # ``_rewrite_events`` does delete-all + reinsert; neither is safe across
    # processes. The deployment runs a single uvicorn process (chart replicas: 1,
    # no workers), so this holds. If we ever scale past one process/replica sharing
    # the DB, this breaks: add a UniqueConstraint(session_id, seq) + insert-on-
    # conflict retry, and replace the rewrite with a targeted update.

    def _load_events_unlocked(self, session_id: str) -> list[dict[str, Any]]:
        with self._session_factory() as db:
            rows = db.scalars(
                select(SessionEventRow).where(SessionEventRow.session_id == session_id).order_by(SessionEventRow.seq)
            ).all()
        return [dict(row.data) for row in rows]

    def load_events(self, session_id: str) -> list[dict[str, Any]]:
        with self._events_lock:
            return self._load_events_unlocked(session_id)

    def _next_seq(self, db: Any, session_id: str) -> int:
        current = db.scalar(select(func.max(SessionEventRow.seq)).where(SessionEventRow.session_id == session_id))
        return (current + 1) if current is not None else 0

    def _event_row(self, session_id: str, seq: int, event: dict[str, Any]) -> SessionEventRow:
        data = _to_json_safe(event)
        return SessionEventRow(
            session_id=session_id,
            seq=seq,
            timestamp=_parse_timestamp(data.get("timestamp")),
            data=data,
        )

    def append_events(self, session_id: str, events: list[dict[str, Any]]) -> None:
        ts = datetime.now(tz=UTC)
        with self._events_lock, self._session_factory.begin() as db:
            seq = self._next_seq(db, session_id)
            for event in events:
                db.add(self._event_row(session_id, seq, _timestamped_event(event, now=ts)))
                seq += 1
        self._notify_change()

    def _rewrite_events(self, session_id: str, events: list[dict[str, Any]]) -> None:
        with self._session_factory.begin() as db:
            db.execute(delete(SessionEventRow).where(SessionEventRow.session_id == session_id))
            for seq, event in enumerate(events):
                db.add(self._event_row(session_id, seq, event))

    def save_events(self, session_id: str, events: list[dict[str, Any]]) -> None:
        with self._events_lock:
            self._rewrite_events(session_id, events)
        self._notify_change()

    def update_events(
        self,
        session_id: str,
        updater: Callable[[list[dict[str, Any]]], Any],
    ) -> Any:
        with self._events_lock:
            events = self._load_events_unlocked(session_id)
            original_ids = {id(event) for event in events}
            result = updater(events)
            new_event_indexes = [index for index, event in enumerate(events) if id(event) not in original_ids]
            if new_event_indexes:
                ts = datetime.now(tz=UTC)
                for index in new_event_indexes:
                    events[index] = _timestamped_event(events[index], now=ts)
            self._rewrite_events(session_id, events)
            self._notify_change()
            return result

    def session_ids_with_open_approval_requests(self) -> list[str]:
        """Sessions that have more approval requests than responses in their event log.

        A cheap SQL prefilter so callers don't load every session's events; they still pair
        requests with responses on the loaded events to find the open ones.
        """
        role = SessionEventRow.data["role"].as_string()
        decided = SessionEventRow.data["decision"].as_string().is_not(None)
        escalation = role.in_(ESCALATION_RESPONSE_FIELDS)
        is_request = or_(role == TOOL_APPROVAL_REQUEST_ROLE, and_(escalation, ~decided))
        is_response = or_(role == TOOL_APPROVAL_RESPONSE_ROLE, and_(escalation, decided))
        stmt = (
            select(SessionEventRow.session_id)
            .where(or_(role.in_([TOOL_APPROVAL_REQUEST_ROLE, TOOL_APPROVAL_RESPONSE_ROLE]), escalation))
            .group_by(SessionEventRow.session_id)
            .having(func.sum(case((is_request, 1), else_=0)) > func.sum(case((is_response, 1), else_=0)))
        )
        with self._session_factory() as db:
            return list(db.scalars(stmt).all())

    # --- Audit log (append-only) ---

    def append_audit(self, session_id: str, entry: dict[str, Any]) -> None:
        data = _to_json_safe(entry)
        with self._session_factory.begin() as db:
            db.add(
                SessionAuditRow(
                    session_id=session_id,
                    timestamp=_parse_timestamp(data.get("timestamp")),
                    data=data,
                )
            )

    def load_audit(self, session_id: str) -> list[dict[str, Any]]:
        with self._session_factory() as db:
            rows = db.scalars(
                select(SessionAuditRow).where(SessionAuditRow.session_id == session_id).order_by(SessionAuditRow.id)
            ).all()
        return [dict(row.data) for row in rows]

    # --- Sandbox token persistence ---

    def get_sandbox_token(self, session_id: str) -> str | None:
        with self._session_factory() as db:
            row = db.get(SandboxTokenRow, session_id)
            return row.token if row is not None else None

    def session_id_for_sandbox_token(self, token: str) -> str | None:
        with self._session_factory() as db:
            row = db.scalars(select(SandboxTokenRow).where(SandboxTokenRow.token == token)).first()
            return row.session_id if row is not None else None

    def put_sandbox_token(self, session_id: str, token: str) -> None:
        with self._session_factory.begin() as db:
            row = db.get(SandboxTokenRow, session_id)
            if row is None:
                db.add(SandboxTokenRow(session_id=session_id, token=token))
            else:
                row.token = token
