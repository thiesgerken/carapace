from __future__ import annotations

import json
import secrets
import shutil
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any

import yaml
from loguru import logger
from pydantic import BaseModel
from pydantic_ai import ModelMessage, ModelMessagesTypeAdapter

from carapace.models import SessionBudget, SessionState
from carapace.sandbox.state import (
    SessionSandboxSnapshot,
    clear_sandbox_snapshot,
    load_sandbox_snapshot,
    save_sandbox_snapshot,
)
from carapace.usage import LlmRequestLog, LlmRequestState, UsageTracker


def _to_yaml_safe(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _to_yaml_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set):
        return [_to_yaml_safe(item) for item in value]
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return repr(value)


def _append_loaded_event(doc: Any, result: list[dict[str, Any]]) -> None:
    if isinstance(doc, list):
        result.extend(item for item in doc if isinstance(item, dict))
    elif isinstance(doc, dict):
        result.append(doc)


def _timestamped_event(event: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    if event.get("timestamp"):
        return event
    stamped = dict(event)
    stamped["timestamp"] = (now or datetime.now(tz=UTC)).isoformat()
    return stamped


class SessionManager:
    def __init__(self, data_dir: Path):
        self.sessions_dir = data_dir / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self._events_lock = RLock()

    def create_session(
        self,
        channel_type: str = "cli",
        channel_ref: str = "",
        budget: SessionBudget | None = None,
        *,
        private: bool = False,
    ) -> SessionState:
        now = datetime.now(tz=UTC)
        session_id = f"{now:%Y-%m-%d-%H-%M}-{secrets.token_hex(4)}"
        state = SessionState(
            session_id=session_id,
            channel_type=channel_type,
            channel_ref=channel_ref or None,
            private=private,
            budget=budget.model_copy(deep=True) if budget is not None else SessionBudget(),
            created_at=now,
            last_active=now,
        )
        session_dir = self.sessions_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        self._save_state(state)
        return state

    def load_state(self, session_id: str) -> SessionState | None:
        """Load session state without mutating last_active."""
        state_path = self.sessions_dir / session_id / "state.yaml"
        if not state_path.exists():
            return None
        with open(state_path) as f:
            raw = yaml.safe_load(f)
        return SessionState.model_validate(raw)

    def resume_session(self, session_id: str) -> SessionState | None:
        state = self.load_state(session_id)
        if state is not None:
            state.last_active = datetime.now(tz=UTC)
        return state

    def list_sessions(self) -> list[str]:
        if not self.sessions_dir.exists():
            return []
        return sorted(
            [d.name for d in self.sessions_dir.iterdir() if d.is_dir()],
            key=lambda s: self._get_mtime(s),
            reverse=True,
        )

    def find_session(self, channel_type: str, channel_ref: str) -> str | None:
        """Return the most recently active session ID for the given channel, or None."""
        candidates: list[tuple[float, str]] = []
        for session_id in self.list_sessions():
            state = self.load_state(session_id)
            if state and state.channel_type == channel_type and state.channel_ref == channel_ref:
                candidates.append((self._get_mtime(session_id), session_id))
        if not candidates:
            return None
        return max(candidates, key=lambda t: t[0])[1]

    def _get_mtime(self, session_id: str) -> float:
        state_path = self.sessions_dir / session_id / "state.yaml"
        if state_path.exists():
            return state_path.stat().st_mtime
        return 0.0

    def delete_session(self, session_id: str) -> bool:
        session_dir = self.sessions_dir / session_id
        if session_dir.exists():
            shutil.rmtree(session_dir)
            return True
        return False

    def save_state(self, state: SessionState) -> None:
        self._save_state(state)

    def _save_state(self, state: SessionState) -> None:
        session_dir = self.sessions_dir / state.session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        state_path = session_dir / "state.yaml"
        with open(state_path, "w") as f:
            yaml.dump(state.model_dump(mode="json"), f, default_flow_style=False)

    def load_history(self, session_id: str) -> list[ModelMessage]:
        history_path = self.sessions_dir / session_id / "history.yaml"
        if not history_path.exists():
            # fallback to legacy JSON
            json_path = history_path.with_suffix(".json")
            if json_path.exists():
                return ModelMessagesTypeAdapter.validate_json(json_path.read_bytes())
            return []
        with open(history_path) as f:
            raw = yaml.safe_load(f)
        return ModelMessagesTypeAdapter.validate_python(raw or [])

    def save_history(self, session_id: str, messages: list[ModelMessage]) -> None:
        session_dir = self.sessions_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        history_path = session_dir / "history.yaml"
        data = ModelMessagesTypeAdapter.dump_python(messages, mode="json")
        with open(history_path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    # --- Usage tracking persistence ---

    def load_usage(self, session_id: str) -> UsageTracker:
        usage_path = self.sessions_dir / session_id / "usage.yaml"
        if not usage_path.exists():
            # fallback to legacy JSON
            json_path = usage_path.with_suffix(".json")
            if json_path.exists():
                return UsageTracker.model_validate_json(json_path.read_bytes())
            return UsageTracker()
        with open(usage_path) as f:
            raw = yaml.safe_load(f)
        return UsageTracker.model_validate(raw or {})

    def save_usage(self, session_id: str, tracker: UsageTracker) -> None:
        session_dir = self.sessions_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        usage_path = session_dir / "usage.yaml"
        with open(usage_path, "w") as f:
            yaml.dump(tracker.model_dump(mode="json"), f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    # --- Per-LLM-request log (API tokens + input-shape ratios) ---

    def load_llm_request_log(self, session_id: str) -> LlmRequestLog:
        path = self.sessions_dir / session_id / "llm_requests.yaml"
        if not path.exists():
            return LlmRequestLog()
        with open(path) as f:
            raw = yaml.safe_load(f)
        return LlmRequestLog.model_validate(raw or {})

    def save_llm_request_log(self, session_id: str, log: LlmRequestLog) -> None:
        session_dir = self.sessions_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        path = session_dir / "llm_requests.yaml"
        with open(path, "w") as f:
            yaml.dump(log.model_dump(mode="json"), f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    # --- In-flight LLM request activity ---

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

    # --- Sandbox snapshot persistence ---

    def _sandbox_snapshot_path(self, session_id: str) -> Path:
        return self.sessions_dir / session_id / "sandbox.yaml"

    def load_sandbox_snapshot(self, session_id: str) -> SessionSandboxSnapshot | None:
        return load_sandbox_snapshot(self._sandbox_snapshot_path(session_id))

    def save_sandbox_snapshot(self, session_id: str, snapshot: SessionSandboxSnapshot) -> None:
        save_sandbox_snapshot(self._sandbox_snapshot_path(session_id), snapshot)

    def clear_sandbox_snapshot(self, session_id: str) -> None:
        clear_sandbox_snapshot(self._sandbox_snapshot_path(session_id))

    # --- Event log (ordered display history including slash commands) ---

    def _load_events_unlocked(self, session_id: str) -> list[dict[str, Any]]:
        events_path = self.sessions_dir / session_id / "events.yaml"
        if not events_path.exists():
            # fallback to legacy JSON
            json_path = events_path.with_suffix(".json")
            if json_path.exists():
                return json.loads(json_path.read_bytes())
            return []
        result: list[dict[str, Any]] = []
        with open(events_path) as f:
            try:
                for doc in yaml.safe_load_all(f):
                    _append_loaded_event(doc, result)
            except yaml.YAMLError as exc:
                logger.warning(f"Failed to parse events.yaml safely for session {session_id}: {exc}")
                f.seek(0)
                docs = f.read().split("---\n")
                skipped_docs = 0
                for raw_doc in docs:
                    if not raw_doc.strip():
                        continue
                    try:
                        doc = yaml.safe_load(raw_doc)
                    except yaml.YAMLError:
                        skipped_docs += 1
                        continue
                    _append_loaded_event(doc, result)
                if skipped_docs:
                    logger.warning(f"Skipped {skipped_docs} invalid event document(s) in session {session_id}")
        return result

    def load_events(self, session_id: str) -> list[dict[str, Any]]:
        with self._events_lock:
            return self._load_events_unlocked(session_id)

    def _append_events_unlocked(self, session_id: str, events: list[dict[str, Any]]) -> None:
        session_dir = self.sessions_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        events_path = session_dir / "events.yaml"
        ts = datetime.now(tz=UTC)
        with open(events_path, "a") as f:
            for event in events:
                f.write("---\n")
                yaml.dump(
                    _to_yaml_safe(_timestamped_event(event, now=ts)),
                    f,
                    default_flow_style=False,
                    allow_unicode=True,
                    sort_keys=False,
                )

    def append_events(self, session_id: str, events: list[dict[str, Any]]) -> None:
        with self._events_lock:
            self._append_events_unlocked(session_id, events)

    def _save_events_unlocked(self, session_id: str, events: list[dict[str, Any]]) -> None:
        session_dir = self.sessions_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        events_path = session_dir / "events.yaml"
        with open(events_path, "w") as f:
            for event in events:
                f.write("---\n")
                yaml.dump(_to_yaml_safe(event), f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    def save_events(self, session_id: str, events: list[dict[str, Any]]) -> None:
        with self._events_lock:
            self._save_events_unlocked(session_id, events)

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
            self._save_events_unlocked(session_id, events)
            return result
