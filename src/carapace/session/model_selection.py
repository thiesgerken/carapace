"""Model catalog and per-session model override helpers."""

from __future__ import annotations

import sys
from typing import Any, Literal, Protocol

from loguru import logger
from pydantic_ai.models import Model, infer_model
from pydantic_ai.settings import ModelSettings

from ..llm import DisabledModelError, ModelFactory, model_settings_for_config
from ..models.config import AvailableModelEntry, Config, agent_available_model_entries
from ..models.session import SessionState
from .manager import SessionManager
from .types import ActiveSession


class _UnsetType:
    pass


_UNSET = _UnsetType()

ModelType = Literal["agent", "sentinel", "title", "compaction"]


class SessionModelHost(Protocol):
    _active: dict[str, ActiveSession]
    _config: Config
    _session_mgr: SessionManager
    _model_factory: ModelFactory | None

    async def _generate_title(self, active: ActiveSession, events: list[dict[str, Any]]) -> str: ...


def _logger() -> Any:
    engine_module = sys.modules.get("carapace.session.engine")
    if engine_module is None:
        return logger
    return getattr(engine_module, "logger", logger)


class SessionModelMixin(SessionModelHost):
    _MODEL_TYPES: tuple[ModelType, ...] = ("agent", "sentinel", "title", "compaction")

    def _compaction_model_default(self) -> str:
        """Resolved platform default for the compaction model (falls back to the title model)."""
        return self._config.agent.compaction_model or self._config.agent.title_model

    @property
    def available_models(self) -> list[str]:
        return [e.model_id for e in self.available_model_entries]

    @property
    def available_model_entries(self) -> list[AvailableModelEntry]:
        """Deduplicated ``agent.available_models`` (last row per ``model_id``), sorted by id."""
        return agent_available_model_entries(self._config.agent)

    @property
    def enabled_model_entries(self) -> list[AvailableModelEntry]:
        """Catalog rows offered for selection. Disabled rows stay in ``available_model_entries``
        so lookups (max_input_tokens, vision) keep working for sessions that still reference them."""
        return [e for e in self.available_model_entries if e.enabled]

    def _max_input_tokens_for_model_id(self, model_id: str) -> int | None:
        for entry in self.available_model_entries:
            if entry.model_id == model_id:
                return entry.max_input_tokens
        return None

    def assert_models_enabled(self, active: ActiveSession) -> None:
        """Turn-level gate for the session's model overrides.

        Only the agent model is resolved per turn, so sentinel/title/compaction overrides would
        otherwise keep running on a stale model object after their catalog row was switched off.
        Platform defaults need no check — ``AgentConfig`` refuses to point them at a disabled row.
        """
        entries = {e.model_id: e for e in self.available_model_entries}
        overrides: dict[ModelType, str | None] = {
            "agent": active.agent_model_name,
            "sentinel": active.sentinel_model_name,
            "title": active.title_model_name,
            "compaction": active.compaction_model_name,
        }
        for model_type, name in overrides.items():
            entry = entries.get(name) if name is not None else None
            if entry is not None and not entry.enabled:
                raise DisabledModelError(f"{model_type} model {name!r} is disabled — select another model")

    def _resolve_model(self, name: str, user: str) -> Model:
        """Create a Model from a name for *user*, using the model_factory if available."""
        return self._model_factory(name, user=user) if self._model_factory else infer_model(name)

    def _resolve_model_settings(self, name: str) -> ModelSettings | None:
        """Build per-model request settings from the configured catalog."""
        return model_settings_for_config(self._config, name, default_thinking=True)

    def apply_platform_model_config(
        self,
        config: Config,
        *,
        model_factory: ModelFactory | None,
    ) -> None:
        self._config = config
        self._model_factory = model_factory
        for active in self._active.values():
            active.agent_model = None
            if active.sentinel is not None:
                model_name = active.sentinel_model_name or config.agent.sentinel_model
                try:
                    active.sentinel.set_model_runtime(
                        model=model_name,
                        model_factory=model_factory,
                        model_settings_resolver=self._resolve_model_settings,
                    )
                except Exception as exc:
                    if active.sentinel_model_name is None:
                        raise
                    _logger().warning(
                        f"Active sentinel model override {active.sentinel_model_name!r} for session "
                        + f"{active.state.session_id} is no longer valid after platform config update: {exc}. "
                        + f"Falling back to {config.agent.sentinel_model!r}."
                    )
                    active.sentinel.set_model_runtime(
                        model=config.agent.sentinel_model,
                        model_factory=model_factory,
                        model_settings_resolver=self._resolve_model_settings,
                    )
                    active.sentinel_model_name = None
                    active.state.sentinel_model_name = None
                    self._session_mgr.save_state(active.state)

    def reset_user_models(self, user: str) -> None:
        """Rebuild the cached models of *user*'s active sessions.

        Needed when the user's ChatGPT subscription login changes: cached models hold the provider
        of the previous login and would keep using its credentials.
        """
        for active in self._active.values():
            if active.owner != user:
                continue
            active.agent_model = None
            if active.sentinel is not None:
                active.sentinel.set_model(active.sentinel_model_name or self._config.agent.sentinel_model)

    def _restore_persisted_model_overrides(self, active: ActiveSession) -> None:
        """Validate restored overrides, falling back to defaults when they are no longer usable.

        A disabled model is kept as the override: no silent fallback, the next request fails with
        the disabled-model error so the user sees why nothing runs.
        """
        state_changed = False

        if active.agent_model_name is not None:
            try:
                active.agent_model = self._resolve_model(active.agent_model_name, active.owner)
            except DisabledModelError:
                pass
            except Exception as exc:
                _logger().warning(
                    f"Persisted agent model override {active.agent_model_name!r} for session "
                    + f"{active.state.session_id} is no longer valid: {exc}. Falling back to "
                    + f"{self._config.agent.model!r}."
                )
                self._apply_model_override(active, "agent", None, None)
                state_changed = True

        if active.sentinel_model_name is not None and active.sentinel is not None:
            try:
                active.sentinel.set_model(active.sentinel_model_name)
            except DisabledModelError:
                pass
            except Exception as exc:
                _logger().warning(
                    f"Persisted sentinel model override {active.sentinel_model_name!r} for session "
                    + f"{active.state.session_id} is no longer valid: {exc}. Falling back to "
                    + f"{self._config.agent.sentinel_model!r}."
                )
                self._apply_model_override(active, "sentinel", None, None)
                state_changed = True

        if active.title_model_name is not None:
            try:
                self._resolve_model(active.title_model_name, active.owner)
            except DisabledModelError:
                pass
            except Exception as exc:
                _logger().warning(
                    f"Persisted title model override {active.title_model_name!r} for session "
                    + f"{active.state.session_id} is no longer valid: {exc}. Falling back to "
                    + f"{self._config.agent.title_model!r}."
                )
                self._apply_model_override(active, "title", None, None)
                state_changed = True

        if active.compaction_model_name is not None:
            try:
                self._resolve_model(active.compaction_model_name, active.owner)
            except DisabledModelError:
                pass
            except Exception as exc:
                _logger().warning(
                    f"Persisted compaction model override {active.compaction_model_name!r} for session "
                    + f"{active.state.session_id} is no longer valid: {exc}. Falling back to "
                    + f"{self._compaction_model_default()!r}."
                )
                self._apply_model_override(active, "compaction", None, None)
                state_changed = True

        if state_changed:
            self._session_mgr.save_state(active.state)

    def update_session_model_overrides(
        self,
        session_id: str,
        *,
        agent_model_name: str | _UnsetType | None = _UNSET,
        sentinel_model_name: str | _UnsetType | None = _UNSET,
    ) -> SessionState:
        """Persist agent and sentinel model overrides without routing through slash commands."""
        active = self._active.get(session_id)
        state = active.state if active is not None else self._session_mgr.load_state(session_id)
        if state is None:
            raise KeyError(session_id)
        owner = active.owner if active is not None else self._session_mgr.load_meta(session_id).user

        if not isinstance(agent_model_name, _UnsetType):
            next_agent_model = None if agent_model_name is None else self._resolve_model(agent_model_name, owner)
            if active is not None:
                self._apply_model_override(active, "agent", agent_model_name, next_agent_model)
            else:
                state.agent_model_name = agent_model_name

        if not isinstance(sentinel_model_name, _UnsetType):
            if sentinel_model_name is not None:
                self._resolve_model(sentinel_model_name, owner)
            if active is not None:
                self._apply_model_override(active, "sentinel", sentinel_model_name, None)
            else:
                state.sentinel_model_name = sentinel_model_name

        self._session_mgr.save_state(state)
        return state

    def _handle_models_command(self, active: ActiveSession) -> dict[str, Any]:
        """Show the available model catalog for selection."""
        available = [e.model_dump(mode="json", by_alias=True) for e in self.enabled_model_entries]
        return {"command": "models", "data": {"available": available}}

    def _models_slash_view(self, active: ActiveSession) -> dict[str, dict[str, str]]:
        defaults = {
            "agent": self._config.agent.model,
            "sentinel": self._config.agent.sentinel_model,
            "title": self._config.agent.title_model,
            "compaction": self._compaction_model_default(),
        }
        overrides = {
            "agent": active.agent_model_name,
            "sentinel": active.sentinel_model_name,
            "title": active.title_model_name,
            "compaction": active.compaction_model_name,
        }
        return {t: {"current": overrides[t] or defaults[t], "default": defaults[t]} for t in self._MODEL_TYPES}

    async def _handle_model_selector_command(
        self, active: ActiveSession, arg: str, *, slash_line: str
    ) -> dict[str, Any]:
        """Process ``/model [ROLE] [MODEL | reset]`` while keeping ``/model MODEL`` as ``all``."""
        if not arg:
            return self._handle_model_all_command(active, "")

        target_aliases: dict[str, ModelType | Literal["all"]] = {
            "all": "all",
            "agent": "agent",
            "sentinel": "sentinel",
            "title": "title",
            "compaction": "compaction",
        }
        args = arg.split(maxsplit=1)
        target = target_aliases.get(args[0].lower())
        if target is None:
            return self._handle_model_all_command(active, arg)

        remainder = args[1].strip() if len(args) == 2 else ""
        if target == "all":
            return self._handle_model_all_command(active, remainder)
        return await self._handle_model_command(active, target, remainder, slash_line=slash_line)

    def _handle_model_all_command(self, active: ActiveSession, arg: str) -> dict[str, Any]:
        """Process ``/model [MODEL | reset]`` — show or set all three model roles at once."""
        defaults = {
            "agent": self._config.agent.model,
            "sentinel": self._config.agent.sentinel_model,
            "title": self._config.agent.title_model,
            "compaction": self._compaction_model_default(),
        }
        models_view = self._models_slash_view(active)

        if not arg:
            return {"command": "model", "data": {"models": models_view}}

        if arg == "reset":
            for model_type in self._MODEL_TYPES:
                self._apply_model_override(active, model_type, None, None)
            self._session_mgr.save_state(active.state)
            reset_view = {t: {"current": defaults[t], "default": defaults[t]} for t in self._MODEL_TYPES}
            return {
                "command": "model",
                "data": {"models": reset_view, "message": "Reset all models to defaults."},
            }

        try:
            new_model = self._resolve_model(arg, active.owner)
        except Exception as exc:
            return {"command": "model", "data": {"models": models_view, "error": str(exc)}}

        self._apply_model_override(active, "agent", arg, new_model)
        self._apply_model_override(active, "sentinel", arg, None)
        self._apply_model_override(active, "title", arg, None)
        self._apply_model_override(active, "compaction", arg, None)
        self._session_mgr.save_state(active.state)
        switched = {t: {"current": arg, "default": defaults[t]} for t in self._MODEL_TYPES}
        return {
            "command": "model",
            "data": {
                "models": switched,
                "message": f"Switched agent, sentinel, title, and compaction to: {arg}",
            },
        }

    async def _handle_model_command(
        self, active: ActiveSession, model_type: ModelType, arg: str, *, slash_line: str
    ) -> dict[str, Any]:
        """Process ``/model ROLE [MODEL | reset]`` for one model role."""
        cmd_name = {
            "agent": "model-agent",
            "sentinel": "model-sentinel",
            "title": "model-title",
            "compaction": "model-compaction",
        }[model_type]
        defaults = {
            "agent": self._config.agent.model,
            "sentinel": self._config.agent.sentinel_model,
            "title": self._config.agent.title_model,
            "compaction": self._compaction_model_default(),
        }
        overrides = {
            "agent": active.agent_model_name,
            "sentinel": active.sentinel_model_name,
            "title": active.title_model_name,
            "compaction": active.compaction_model_name,
        }
        default = defaults[model_type]
        current = overrides[model_type] or default

        if not arg:
            return {"command": cmd_name, "data": {"current": current, "default": default}}

        if arg == "reset":
            self._apply_model_override(active, model_type, None, None)
            self._session_mgr.save_state(active.state)
            if model_type == "title":
                await self._regenerate_title(active, pending_user_line=slash_line)
            return {
                "command": cmd_name,
                "data": {"current": default, "default": default, "message": f"Reset to default: {default}"},
            }

        try:
            new_model = self._resolve_model(arg, active.owner)
        except Exception as exc:
            return {"command": cmd_name, "data": {"current": current, "default": default, "error": str(exc)}}

        self._apply_model_override(active, model_type, arg, new_model if model_type == "agent" else None)
        self._session_mgr.save_state(active.state)
        if model_type == "title":
            await self._regenerate_title(active, pending_user_line=slash_line)
        return {
            "command": cmd_name,
            "data": {"current": arg, "default": default, "message": f"Switched to: {arg}"},
        }

    def _apply_model_override(
        self, active: ActiveSession, model_type: ModelType, name: str | None, model_obj: Model | None = None
    ) -> None:
        if model_type == "agent":
            active.agent_model = model_obj
            active.agent_model_name = name
            active.state.agent_model_name = name
        elif model_type == "sentinel":
            active.sentinel_model_name = name
            active.state.sentinel_model_name = name
            if active.sentinel:
                active.sentinel.set_model(name or self._config.agent.sentinel_model)
        elif model_type == "title":
            active.title_model_name = name
            active.state.title_model_name = name
        elif model_type == "compaction":
            active.compaction_model_name = name
            active.state.compaction_model_name = name

    async def _regenerate_title(self, active: ActiveSession, *, pending_user_line: str | None = None) -> None:
        """Regenerate the session title using the current title model.

        *pending_user_line* is the slash command line not yet persisted to events (e.g. first
        ``/model title`` in a session).
        """
        session_id = active.state.session_id
        events = list(self._session_mgr.load_events(session_id))
        if pending_user_line:
            events.append({"role": "user", "content": pending_user_line})
        if events:
            await self._generate_title(active, events)
