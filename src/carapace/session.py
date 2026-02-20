from __future__ import annotations

import shutil
import uuid
from datetime import datetime
from pathlib import Path

import yaml
from pydantic_ai import ModelMessage, ModelMessagesTypeAdapter
from pydantic_core import to_json

from carapace.models import SessionState


class SessionManager:
    def __init__(self, data_dir: Path):
        self.sessions_dir = data_dir / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def create_session(self, channel_type: str = "cli", channel_ref: str = "") -> SessionState:
        session_id = uuid.uuid4().hex[:12]
        state = SessionState(
            session_id=session_id,
            channel_type=channel_type,
            channel_ref=channel_ref,
            created_at=datetime.now(),
            last_active=datetime.now(),
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
            state.last_active = datetime.now()
        return state

    def list_sessions(self) -> list[str]:
        if not self.sessions_dir.exists():
            return []
        return sorted(
            [d.name for d in self.sessions_dir.iterdir() if d.is_dir()],
            key=lambda s: self._get_mtime(s),
            reverse=True,
        )

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
        history_path = self.sessions_dir / session_id / "history.json"
        if not history_path.exists():
            return []
        raw = history_path.read_bytes()
        return ModelMessagesTypeAdapter.validate_json(raw)

    def save_history(self, session_id: str, messages: list[ModelMessage]) -> None:
        session_dir = self.sessions_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        history_path = session_dir / "history.json"
        history_path.write_bytes(to_json(messages))
