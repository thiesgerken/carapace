from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..api_keys import Access, Scope
from ..auth import UserIdentity
from ..memory.models import MemoryBudgetNotice, OpenLoop, ThisWeek
from .auth import require
from .state import server_module

server = server_module()
router = APIRouter()

# Almost everything on the home page comes from memory, which shares the knowledge scope.
_Reader = Annotated[UserIdentity, Depends(require(Scope.knowledge, Access.read))]
_Writer = Annotated[UserIdentity, Depends(require(Scope.knowledge, Access.write))]


class PendingApproval(BaseModel):
    session_id: str
    session_title: str | None


class HomeNotices(BaseModel):
    pending_approvals: list[PendingApproval]
    failed_memory_tasks: int
    outdated_memory_records: int
    memory_budget: MemoryBudgetNotice | None


class HomeResponse(BaseModel):
    open_loops: list[OpenLoop]
    this_week: ThisWeek | None
    notices: HomeNotices


@router.get("/home", response_model=HomeResponse)
async def get_home(user: _Reader) -> HomeResponse:
    memory = server._memory_service
    return HomeResponse(
        open_loops=memory.open_loops(user.username),
        this_week=memory.this_week(user.username),
        notices=HomeNotices(
            pending_approvals=[
                PendingApproval(session_id=state.session_id, session_title=state.title)
                for state in server._engine.sessions_awaiting_approval(user.username)
            ],
            failed_memory_tasks=memory.failed_task_count(user.username),
            outdated_memory_records=memory.outdated_record_count(user.username),
            memory_budget=memory.budget_notice(user.username),
        ),
    )


@router.post("/home/open-loops/{loop_id}/dismiss", status_code=204)
async def dismiss_open_loop(loop_id: str, user: _Writer) -> None:
    if not server._memory_service.dismiss_loop(user.username, loop_id):
        raise HTTPException(status_code=404, detail="Open loop not found")


@router.delete("/home/open-loops/{loop_id}/dismiss", status_code=204)
async def undismiss_open_loop(loop_id: str, user: _Writer) -> None:
    # No 404 for a missing row: the undo must keep working once the loop itself has aged out.
    server._memory_service.undismiss_loop(user.username, loop_id)
