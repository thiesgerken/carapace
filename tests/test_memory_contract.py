from __future__ import annotations

from datetime import UTC, datetime

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from pydantic import ValidationError
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from carapace.database.base import Base
from carapace.database.engine import create_engine_and_factory, run_migrations
from carapace.database.models import MemoryTaskRow, User
from carapace.memory.models import Fact, ModelRole, TaskSelection
from carapace.models.config import AgentConfig, AvailableModelEntry, Config, DatabaseConfig
from carapace.models.user import UserConfig
from carapace.user_defaults import effective_memory_model


def test_migrations_match_rows(tmp_path):
    engine, _ = create_engine_and_factory(DatabaseConfig(url=f"sqlite+pysqlite:///{tmp_path}/m.db"))
    run_migrations(engine)
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    engine.dispose()
    assert diff == []


def _task(status: str) -> MemoryTaskRow:
    return MemoryTaskRow(
        user="alice",
        kind="session_extract",
        target="s1",
        status=status,
        spawned_by="auto",
        attempts=0,
        created_at=datetime.now(tz=UTC),
    )


def test_one_open_task_per_target(db_factory):
    now = datetime.now(tz=UTC)
    with db_factory.begin() as db:
        db.add(
            User(
                username="alice",
                password_hash="x",
                config=UserConfig(),
                created_at=now,
                updated_at=now,
                password_changed_at=now,
            )
        )
        db.flush()
        db.add_all([_task("done"), _task("failed"), _task("pending")])

    with pytest.raises(IntegrityError), db_factory.begin() as db:
        db.add(_task("queued"))

    with db_factory.begin() as db:
        db.execute(update(MemoryTaskRow).where(MemoryTaskRow.status == "pending").values(status="cancelled"))
        db.add(_task("queued"))


def test_fact_provenance_rules():
    base = {"statement": "x", "source_seqs": [1], "confidence": "high", "durability": "durable"}
    Fact.model_validate(base | {"category": "surroundings", "source_kind": "observed"})
    Fact.model_validate(base | {"category": "social", "subject": "Anna", "source_kind": "user_said"})
    with pytest.raises(ValidationError, match="observed facts"):
        Fact.model_validate(base | {"category": "user", "source_kind": "observed"})
    with pytest.raises(ValidationError, match="subject"):
        Fact.model_validate(base | {"category": "social", "source_kind": "user_said"})


def test_task_selection_needs_ids_xor_filter():
    TaskSelection(ids=[1])
    TaskSelection(filter={}, newest=50)
    for bad in ({}, {"ids": [1], "filter": {}}, {"ids": [1], "newest": 5}):
        with pytest.raises(ValidationError):
            TaskSelection.model_validate(bad)


def test_user_timezone_validated():
    assert UserConfig().timezone == "Europe/Berlin"
    assert UserConfig(timezone=" UTC ").timezone == "UTC"
    for bad in ("Mars/Olympus", "", "../etc"):
        with pytest.raises(ValidationError, match="timezone"):
            UserConfig(timezone=bad)


def test_memory_model_fallbacks():
    models = [AvailableModelEntry(provider="test", name=n) for n in ("agent", "title", "compact", "low", "high")]
    agent = AgentConfig(
        model="test:agent", sentinel_model="test:title", title_model="test:title", available_models=models
    )
    config = Config(agent=agent)
    user = UserConfig()

    assert effective_memory_model(config, user, ModelRole.memory_low) == "test:title"
    assert effective_memory_model(config, user, ModelRole.memory_high) == "test:agent"

    agent.compaction_model = "test:compact"
    assert effective_memory_model(config, user, ModelRole.memory_low) == "test:compact"

    agent.memory_low_model, agent.memory_high_model = "test:low", "test:high"
    assert effective_memory_model(config, user, ModelRole.memory_low) == "test:low"
    assert effective_memory_model(config, user, ModelRole.memory_high) == "test:high"

    user.default_models.memory_low, user.default_models.memory_high = "test:agent", "test:title"
    assert effective_memory_model(config, user, ModelRole.memory_low) == "test:agent"
    assert effective_memory_model(config, user, ModelRole.memory_high) == "test:title"
