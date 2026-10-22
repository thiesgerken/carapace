from __future__ import annotations

import secrets
from datetime import UTC, datetime

from pydantic import BaseModel
from sqlalchemy import select

from .database.engine import SessionFactory
from .database.models import ArtifactRow


class ArtifactShare(BaseModel):
    owner: str
    slug: str
    share_token: str | None
    shared_at: datetime | None


class ArtifactShareStore:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def get(self, owner: str, slug: str) -> ArtifactShare | None:
        with self._session_factory() as db:
            row = db.get(ArtifactRow, (owner, slug))
            return ArtifactShare.model_validate(row, from_attributes=True) if row is not None else None

    def enable(self, owner: str, slug: str) -> ArtifactShare:
        with self._session_factory.begin() as db:
            row = db.get(ArtifactRow, (owner, slug))
            if row is None:
                row = ArtifactRow(owner=owner, slug=slug)
                db.add(row)
            row.share_token = secrets.token_urlsafe(32)
            row.shared_at = datetime.now(tz=UTC)
            return ArtifactShare.model_validate(row, from_attributes=True)

    def disable(self, owner: str, slug: str) -> None:
        with self._session_factory.begin() as db:
            row = db.get(ArtifactRow, (owner, slug))
            if row is not None:
                row.share_token = None
                row.shared_at = None

    def resolve(self, token: str) -> ArtifactShare | None:
        with self._session_factory() as db:
            row = db.scalar(select(ArtifactRow).where(ArtifactRow.share_token == token))
            return ArtifactShare.model_validate(row, from_attributes=True) if row is not None else None

    def shared_slugs(self, owner: str) -> set[str]:
        with self._session_factory() as db:
            return set(
                db.scalars(
                    select(ArtifactRow.slug).where(ArtifactRow.owner == owner, ArtifactRow.share_token.is_not(None))
                )
            )
