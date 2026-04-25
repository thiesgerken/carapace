from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from loguru import logger
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, ThinkingPart, ToolCallPart, UserPromptPart

from carapace.git.store import GitStore
from carapace.models import SessionArchiveConfig, SessionState
from carapace.session.manager import SessionManager

ArchiveTrigger = Literal["manual", "autosave"]

_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class SessionArchiveResult:
    committed: bool
    archive_path: str | None
    committed_at: datetime | None
    trigger: ArchiveTrigger
    reason: str | None = None


class SessionArchiveService:
    def __init__(
        self,
        *,
        knowledge_dir: Path,
        git_store: GitStore,
        session_mgr: SessionManager,
        config: SessionArchiveConfig,
    ) -> None:
        self._knowledge_dir = knowledge_dir
        self._git_store = git_store
        self._session_mgr = session_mgr
        self._config = config

    @property
    def enabled(self) -> bool:
        return self._config.enabled

    def archive_relative_path_for_state(self, state: SessionState) -> str:
        prefix = Path(self._config.path_prefix)
        relative = prefix / f"{state.created_at:%Y}" / f"{state.created_at:%m}" / state.session_id / "conversation.json"
        return relative.as_posix()

    def archive_absolute_path_for_state(self, state: SessionState) -> Path:
        return self._knowledge_dir / self.archive_relative_path_for_state(state)

    async def commit_session(self, session_id: str, *, trigger: ArchiveTrigger) -> SessionArchiveResult:
        if not self._config.enabled:
            return SessionArchiveResult(
                committed=False,
                archive_path=None,
                committed_at=None,
                trigger=trigger,
                reason="Session archive is disabled",
            )

        state = self._session_mgr.load_state(session_id)
        if state is None:
            raise ValueError(f"Session {session_id!r} not found")
        if state.private:
            return SessionArchiveResult(
                committed=False,
                archive_path=None,
                committed_at=None,
                trigger=trigger,
                reason="Private sessions cannot be committed to knowledge",
            )

        history = self._normalized_history(session_id)
        if not history:
            return SessionArchiveResult(
                committed=False,
                archive_path=self.archive_relative_path_for_state(state),
                committed_at=None,
                trigger=trigger,
                reason="Session has no history to archive yet",
            )

        archive_path = self.archive_relative_path_for_state(state)
        archive_file = self._knowledge_dir / archive_path
        committed_at = datetime.now(tz=UTC)
        payload = {
            "schema_version": _SCHEMA_VERSION,
            "session": {
                "session_id": state.session_id,
                "channel_type": state.channel_type,
                "channel_ref": state.channel_ref,
                "title": state.title,
                "private": state.private,
                "created_at": state.created_at.isoformat(),
                "last_active": state.last_active.isoformat(),
            },
            "archive": {
                "trigger": trigger,
                "committed_at": committed_at.isoformat(),
                "archive_path": archive_path,
            },
            "history": history,
        }
        serialized = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        export_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()

        if (
            state.knowledge_last_export_hash == export_hash
            and state.knowledge_last_archive_path == archive_path
            and archive_file.exists()
        ):
            return SessionArchiveResult(
                committed=False,
                archive_path=archive_path,
                committed_at=state.knowledge_last_committed_at,
                trigger=trigger,
                reason="No archive changes to commit",
            )

        archive_file.parent.mkdir(parents=True, exist_ok=True)
        archive_file.write_text(serialized, encoding="utf-8")

        commit_made = await self._git_store.commit(
            [archive_path],
            f"💾 session: archive {session_id}",
            session_id=session_id,
        )

        state.knowledge_last_archive_path = archive_path
        state.knowledge_last_export_hash = export_hash
        if commit_made:
            state.knowledge_last_committed_at = committed_at
            state.knowledge_last_commit_trigger = trigger
        self._session_mgr.save_state(state)

        logger.info(
            f"Session archive {'committed' if commit_made else 'updated'} session={session_id} trigger={trigger}"
        )
        return SessionArchiveResult(
            committed=commit_made,
            archive_path=archive_path,
            committed_at=state.knowledge_last_committed_at,
            trigger=trigger,
            reason=None if commit_made else "No archive changes to commit",
        )

    async def delete_session_archive(self, state: SessionState) -> bool:
        if not self._config.enabled:
            return False

        archive_path = state.knowledge_last_archive_path or self.archive_relative_path_for_state(state)
        archive_file = self._knowledge_dir / archive_path
        if not archive_file.exists():
            return False

        archive_file.unlink()
        self._prune_empty_archive_dirs(archive_file.parent)
        commit_made = await self._git_store.commit(
            [archive_path],
            f"🗑️ session: remove archive {state.session_id}",
            session_id=state.session_id,
        )
        logger.info(f"Session archive removed session={state.session_id} committed={commit_made}")
        return commit_made

    def _prune_empty_archive_dirs(self, start_dir: Path) -> None:
        stop_dir = self._knowledge_dir / self._config.path_prefix
        current = start_dir
        while current != stop_dir and current.is_dir():
            try:
                current.rmdir()
            except OSError:
                break
            current = current.parent

    def _normalized_history(self, session_id: str) -> list[dict[str, Any]]:
        events = self._session_mgr.load_events(session_id)
        if events:
            return [dict(event) for event in events]

        result: list[dict[str, Any]] = []
        for msg in self._session_mgr.load_history(session_id):
            if isinstance(msg, ModelRequest):
                for part in msg.parts:
                    if isinstance(part, UserPromptPart) and isinstance(part.content, str):
                        result.append({"role": "user", "content": part.content})
            elif isinstance(msg, ModelResponse):
                for part in msg.parts:
                    if isinstance(part, ToolCallPart):
                        args = part.args if isinstance(part.args, dict) else {}
                        event: dict[str, Any] = {
                            "role": "tool_call",
                            "content": "",
                            "tool": part.tool_name,
                            "args": args,
                        }
                        contexts_raw = args.get("contexts")
                        if isinstance(contexts_raw, list):
                            event["contexts"] = list(contexts_raw)
                        result.append(event)
                    elif isinstance(part, TextPart):
                        result.append({"role": "assistant", "content": part.content})
                    elif isinstance(part, ThinkingPart) and part.content:
                        result.append({"role": "thinking", "content": part.content})
        return result
