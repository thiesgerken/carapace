from __future__ import annotations

import json
import secrets
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic_ai import ModelMessage, ModelMessagesTypeAdapter

from carapace.models import SessionState, UsageTracker


class SessionManager:
    def __init__(self, data_dir: Path):
        self.sessions_dir = data_dir / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def create_session(self, channel_type: str = "cli", channel_ref: str = "") -> SessionState:
        now = datetime.now(tz=UTC)
        session_id = f"{now:%Y-%m-%d-%H-%M}-{secrets.token_hex(4)}"
        state = SessionState(
            session_id=session_id,
            channel_type=channel_type,
            channel_ref=channel_ref,
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

    # --- Event log (ordered display history including slash commands) ---

    def load_events(self, session_id: str) -> list[dict[str, Any]]:
        events_path = self.sessions_dir / session_id / "events.yaml"
        if not events_path.exists():
            # fallback to legacy JSON
            json_path = events_path.with_suffix(".json")
            if json_path.exists():
                return json.loads(json_path.read_bytes())
            return []
        with open(events_path) as f:
            return yaml.safe_load(f) or []

    def append_events(self, session_id: str, events: list[dict[str, Any]]) -> None:
        session_dir = self.sessions_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        events_path = session_dir / "events.yaml"
        existing = self.load_events(session_id)
        existing.extend(events)
        with open(events_path, "w") as f:
            yaml.dump(existing, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
