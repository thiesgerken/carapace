from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel
from pydantic_ai import ModelMessage, ModelMessagesTypeAdapter
from sqlalchemy import JSON, DateTime, TypeDecorator
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


# JSON column type that maps to JSONB on PostgreSQL and JSON/TEXT elsewhere (SQLite).
# Used for free-form dict/list payloads that aren't a single Pydantic model.
JsonType = JSON().with_variant(postgresql.JSONB(), "postgresql")


class _JsonBacked(TypeDecorator):
    """Base for JSON-backed columns: JSONB on PostgreSQL, JSON/TEXT on SQLite."""

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect: Any) -> Any:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(postgresql.JSONB())
        return dialect.type_descriptor(JSON())


class PydanticJson[ModelT: BaseModel](_JsonBacked):
    """A JSON column that (de)serializes a specific Pydantic model.

    The column annotation reads ``Mapped[SomeModel]`` and callers store/read the
    model directly — serialization to/from the JSON payload happens here.
    """

    cache_ok = True

    def __init__(self, model: type[ModelT]) -> None:
        self.model = model
        super().__init__()

    def process_bind_param(self, value: ModelT | None, dialect: Any) -> Any:
        # Computed fields derive from the stored ones; storing them would only let them go stale.
        return None if value is None else value.model_dump(mode="json", exclude_computed_fields=True)

    def process_result_value(self, value: Any, dialect: Any) -> ModelT | None:
        return None if value is None else self.model.model_validate(value)


class ModelMessagesJson(_JsonBacked):
    """A JSON column holding a pydantic-ai ``list[ModelMessage]`` conversation history."""

    cache_ok = True

    def process_bind_param(self, value: list[ModelMessage] | None, dialect: Any) -> Any:
        return None if value is None else ModelMessagesTypeAdapter.dump_python(value, mode="json")

    def process_result_value(self, value: Any, dialect: Any) -> list[ModelMessage]:
        return [] if not value else ModelMessagesTypeAdapter.validate_python(value)


class UtcDateTime(TypeDecorator):
    """Timezone-aware datetime stored as UTC.

    PostgreSQL keeps tz info; SQLite drops it. This decorator normalizes every
    value to UTC on the way in and re-attaches UTC on the way out so callers
    always receive tz-aware datetimes regardless of backend.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if not isinstance(value, datetime):
            raise TypeError(f"expected datetime, got {type(value)!r}")
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
