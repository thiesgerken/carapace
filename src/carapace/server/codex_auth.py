from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from pydantic_ai.providers.openai_codex import CredentialsRefreshError

from ..api_keys import Access, Scope
from ..auth import UserIdentity
from ..codex_auth import CodexConnection, CodexLoginError
from .auth import require
from .state import server_module

server = server_module()
router = APIRouter()


class CodexModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CodexStatusResponse(CodexModel):
    connected: bool
    email: str | None = None
    updated_at: datetime | None = None


class CodexLoginStartResponse(CodexModel):
    authorize_url: str


class CodexLoginCompleteRequest(CodexModel):
    # The localhost URL the browser was redirected to after the ChatGPT login. The redirect URI is
    # pinned to localhost by OpenAI, so a remote server never receives the callback itself.
    redirect_url: str


def _status(connection: CodexConnection | None) -> CodexStatusResponse:
    if connection is None:
        return CodexStatusResponse(connected=False)
    return CodexStatusResponse(connected=True, email=connection.email, updated_at=connection.updated_at)


@router.get("/user/codex", response_model=CodexStatusResponse)
async def get_codex_status(
    user: Annotated[UserIdentity, Depends(require(Scope.preferences, Access.read))],
) -> CodexStatusResponse:
    return _status(server._codex_accounts.connection(user.username))


@router.post("/user/codex/login", response_model=CodexLoginStartResponse)
async def start_codex_login(
    user: Annotated[UserIdentity, Depends(require(Scope.preferences, Access.write))],
) -> CodexLoginStartResponse:
    return CodexLoginStartResponse(authorize_url=server._codex_accounts.start_login(user.username))


@router.post("/user/codex/login/complete", response_model=CodexStatusResponse)
async def complete_codex_login(
    body: CodexLoginCompleteRequest,
    user: Annotated[UserIdentity, Depends(require(Scope.preferences, Access.write))],
) -> CodexStatusResponse:
    try:
        connection = await server._codex_accounts.complete_login(user.username, body.redirect_url)
    except (CodexLoginError, CredentialsRefreshError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    server._engine.reset_user_models(user.username)
    return _status(connection)


@router.delete("/user/codex", status_code=204)
async def disconnect_codex(
    user: Annotated[UserIdentity, Depends(require(Scope.preferences, Access.write))],
) -> None:
    if not server._codex_accounts.disconnect(user.username):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No ChatGPT subscription is connected")
    server._engine.reset_user_models(user.username)
