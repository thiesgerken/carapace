from __future__ import annotations

from sqlalchemy import delete, select

from .database.engine import SessionFactory
from .database.models import ModelRow, PlatformSettingRow
from .models.config import (
    AgentConfig,
    AvailableModelEntry,
    Config,
    SessionsConfig,
    model_entry_to_dict,
)

# Scalar agent fields persisted under the platform_settings 'agent' row (everything except
# available_models, which lives in its own table).
_AGENT_SCALAR_FIELDS = (
    "model",
    "sentinel_model",
    "title_model",
    "compaction_model",
    "memory_low_model",
    "memory_high_model",
    "compaction",
    "default_session_budget",
    "max_parallel_llm",
    "max_sentinel_calls_per_tool_call",
    "sentinel_domain_batch_window_ms",
    "sentinel_timeout_seconds",
    "tool_output_max_chars",
)


def _model_to_row(entry: AvailableModelEntry) -> ModelRow:
    return ModelRow(
        id=entry.model_id,
        provider=entry.provider,
        name=entry.name,
        data=model_entry_to_dict(entry),
    )


def _dedup_models(entries: list[AvailableModelEntry]) -> list[AvailableModelEntry]:
    """Collapse duplicate ``model_id`` rows (last wins) so they map to a unique PK in ``models``.

    Mirrors ``agent_available_model_entries`` — a config listing the same id twice stays valid.
    """
    by_id: dict[str, AvailableModelEntry] = {}
    for entry in entries:
        by_id[entry.model_id] = entry
    return list(by_id.values())


def _agent_scalars(agent: AgentConfig) -> dict[str, object]:
    return agent.model_dump(mode="json", include=set(_AGENT_SCALAR_FIELDS))


class PlatformSettingsStore:
    """DB-backed runtime platform config (model catalog + scalar agent/sessions settings).

    The in-memory ``Config`` stays the single read surface for the app; this store is the
    *source* (startup overlay) and the *write path* for the admin "platform settings" UI.
    """

    def __init__(self, session_factory: SessionFactory):
        self._session_factory = session_factory

    # --- models table ---

    def load_models(self) -> list[AvailableModelEntry]:
        with self._session_factory() as db:
            rows = db.scalars(select(ModelRow).order_by(ModelRow.id)).all()
        return [AvailableModelEntry.model_validate(row.data) for row in rows]

    def replace_models(self, entries: list[AvailableModelEntry]) -> None:
        """Wholesale replace the catalog (delete-all + insert) in one transaction."""
        with self._session_factory.begin() as db:
            db.execute(delete(ModelRow))
            db.add_all(_model_to_row(entry) for entry in _dedup_models(entries))

    def save_agent_config(self, agent: AgentConfig) -> None:
        """Persist the full agent config: replace the model catalog + scalar 'agent' row in one txn."""
        with self._session_factory.begin() as db:
            db.execute(delete(ModelRow))
            db.add_all(_model_to_row(entry) for entry in _dedup_models(agent.available_models))
            db.merge(PlatformSettingRow(key="agent", data=_agent_scalars(agent)))

    # --- platform_settings table ---

    def load_section(self, key: str) -> dict[str, object] | None:
        with self._session_factory() as db:
            row = db.get(PlatformSettingRow, key)
            return dict(row.data) if row is not None else None

    def save_section(self, key: str, data: dict[str, object]) -> None:
        with self._session_factory.begin() as db:
            db.merge(PlatformSettingRow(key=key, data=data))

    # --- assembly / overlay ---

    def assemble_agent_config(self, file_agent: AgentConfig) -> AgentConfig:
        """Build an AgentConfig from DB models + DB scalars, falling back to *file_agent* per field.

        ``AgentConfig.model_validate`` re-runs ``_defaults_listed_in_available_models``, so a
        stray default/model mismatch surfaces here.
        """
        models = self.load_models()
        scalars = self.load_section("agent") or {}
        base = file_agent.model_dump(mode="json")
        for field in _AGENT_SCALAR_FIELDS:
            if field in scalars:
                base[field] = scalars[field]
        source = models if models else file_agent.available_models
        base["available_models"] = [model_entry_to_dict(e) for e in source]
        return AgentConfig.model_validate(base)

    def assemble_sessions_config(self, file_sessions: SessionsConfig) -> SessionsConfig:
        data = self.load_section("sessions")
        return SessionsConfig.model_validate(data) if data is not None else file_sessions

    def overlay_config(self, config: Config) -> Config:
        """Return a Config copy with ``agent`` and ``sessions`` sourced from the DB."""
        return config.model_copy(
            update={
                "agent": self.assemble_agent_config(config.agent),
                "sessions": self.assemble_sessions_config(config.sessions),
            }
        )
