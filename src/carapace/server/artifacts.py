from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..artifact_shares import ArtifactShare
from ..auth import UserIdentity
from .artifact_rendering import artifact_headers
from .auth import require_browser_session
from .knowledge import resolve_artifact_index, validate_artifact_slug
from .state import server_module

server = server_module()
router = APIRouter()


class ArtifactShareState(BaseModel):
    url: str | None
    shared_at: datetime | None


def _share_state(share: ArtifactShare | None) -> ArtifactShareState:
    if share is None or share.share_token is None:
        return ArtifactShareState(url=None, shared_at=None)
    return ArtifactShareState(url=f"/api/public/a/{share.share_token}", shared_at=share.shared_at)


@router.get("/artifacts/{slug}/share")
async def get_artifact_share(
    slug: str,
    user: Annotated[UserIdentity, Depends(require_browser_session)],
) -> ArtifactShareState:
    validate_artifact_slug(slug)
    return _share_state(server._artifact_share_store.get(user.username, slug))


@router.put("/artifacts/{slug}/share")
async def enable_artifact_share(
    slug: str,
    user: Annotated[UserIdentity, Depends(require_browser_session)],
) -> ArtifactShareState:
    handle = server._knowledge_repo_registry.get_for_user(user.username)
    resolve_artifact_index(handle.knowledge_dir.resolve(), slug)
    return _share_state(server._artifact_share_store.enable(user.username, slug))


@router.delete("/artifacts/{slug}/share")
async def disable_artifact_share(
    slug: str,
    user: Annotated[UserIdentity, Depends(require_browser_session)],
) -> ArtifactShareState:
    # Revocation must still work after the artifact is deleted or renamed.
    validate_artifact_slug(slug)
    server._artifact_share_store.disable(user.username, slug)
    return ArtifactShareState(url=None, shared_at=None)


@router.get("/public/a/{token}")
async def public_artifact(token: str) -> FileResponse:
    headers = {
        **artifact_headers(),
        "Referrer-Policy": "no-referrer",
        "Cache-Control": "no-store",
    }
    share = server._artifact_share_store.resolve(token)
    if share is None:
        raise HTTPException(status_code=404, detail="Not Found", headers=headers)
    handle = server._knowledge_repo_registry.get_for_user(share.owner)
    try:
        target = resolve_artifact_index(handle.knowledge_dir.resolve(), share.slug)
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
        raise HTTPException(status_code=404, detail="Not Found", headers=headers) from exc
    return FileResponse(target, media_type="text/html", headers=headers)
