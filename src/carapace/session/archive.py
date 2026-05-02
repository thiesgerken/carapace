from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from loguru import logger
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, ThinkingPart, ToolCallPart, UserPromptPart

from carapace.git.store import GitStore
from carapace.models import SessionCommitConfig, SessionState
from carapace.session.manager import SessionManager

ArchiveTrigger = Literal["manual", "autosave", "archive"]

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
        config: SessionCommitConfig,
    ) -> None:
        self._knowledge_dir = knowledge_dir
        self._git_store = git_store
        self._session_mgr = session_mgr
        self._config = config
        self._session_locks: dict[str, asyncio.Lock] = {}
        self._session_lock_refs: dict[str, int] = {}

    @property
    def enabled(self) -> bool:
        return self._config.enabled

    def archive_relative_path_for_state(self, state: SessionState) -> str:
        prefix = Path(self._config.path_prefix)
        relative = prefix / f"{state.created_at:%Y}" / f"{state.created_at:%m}" / state.session_id / "conversation.json"
        return relative.as_posix()

    def archive_absolute_path_for_state(self, state: SessionState) -> Path:
        return self._knowledge_dir / self.archive_relative_path_for_state(state)

    def _get_session_lock(self, session_id: str) -> asyncio.Lock:
        lock = self._session_locks.get(session_id)
        if lock is None:
            lock = asyncio.Lock()
            self._session_locks[session_id] = lock
        return lock

    @asynccontextmanager
    async def _locked_session(self, session_id: str):
        lock = self._get_session_lock(session_id)
        self._session_lock_refs[session_id] = self._session_lock_refs.get(session_id, 0) + 1
        try:
            async with lock:
                yield
        finally:
            remaining_refs = self._session_lock_refs[session_id] - 1
            if remaining_refs == 0:
                self._session_lock_refs.pop(session_id, None)
                if self._session_locks.get(session_id) is lock:
                    self._session_locks.pop(session_id, None)
            else:
                self._session_lock_refs[session_id] = remaining_refs

    async def commit_session(
        self,
        session_id: str,
        *,
        trigger: ArchiveTrigger,
        autosave_cutoff: datetime | None = None,
        is_agent_running: Callable[[], bool] | None = None,
    ) -> SessionArchiveResult:
        async with self._locked_session(session_id):
            if not self._config.enabled:
                return SessionArchiveResult(
                    committed=False,
                    archive_path=None,
                    committed_at=None,
                    trigger=trigger,
                    reason="Session archive is disabled",
                )

            current_state = self._session_mgr.load_state(session_id)
            if current_state is None:
                raise ValueError(f"Session {session_id!r} not found")
            if current_state.attributes.private:
                return SessionArchiveResult(
                    committed=False,
                    archive_path=None,
                    committed_at=None,
                    trigger=trigger,
                    reason="Private sessions cannot be committed to knowledge",
                )
            if autosave_cutoff is not None and current_state.last_active > autosave_cutoff:
                return SessionArchiveResult(
                    committed=False,
                    archive_path=None,
                    committed_at=current_state.knowledge_last_committed_at,
                    trigger=trigger,
                    reason="Session is still active",
                )
            if (
                autosave_cutoff is not None
                and current_state.knowledge_last_committed_at is not None
                and current_state.knowledge_last_committed_at >= current_state.last_active
            ):
                return SessionArchiveResult(
                    committed=False,
                    archive_path=current_state.knowledge_last_archive_path,
                    committed_at=current_state.knowledge_last_committed_at,
                    trigger=trigger,
                    reason="No archive changes to commit",
                )
            if is_agent_running is not None and is_agent_running():
                return SessionArchiveResult(
                    committed=False,
                    archive_path=current_state.knowledge_last_archive_path,
                    committed_at=current_state.knowledge_last_committed_at,
                    trigger=trigger,
                    reason="Cannot archive a session while an agent turn is running",
                )

            history = self._normalized_history(session_id)
            if not history:
                return SessionArchiveResult(
                    committed=False,
                    archive_path=None,
                    committed_at=None,
                    trigger=trigger,
                    reason="Session has no history to archive yet",
                )

            archive_path = self.archive_relative_path_for_state(current_state)
            archive_file = self._knowledge_dir / archive_path
            committed_at = datetime.now(tz=UTC)
            session_payload = {
                "session_id": current_state.session_id,
                "channel_type": current_state.channel_type,
                "channel_ref": current_state.channel_ref,
                "title": current_state.title,
                "attributes": current_state.attributes.model_dump(mode="json"),
                "created_at": current_state.created_at.isoformat(),
                "last_active": current_state.last_active.isoformat(),
            }
            payload = {
                "schema_version": _SCHEMA_VERSION,
                "session": session_payload,
                "archive": {
                    "trigger": trigger,
                    "committed_at": committed_at.isoformat(),
                    "archive_path": archive_path,
                },
                "history": history,
            }
            serialized = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
            export_hash = self._content_hash(
                session_payload=session_payload,
                archive_path=archive_path,
                history=history,
            )

            if (
                current_state.knowledge_last_export_hash == export_hash
                and current_state.knowledge_last_archive_path == archive_path
                and archive_file.exists()
            ):
                return SessionArchiveResult(
                    committed=False,
                    archive_path=archive_path,
                    committed_at=current_state.knowledge_last_committed_at,
                    trigger=trigger,
                    reason="No archive changes to commit",
                )

            archive_file.parent.mkdir(parents=True, exist_ok=True)
            archive_file.write_text(serialized, encoding="utf-8")
            commit_action = "add" if current_state.knowledge_last_committed_at is None else "update"

            try:
                commit_made = await self._git_store.commit(
                    [archive_path],
                    f"💾 session: {commit_action} {session_id}",
                    session_id=session_id,
                )
            except RuntimeError:
                archive_file.unlink(missing_ok=True)
                self._prune_empty_archive_dirs(archive_file.parent)
                raise

            latest_state = self._session_mgr.load_state(session_id)
            if latest_state is None:
                raise ValueError(f"Session {session_id!r} not found")

            latest_state.knowledge_last_archive_path = archive_path
            latest_state.knowledge_last_export_hash = export_hash
            if commit_made:
                latest_state.knowledge_last_committed_at = committed_at
                latest_state.knowledge_last_commit_trigger = trigger
            self._session_mgr.save_state(latest_state)

            logger.info(
                f"Session archive {'committed' if commit_made else 'updated'} session={session_id} trigger={trigger}"
            )
            return SessionArchiveResult(
                committed=commit_made,
                archive_path=archive_path,
                committed_at=latest_state.knowledge_last_committed_at,
                trigger=trigger,
                reason=None if commit_made else "No archive changes to commit",
            )

    async def delete_session_archive(self, state: SessionState) -> bool:
        async with self._locked_session(state.session_id):
            if not self._config.enabled:
                return False
            if state.attributes.private:
                return False

            archive_path = state.knowledge_last_archive_path or self.archive_relative_path_for_state(state)
            archive_file = self._knowledge_dir / archive_path
            if not archive_file.exists():
                return False

            archive_file.unlink()
            self._prune_empty_archive_dirs(archive_file.parent)
            commit_made = await self._git_store.commit_removals(
                [archive_path],
                f"🗑️ session: remove archive {state.session_id}",
                session_id=state.session_id,
            )
            logger.info(f"Session archive removed session={state.session_id} committed={commit_made}")
            return commit_made

    def _content_hash(
        self,
        *,
        session_payload: dict[str, Any],
        archive_path: str,
        history: list[dict[str, Any]],
    ) -> str:
        stable_payload = {
            "schema_version": _SCHEMA_VERSION,
            "session": session_payload,
            "archive_path": archive_path,
            "history": history,
        }
        return hashlib.sha256(
            json.dumps(stable_payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()

    def _prune_empty_archive_dirs(self, start_dir: Path) -> None:
        stop_dir = (self._knowledge_dir / self._config.path_prefix).resolve()
        current = start_dir.resolve()
        while current != stop_dir and current.is_dir() and stop_dir in current.parents:
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
