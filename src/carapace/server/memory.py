from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from ..api_keys import Access, Scope
from ..auth import UserIdentity
from ..memory.models import (
    Confidence,
    DigestLevel,
    Durability,
    EstimateTotal,
    ExtractionState,
    FactCategory,
    FactFilter,
    FactListResponse,
    FactSourceKind,
    MemoryStatus,
    OutdatedReason,
    PeriodDetail,
    PeriodTree,
    SessionMemoryDetail,
    SessionMemoryFilter,
    SessionMemoryListResponse,
    TaskCountResponse,
    TaskFilter,
    TaskIdsRequest,
    TaskKind,
    TaskListResponse,
    TaskRunRequest,
    TaskSelection,
    TaskSpawnRequest,
    TaskSpawnResponse,
    TaskStatus,
)
from ..memory.service import MemoryService
from .auth import require
from .state import server_module

server = server_module()
router = APIRouter(prefix="/memory")

# Memory is distilled from the knowledge repo, so it shares the knowledge scope.
_Reader = Annotated[UserIdentity, Depends(require(Scope.knowledge, Access.read))]
_Writer = Annotated[UserIdentity, Depends(require(Scope.knowledge, Access.write))]


def _service() -> MemoryService:
    return server._memory_service


@router.get("/status", response_model=MemoryStatus)
async def get_status(user: _Reader) -> MemoryStatus:
    return await _service().status(user.username)


@router.get("/tasks", response_model=TaskListResponse)
async def list_tasks(
    user: _Reader,
    status: Annotated[list[TaskStatus] | None, Query()] = None,
    kind: Annotated[list[TaskKind] | None, Query()] = None,
    period: str | None = None,
    model: str | None = None,
    cursor: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> TaskListResponse:
    task_filter = TaskFilter(status=status, kind=kind, period=period, model=model)
    return await _service().list_tasks(user.username, task_filter, cursor, limit)


@router.post("/tasks/estimate", response_model=EstimateTotal)
async def estimate_tasks(body: TaskRunRequest, user: _Reader) -> EstimateTotal:
    return await _service().estimate_tasks(user.username, body)


@router.post("/tasks/run", response_model=TaskCountResponse)
async def run_tasks(body: TaskRunRequest, user: _Writer) -> TaskCountResponse:
    return await _service().run_tasks(user.username, body)


@router.post("/tasks/cancel", response_model=TaskCountResponse)
async def cancel_tasks(body: TaskSelection, user: _Writer) -> TaskCountResponse:
    return await _service().cancel_tasks(user.username, body)


@router.post("/tasks/retry", response_model=TaskCountResponse)
async def retry_tasks(body: TaskIdsRequest, user: _Writer) -> TaskCountResponse:
    return await _service().retry_tasks(user.username, body.ids)


@router.post("/tasks/spawn", response_model=TaskSpawnResponse)
async def spawn_tasks(body: TaskSpawnRequest, user: _Writer) -> TaskSpawnResponse:
    return await _service().spawn_tasks(user.username, body)


@router.get("/sessions", response_model=SessionMemoryListResponse)
async def list_sessions(
    user: _Reader,
    week: str | None = None,
    state: Annotated[list[ExtractionState] | None, Query()] = None,
    task_status: Annotated[list[TaskStatus] | None, Query()] = None,
    model: str | None = None,
    channel: str | None = None,
    outdated_reason: OutdatedReason | None = None,
    cursor: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> SessionMemoryListResponse:
    session_filter = SessionMemoryFilter(
        week=week,
        state=state,
        task_status=task_status,
        model=model,
        channel=channel,
        outdated_reason=outdated_reason,
    )
    return await _service().list_sessions(user.username, session_filter, cursor, limit)


@router.get("/sessions/{session_id}", response_model=SessionMemoryDetail)
async def get_session(session_id: str, user: _Reader) -> SessionMemoryDetail:
    detail = await _service().session_detail(user.username, session_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return detail


@router.get("/periods", response_model=PeriodTree)
async def get_periods(user: _Reader) -> PeriodTree:
    return await _service().periods(user.username)


@router.get("/periods/{level}/{key}", response_model=PeriodDetail)
async def get_period(level: DigestLevel, key: str, user: _Reader) -> PeriodDetail:
    detail = await _service().period_detail(user.username, level, key)
    if detail is None:
        raise HTTPException(status_code=404, detail="Period not found")
    return detail


@router.get("/facts", response_model=FactListResponse)
async def list_facts(
    user: _Reader,
    category: Annotated[list[FactCategory] | None, Query()] = None,
    subject: str | None = None,
    confidence: Annotated[list[Confidence] | None, Query()] = None,
    durability: Annotated[list[Durability] | None, Query()] = None,
    source_kind: Annotated[list[FactSourceKind] | None, Query()] = None,
    period: str | None = None,
) -> FactListResponse:
    fact_filter = FactFilter(
        category=category,
        subject=subject,
        confidence=confidence,
        durability=durability,
        source_kind=source_kind,
        period=period,
    )
    return await _service().facts(user.username, fact_filter)
