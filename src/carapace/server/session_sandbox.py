from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..api_keys import Access, Scope
from ..auth import UserIdentity
from ..sandbox.manager import UploadError, UploadTooLargeError
from ..sandbox.state import SessionSandboxSnapshot
from ..session import sent_files
from .auth import require
from .state import server_module

MAX_UPLOAD_BYTES = 50 * 1024 * 1024

server = server_module()

router = APIRouter()


def _load_owned_session(session_id: str, user: UserIdentity):
    state = server._engine.session_mgr.load_state(session_id)
    if state is None or not server._engine.session_mgr.is_owned_by(session_id, user.username):
        raise HTTPException(status_code=404, detail="Session not found")
    return state


@router.get("/sessions/{session_id}/sandbox", response_model=SessionSandboxSnapshot)
async def get_session_sandbox(
    session_id: str,
    user: Annotated[UserIdentity, Depends(require(Scope.sessions, Access.read))],
) -> SessionSandboxSnapshot:
    _load_owned_session(session_id, user)
    snapshot = server._engine.session_mgr.load_sandbox_snapshot(session_id)
    return snapshot or SessionSandboxSnapshot()


@router.post("/sessions/{session_id}/sandbox/up", response_model=SessionSandboxSnapshot)
async def start_session_sandbox(
    session_id: str,
    user: Annotated[UserIdentity, Depends(require(Scope.sessions, Access.write))],
) -> SessionSandboxSnapshot:
    state = _load_owned_session(session_id, user)
    if state.attributes.archived:
        raise HTTPException(status_code=409, detail="Archived sessions must be unarchived before use")
    if server._engine.is_agent_running(session_id):
        raise HTTPException(status_code=409, detail="Cannot start sandbox while an agent turn is running")
    await server._engine.sandbox_mgr.ensure_session(session_id)
    snapshot = server._engine.session_mgr.load_sandbox_snapshot(session_id)
    return snapshot or SessionSandboxSnapshot()


@router.post("/sessions/{session_id}/sandbox/down", response_model=SessionSandboxSnapshot)
async def stop_session_sandbox(
    session_id: str,
    user: Annotated[UserIdentity, Depends(require(Scope.sessions, Access.write))],
) -> SessionSandboxSnapshot:
    state = _load_owned_session(session_id, user)
    if state.attributes.archived:
        raise HTTPException(status_code=409, detail="Archived sessions must be unarchived before use")
    if server._engine.is_agent_running(session_id):
        raise HTTPException(status_code=409, detail="Cannot scale down sandbox while an agent turn is running")
    await server._engine.sandbox_mgr.cleanup_session(session_id)
    snapshot = server._engine.session_mgr.load_sandbox_snapshot(session_id)
    return snapshot or SessionSandboxSnapshot()


class UploadedFile(BaseModel):
    name: str
    path: str
    file_id: str
    size: int
    mime: str


@router.post("/sessions/{session_id}/sandbox/files", response_model=UploadedFile)
async def upload_session_sandbox_file(
    session_id: str,
    user: Annotated[UserIdentity, Depends(require(Scope.sessions, Access.write))],
    file: Annotated[UploadFile, File()],
) -> UploadedFile:
    state = _load_owned_session(session_id, user)
    if state.attributes.archived:
        raise HTTPException(status_code=409, detail="Archived sessions must be unarchived before use")
    # Start (warm-claim or cold-create) the sandbox if it isn't running yet; the file is
    # streamed straight into it, so it must be live. Idempotent when already running.
    await server._engine.sandbox_mgr.ensure_session(session_id)
    filename = file.filename or "upload"

    # Persist a server-side copy as the bytes stream into the sandbox, so the file stays
    # downloadable after the sandbox is gone. The tee avoids a second base64 round-trip.
    data_dir = server._engine.session_mgr.data_dir
    file_id, dest = sent_files.reserve(data_dir, session_id, filename)
    written = 0
    handle = dest.open("wb")

    async def tee_read(n: int) -> bytes:
        nonlocal written
        chunk = await file.read(n)
        if chunk:
            handle.write(chunk)
            written += len(chunk)
        return chunk

    try:
        path = await server._engine.sandbox_mgr.upload_tmp_file(
            session_id,
            filename,
            tee_read,
            max_bytes=MAX_UPLOAD_BYTES,
        )
    except BaseException as exc:
        # Any failure (size limit, write error, stopped sandbox, I/O) must not leave a
        # sidecar-less blob behind in sessions/{id}/files/.
        handle.close()
        dest.unlink(missing_ok=True)
        if isinstance(exc, UploadTooLargeError):
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        if isinstance(exc, UploadError):
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        raise
    finally:
        if not handle.closed:
            handle.close()

    info = sent_files.finalize(data_dir, session_id, file_id, filename, written)
    return UploadedFile(name=filename, path=path, file_id=info.file_id, size=info.size, mime=info.mime)


@router.get("/sessions/{session_id}/files/{file_id}")
async def download_sent_file(
    session_id: str,
    file_id: str,
    user: Annotated[UserIdentity, Depends(require(Scope.sessions, Access.read))],
    download: Annotated[bool, Query()] = False,
) -> FileResponse:
    _load_owned_session(session_id, user)
    resolved = sent_files.resolve(server._engine.session_mgr.data_dir, session_id, file_id)
    if resolved is None:
        raise HTTPException(status_code=404, detail="File not found")
    blob, info = resolved
    inline = not download and info.mime in sent_files.INLINE_MIME_TYPES
    return FileResponse(
        blob,
        media_type=info.mime if inline else "application/octet-stream",
        filename=info.name,
        content_disposition_type="inline" if inline else "attachment",
    )


@router.post("/sessions/{session_id}/sandbox/wipe", response_model=SessionSandboxSnapshot)
async def wipe_session_sandbox(
    session_id: str,
    user: Annotated[UserIdentity, Depends(require(Scope.sessions, Access.write))],
) -> SessionSandboxSnapshot:
    state = _load_owned_session(session_id, user)
    if state.attributes.archived:
        raise HTTPException(status_code=409, detail="Archived sessions must be unarchived before use")
    if server._engine.is_agent_running(session_id):
        raise HTTPException(status_code=409, detail="Cannot wipe sandbox while an agent turn is running")
    await server._engine.sandbox_mgr.reset_session(session_id)
    snapshot = server._engine.session_mgr.load_sandbox_snapshot(session_id)
    return snapshot or SessionSandboxSnapshot()
