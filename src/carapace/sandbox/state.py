from __future__ import annotations

from loguru import logger
from sqlalchemy import func, select

from ..database.engine import SessionFactory
from ..database.models import SessionRow
from .snapshot import SessionSandboxSnapshot

__all__ = [
    "SessionSandboxSnapshot",
    "clear_sandbox_snapshot",
    "count_owned_sessions",
    "load_sandbox_snapshot",
    "save_sandbox_snapshot",
    "session_owner",
]


def load_sandbox_snapshot(session_factory: SessionFactory, session_id: str) -> SessionSandboxSnapshot | None:
    with session_factory() as db:
        row = db.get(SessionRow, session_id)
        return row.sandbox_snapshot if row is not None else None


def save_sandbox_snapshot(session_factory: SessionFactory, session_id: str, snapshot: SessionSandboxSnapshot) -> None:
    with session_factory.begin() as db:
        row = db.get(SessionRow, session_id)
        if row is None:
            logger.warning(f"Cannot persist sandbox snapshot: session {session_id} not found")
            return
        row.sandbox_snapshot = snapshot


def clear_sandbox_snapshot(session_factory: SessionFactory, session_id: str) -> None:
    with session_factory.begin() as db:
        row = db.get(SessionRow, session_id)
        if row is not None:
            row.sandbox_snapshot = None


def session_owner(session_factory: SessionFactory, session_id: str) -> str:
    with session_factory() as db:
        user = db.scalar(select(SessionRow.user).where(SessionRow.session_id == session_id))
    if not user:
        raise LookupError(f"Session {session_id} has no owner")
    return user


def count_owned_sessions(session_factory: SessionFactory, user: str, session_ids: set[str]) -> int:
    """Count how many of *session_ids* belong to *user*; ids without a session row are ignored."""
    if not session_ids:
        return 0
    stmt = (
        select(func.count())
        .select_from(SessionRow)
        .where(SessionRow.user == user, SessionRow.session_id.in_(session_ids))
    )
    with session_factory() as db:
        return db.scalar(stmt) or 0
