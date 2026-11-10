from __future__ import annotations

import contextlib
from decimal import Decimal
from typing import Annotated, Any, Self

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger
from pydantic import BaseModel, ConfigDict, StringConstraints, ValidationError, field_validator, model_validator
from pydantic_ai.messages import ModelMessage

from ..api_keys import Access, Scope
from ..auth import UserIdentity
from ..models.git import GitActionResult, GlobalGitStatus, SandboxGitStatus
from ..models.session import SessionAttributes, SessionBudget, SessionJobRunContext, SessionState
from ..sandbox.state import SessionSandboxSnapshot
from ..session.transcript import is_turn_terminal_event
from ..session.usage_budget import BUDGET_METRIC_FIELDS, parse_budget_limit
from ..usage import BudgetMetric, CostSplit
from ..user_defaults import apply_user_model_defaults, effective_user_budget
from .auth import require
from .history import _history_from_messages
from .state import server_module

server = server_module()

router = APIRouter()

_BUDGET_FIELD_METRICS: dict[str, BudgetMetric] = {field: metric for metric, field in BUDGET_METRIC_FIELDS.items()}
_SEARCH_LIMIT = 50


class SessionCreateRequest(BaseModel):
    channel_type: str = "cli"
    channel_ref: str = ""
    private: bool | None = None
    unattended: bool | None = None
    ask_mode: bool | None = None
    yolo_mode: bool | None = None

    @model_validator(mode="after")
    def _validate_modes(self) -> Self:
        if self.ask_mode and self.yolo_mode:
            raise ValueError("ask_mode and yolo_mode are mutually exclusive")
        return self


class SessionAttributesPatch(BaseModel):
    private: bool | None = None
    archived: bool | None = None
    pinned: bool | None = None
    favorite: bool | None = None
    unattended: bool | None = None
    ask_mode: bool | None = None
    yolo_mode: bool | None = None

    @model_validator(mode="after")
    def _validate_modes(self) -> Self:
        if self.ask_mode and self.yolo_mode:
            raise ValueError("ask_mode and yolo_mode are mutually exclusive")
        return self


class SessionBudgetPatch(BaseModel):
    """Limits as ``/budget`` accepts them (``"100k"``, ``"2.50"``); ``null`` clears one, omitted keeps it."""

    model_config = ConfigDict(extra="forbid")

    input_tokens: str | None = None
    output_tokens: str | None = None
    cost_usd: str | None = None
    equivalent_cost_usd: str | None = None
    tool_calls: str | None = None
    autonomous_tool_calls: str | None = None

    def parsed_limits(self) -> dict[BudgetMetric, int | Decimal | None]:
        """Parse every set field with the ``/budget`` parser; raises ``ValueError`` on the first invalid one."""
        limits: dict[BudgetMetric, int | Decimal | None] = {}
        for field in self.model_fields_set:
            metric = _BUDGET_FIELD_METRICS[field]
            raw: str | None = getattr(self, field)
            limits[metric] = None if raw is None else parse_budget_limit(metric, raw)
        return limits


class SessionUpdateRequest(BaseModel):
    attributes: SessionAttributesPatch | None = None
    budget: SessionBudgetPatch | None = None
    agent_model_name: str | None = None
    sentinel_model_name: str | None = None

    @field_validator("agent_model_name", "sentinel_model_name", mode="before")
    @classmethod
    def _normalize_model_name_field(cls, value: str | None) -> str | None:
        return cls._normalize_optional_model_name(value)

    @staticmethod
    def _normalize_optional_model_name(value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class SessionForkRequest(BaseModel):
    event_index: int
    channel_type: str = "cli"
    channel_ref: str = ""
    unattended: bool | None = None
    ask_mode: bool | None = None
    yolo_mode: bool | None = None

    @model_validator(mode="after")
    def _validate_modes(self) -> Self:
        if self.ask_mode and self.yolo_mode:
            raise ValueError("ask_mode and yolo_mode are mutually exclusive")
        return self


class SessionInfo(BaseModel):
    session_id: str
    channel_type: str
    channel_ref: str | None = None
    created_at: str
    last_active: str
    title: str | None = None
    agent_model_name: str | None = None
    sentinel_model_name: str | None = None
    attributes: SessionAttributes
    budget: SessionBudget
    latest_job_run: SessionJobRunContext | None = None
    knowledge_last_committed_at: str | None = None
    knowledge_last_archive_path: str | None = None
    knowledge_last_commit_trigger: str | None = None
    message_count: int = 0
    # Billed per token; subscription usage is only in the equivalent cost (list price).
    total_cost_usd: float | None = None
    total_equivalent_cost_usd: float | None = None
    sandbox: SessionSandboxSnapshot | None = None

    @classmethod
    def from_state(
        cls,
        state: SessionState,
        *,
        message_count: int = 0,
        total_cost: CostSplit | None = None,
        sandbox: SessionSandboxSnapshot | None = None,
    ) -> SessionInfo:
        return cls(
            session_id=state.session_id,
            channel_type=state.channel_type,
            channel_ref=state.channel_ref,
            created_at=state.created_at.isoformat(),
            last_active=state.last_active.isoformat(),
            title=state.title,
            agent_model_name=state.agent_model_name,
            sentinel_model_name=state.sentinel_model_name,
            attributes=state.attributes,
            budget=state.budget,
            latest_job_run=state.latest_job_run.model_copy(deep=True) if state.latest_job_run is not None else None,
            knowledge_last_committed_at=(
                state.knowledge_last_committed_at.isoformat() if state.knowledge_last_committed_at else None
            ),
            knowledge_last_archive_path=state.knowledge_last_archive_path,
            knowledge_last_commit_trigger=state.knowledge_last_commit_trigger,
            message_count=message_count,
            total_cost_usd=float(total_cost.actual) if total_cost is not None else None,
            total_equivalent_cost_usd=float(total_cost.equivalent) if total_cost is not None else None,
            sandbox=sandbox,
        )


class SessionListPage(BaseModel):
    items: list[SessionInfo]
    next_cursor: str | None = None
    has_more: bool


class SessionSearchHit(BaseModel):
    session: SessionInfo
    # The first matching chat message around the match; only fulltext searches set it.
    snippet: str | None = None


class SessionArchiveCommitResponse(BaseModel):
    session: SessionInfo
    committed: bool
    archive_path: str | None = None
    committed_at: str | None = None
    trigger: str
    reason: str | None = None


def _session_message_count(session_id: str) -> int:
    events = server._engine.session_mgr.load_events(session_id)
    if events:
        return sum(1 for event in events if event.get("role") == "user" or is_turn_terminal_event(event))

    history = _history_from_messages(session_id)
    return sum(1 for message in history if message.role in {"user", "assistant"})


def _load_owned_state(session_id: str, user: UserIdentity) -> SessionState:
    state = server._engine.session_mgr.load_state(session_id)
    if state is None or not server._engine.session_mgr.is_owned_by(session_id, user.username):
        raise HTTPException(status_code=404, detail="Session not found")
    return state


def _parse_session_cursor(cursor: str | None) -> int:
    if cursor is None:
        return 0
    try:
        offset = int(cursor)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid session cursor") from exc
    if offset < 0:
        raise HTTPException(status_code=400, detail="Invalid session cursor")
    return offset


def _session_info_from_state(state: SessionState, *, include_message_count: bool) -> SessionInfo:
    message_count = _session_message_count(state.session_id) if include_message_count else 0
    sandbox = server._engine.session_mgr.load_sandbox_snapshot(state.session_id)
    return SessionInfo.from_state(
        state,
        message_count=message_count,
        total_cost=_session_total_cost(state.session_id),
        sandbox=sandbox,
    )


def _session_total_cost(session_id: str) -> CostSplit:
    return server._engine.session_mgr.load_usage(session_id).total_cost()


async def _list_session_page(
    *,
    include_message_count: bool,
    include_archived: bool,
    limit: int,
    cursor: str | None,
    user: UserIdentity,
) -> SessionListPage:
    offset = _parse_session_cursor(cursor)

    def load_page() -> dict[str, Any]:
        states, has_more = server._engine.session_mgr.list_session_states_page(
            user=user.username, include_archived=include_archived, offset=offset, limit=limit
        )
        page = SessionListPage(
            items=[_session_info_from_state(state, include_message_count=include_message_count) for state in states],
            next_cursor=str(offset + limit) if has_more else None,
            has_more=has_more,
        )
        return page.model_dump(mode="json")

    cached = await server._session_list_cache.get_session_page(
        user=user.username,
        include_archived=include_archived,
        include_message_count=include_message_count,
        offset=offset,
        limit=limit,
        loader=load_page,
    )
    return SessionListPage.model_validate(cached)


@router.post("/sessions", response_model=SessionInfo)
async def create_session(
    user: Annotated[UserIdentity, Depends(require(Scope.sessions, Access.write))],
    body: SessionCreateRequest | None = None,
) -> SessionInfo:
    body = body or SessionCreateRequest()
    state = server._engine.session_mgr.create_session(
        body.channel_type,
        body.channel_ref,
        budget=effective_user_budget(server._engine.config, user.config),
        user=user.username,
        private=False if body.private is None else body.private,
        unattended=False if body.unattended is None else body.unattended,
        ask_mode=False if body.ask_mode is None else body.ask_mode,
        yolo_mode=False if body.yolo_mode is None else body.yolo_mode,
    )
    apply_user_model_defaults(state, user.config)
    server._engine.session_mgr.save_state(state)
    return SessionInfo.from_state(state)


@router.get("/sessions", response_model=SessionListPage)
async def list_sessions(
    user: Annotated[UserIdentity, Depends(require(Scope.sessions, Access.read))],
    include_message_count: bool = False,
    include_archived: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = None,
) -> SessionListPage:
    return await _list_session_page(
        include_message_count=include_message_count,
        include_archived=include_archived,
        limit=limit,
        cursor=cursor,
        user=user,
    )


@router.get("/sessions/search", response_model=list[SessionSearchHit])
# Plain def: the scan and the per-hit loads are blocking, so FastAPI runs them in its threadpool.
def search_sessions(
    user: Annotated[UserIdentity, Depends(require(Scope.sessions, Access.read))],
    q: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1), Query()],
    fulltext: bool = False,
) -> list[SessionSearchHit]:
    matches = server._engine.session_mgr.search_sessions(
        user=user.username, query=q, fulltext=fulltext, limit=_SEARCH_LIMIT
    )
    return [
        SessionSearchHit(
            session=_session_info_from_state(match.state, include_message_count=True),
            snippet=match.snippet,
        )
        for match in matches
    ]


@router.get("/sessions/{session_id}", response_model=SessionInfo)
async def get_session(
    session_id: str, user: Annotated[UserIdentity, Depends(require(Scope.sessions, Access.read))]
) -> SessionInfo:
    state = _load_owned_state(session_id, user)
    sandbox = server._engine.session_mgr.load_sandbox_snapshot(session_id)
    return SessionInfo.from_state(
        state,
        message_count=_session_message_count(session_id),
        total_cost=_session_total_cost(session_id),
        sandbox=sandbox,
    )


async def archive_session(session_id: str) -> None:
    """Mark a session archived, commit it to knowledge (unless private), and tear down its sandbox.

    Mirrors the archive branch of update_session. No-ops if the session is missing,
    already archived, or has an agent turn running.
    """
    state = server._engine.session_mgr.load_state(session_id)
    if state is None or state.attributes.archived:
        return
    if server._engine.is_agent_running(session_id):
        return

    previous_attributes = state.attributes
    next_attributes = state.attributes.model_copy(update={"archived": True})
    state.attributes = next_attributes
    server._engine.session_mgr.save_state(state)
    server._engine.update_active_state(session_id, attributes=next_attributes)

    try:
        if server._session_archive.enabled and not next_attributes.private:
            await server._session_archive.commit_session(
                session_id,
                trigger="archive",
                is_agent_running=lambda: server._engine.is_agent_running(session_id),
            )
    except Exception:
        # Roll back the archived flag so a transient commit failure doesn't strand
        # the session as archived-but-not-committed (archive_session would no-op next run).
        state.attributes = previous_attributes
        server._engine.session_mgr.save_state(state)
        server._engine.update_active_state(session_id, attributes=previous_attributes)
        raise

    server._engine.deactivate(session_id)
    await server._engine.sandbox_mgr.destroy_session(session_id)


@router.patch("/sessions/{session_id}", response_model=SessionInfo)
async def update_session(
    session_id: str,
    body: SessionUpdateRequest,
    user: Annotated[UserIdentity, Depends(require(Scope.sessions, Access.write))],
) -> SessionInfo:
    state = _load_owned_state(session_id, user)

    # Parsed up front but applied last, so an invalid limit or a failed attribute/model change leaves
    # the whole session untouched.
    budget_limits: dict[BudgetMetric, int | Decimal | None] | None = None
    if body.budget is not None:
        try:
            budget_limits = body.budget.parsed_limits()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    next_attributes: SessionAttributes | None = None
    previous_attributes: SessionAttributes | None = None
    previous_history: list[ModelMessage] | None = None
    archive_changed = False
    archive_now = False

    if body.attributes is not None:
        previous_attributes = state.attributes.model_copy(deep=True)
        merged_attributes = state.attributes.model_dump(mode="json")
        merged_attributes.update(body.attributes.model_dump(exclude_none=True))
        try:
            next_attributes = SessionAttributes.model_validate(merged_attributes)
        except ValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        unattended_changed = next_attributes.unattended != state.attributes.unattended
        if unattended_changed:
            active = server._engine._active.get(session_id)
            lock = active.lock if active else contextlib.nullcontext()
            async with lock:
                if server._engine.is_agent_running(session_id):
                    raise HTTPException(
                        status_code=409,
                        detail="Cannot toggle unattended mode while an agent turn is actively running",
                    )
                if state.attributes.unattended and not next_attributes.unattended:
                    history = server._engine.session_mgr.load_history(session_id)
                    previous_history = history
                    truncated_history = server._engine._truncate_incomplete_model_history(history)
                    normalized_history = server._engine._normalize_unattended_output_history(truncated_history)
                    server._engine.session_mgr.save_history(session_id, normalized_history)

        archive_changed = next_attributes.archived != state.attributes.archived
        archive_now = next_attributes.archived

        if archive_changed and server._engine.is_agent_running(session_id):
            raise HTTPException(status_code=409, detail="Cannot archive a session while an agent turn is running")

    model_changes: dict[str, str | None] = {}
    if "agent_model_name" in body.model_fields_set:
        model_changes["agent_model_name"] = body.agent_model_name
    if "sentinel_model_name" in body.model_fields_set:
        model_changes["sentinel_model_name"] = body.sentinel_model_name

    previous_models: dict[str, str | None] = {}
    if model_changes:
        previous_models = {
            "agent_model_name": state.agent_model_name,
            "sentinel_model_name": state.sentinel_model_name,
        }
        try:
            state = server._engine.update_session_model_overrides(session_id, **model_changes)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    if next_attributes is not None:
        state.attributes = next_attributes
        server._engine.session_mgr.save_state(state)
        server._engine.update_active_state(session_id, attributes=next_attributes)

        try:
            if archive_changed and archive_now and server._session_archive.enabled and not next_attributes.private:
                await server._session_archive.commit_session(
                    session_id,
                    trigger="archive",
                    is_agent_running=lambda: server._engine.is_agent_running(session_id),
                )
                refreshed = server._engine.session_mgr.load_state(session_id)
                if refreshed is None:
                    raise HTTPException(status_code=404, detail="Session not found")
                state = refreshed
        except Exception:
            if previous_attributes is not None:
                state.attributes = previous_attributes
                server._engine.session_mgr.save_state(state)
                server._engine.update_active_state(session_id, attributes=previous_attributes)
            if previous_history is not None:
                server._engine.session_mgr.save_history(session_id, previous_history)
            if model_changes:
                state = server._engine.update_session_model_overrides(session_id, **previous_models)
            raise

        if archive_changed and archive_now:
            server._engine.deactivate(session_id)
            await server._engine.sandbox_mgr.destroy_session(session_id)

    if budget_limits is not None:
        await server._engine.update_session_budget(session_id, budget_limits)
        state = _load_owned_state(session_id, user)

    sandbox = server._engine.session_mgr.load_sandbox_snapshot(session_id)
    return SessionInfo.from_state(
        state,
        message_count=_session_message_count(session_id),
        total_cost=_session_total_cost(session_id),
        sandbox=sandbox,
    )


@router.post("/sessions/{session_id}/fork", response_model=SessionInfo)
async def fork_session(
    session_id: str,
    body: SessionForkRequest,
    user: Annotated[UserIdentity, Depends(require(Scope.sessions, Access.write))],
) -> SessionInfo:
    _load_owned_state(session_id, user)

    try:
        forked = server._engine.fork_session(
            session_id,
            event_index=body.event_index,
            channel_type=body.channel_type,
            channel_ref=body.channel_ref,
            unattended=body.unattended,
            ask_mode=body.ask_mode,
            yolo_mode=body.yolo_mode,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return SessionInfo.from_state(
        forked,
        message_count=_session_message_count(forked.session_id),
        total_cost=_session_total_cost(forked.session_id),
    )


@router.post("/sessions/{session_id}/knowledge/commit", response_model=SessionArchiveCommitResponse)
async def commit_session_knowledge(
    session_id: str,
    user: Annotated[UserIdentity, Depends(require(Scope.sessions, Access.write))],
) -> SessionArchiveCommitResponse:
    state = _load_owned_state(session_id, user)
    if not server._session_archive.enabled:
        raise HTTPException(status_code=503, detail="Session archive is disabled")
    if state.attributes.private:
        raise HTTPException(status_code=409, detail="Private sessions cannot be committed to knowledge")
    if server._engine.is_agent_running(session_id):
        raise HTTPException(status_code=409, detail="Cannot archive a session while an agent turn is running")

    result = await server._session_archive.commit_session(
        session_id,
        trigger="manual",
        is_agent_running=lambda: server._engine.is_agent_running(session_id),
    )
    fresh = server._engine.session_mgr.load_state(session_id)
    if fresh is None:
        raise HTTPException(status_code=404, detail="Session not found")
    sandbox = server._engine.session_mgr.load_sandbox_snapshot(session_id)
    return SessionArchiveCommitResponse(
        session=SessionInfo.from_state(
            fresh,
            message_count=_session_message_count(session_id),
            total_cost=_session_total_cost(session_id),
            sandbox=sandbox,
        ),
        committed=result.committed,
        archive_path=result.archive_path,
        committed_at=result.committed_at.isoformat() if result.committed_at else None,
        trigger=result.trigger,
        reason=result.reason,
    )


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(
    session_id: str, user: Annotated[UserIdentity, Depends(require(Scope.sessions, Access.write))]
) -> None:
    state = _load_owned_state(session_id, user)
    server._engine.deactivate(session_id)
    await server._engine.sandbox_mgr.destroy_session(session_id)
    if server._session_archive.enabled and server._config.sessions.commit.delete_from_knowledge_on_session_delete:
        try:
            await server._session_archive.delete_session_archive(state)
        except Exception as exc:
            logger.warning(f"Session archive delete failed for {session_id}: {exc}")
    if not server._engine.session_mgr.delete_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found")


class PendingApprovalsResponse(BaseModel):
    # Heterogeneous payloads: each entry carries an "id" plus a "kind" and kind-specific fields,
    # mirroring what the WebSocket handler replays to connecting clients.
    approvals: list[dict[str, Any]] = []
    escalations: list[dict[str, Any]] = []


@router.get("/sessions/{session_id}/pending-approvals", response_model=PendingApprovalsResponse)
async def get_pending_approvals(
    session_id: str,
    user: Annotated[UserIdentity, Depends(require(Scope.sessions, Access.read))],
) -> PendingApprovalsResponse:
    """List approval/escalation requests the running turn is currently parked on (by id)."""
    _load_owned_state(session_id, user)
    active = server._engine.get_active(session_id)
    if active is None:
        return PendingApprovalsResponse()
    approvals = [
        {"id": pa.get("tool_call_id", ""), "kind": "tool", **{k: v for k, v in pa.items() if k != "type"}}
        for pa in active.pending_approval_requests
    ]
    escalations = [{"id": pe.get("request_id", ""), **pe} for pe in active.pending_escalations]
    return PendingApprovalsResponse(approvals=approvals, escalations=escalations)


# ----------------------------------------------------------------------
# Sandbox git (B1: /workspace clone ↔ backend repo)
# ----------------------------------------------------------------------


@router.get("/sessions/{session_id}/sandbox/git", response_model=SandboxGitStatus)
async def get_sandbox_git(
    session_id: str,
    user: Annotated[UserIdentity, Depends(require(Scope.sessions, Access.read))],
    fetch: Annotated[bool, Query()] = True,
) -> SandboxGitStatus:
    _load_owned_state(session_id, user)
    try:
        return await server._engine.sandbox_mgr.sandbox_git_status(session_id, fetch=fetch)
    except Exception as exc:
        logger.warning(f"Sandbox git status failed for {session_id}: {exc}")
        raise HTTPException(status_code=502, detail="Could not read sandbox git status") from exc


@router.post("/sessions/{session_id}/sandbox/git/pull", response_model=GitActionResult)
async def pull_sandbox_git(
    session_id: str, user: Annotated[UserIdentity, Depends(require(Scope.sessions, Access.write))]
) -> GitActionResult:
    _load_owned_state(session_id, user)
    return await server._engine.sandbox_mgr.sandbox_git_pull(session_id)


@router.post("/sessions/{session_id}/sandbox/git/push", response_model=GitActionResult)
async def push_sandbox_git(
    session_id: str, user: Annotated[UserIdentity, Depends(require(Scope.sessions, Access.write))]
) -> GitActionResult:
    _load_owned_state(session_id, user)
    return await server._engine.sandbox_mgr.sandbox_git_push(session_id)


# ----------------------------------------------------------------------
# Global git (B2: backend per-user repo ↔ external remote)
# ----------------------------------------------------------------------


@router.get("/git/status", response_model=GlobalGitStatus)
async def get_global_git(
    user: Annotated[UserIdentity, Depends(require(Scope.sessions, Access.read))],
) -> GlobalGitStatus:
    try:
        return await server._knowledge_git_runtime.status_for_user(user.username)
    except Exception as exc:
        logger.warning(f"Global git status failed for {user.username}: {exc}")
        raise HTTPException(status_code=502, detail="Could not read global git status") from exc


@router.post("/git/pull", response_model=GitActionResult)
async def pull_global_git(
    user: Annotated[UserIdentity, Depends(require(Scope.sessions, Access.write))],
) -> GitActionResult:
    try:
        ok, message = await server._knowledge_git_runtime.pull_for_user(user.username)
    except Exception as exc:
        return GitActionResult(ok=False, message=f"Pull failed: {exc}")
    return GitActionResult(ok=ok, message=message)


@router.post("/git/push", response_model=GitActionResult)
async def push_global_git(
    user: Annotated[UserIdentity, Depends(require(Scope.sessions, Access.write))],
) -> GitActionResult:
    try:
        ok, message = await server._knowledge_git_runtime.push_for_user(user.username)
    except Exception as exc:
        return GitActionResult(ok=False, message=f"Push failed: {exc}")
    return GitActionResult(ok=ok, message=message)
