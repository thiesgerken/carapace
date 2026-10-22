"""Persistent storage for files the agent exposes to the user via ``send_file``.

The sandbox ``/tmp`` and the container die on scale-down, so a "sent" file is copied
out of the sandbox into ``data_dir/sessions/{session_id}/files/`` where it survives
sandbox shutdown and history replay. Each file is stored as ``{file_id}{ext}`` next to a
``{file_id}.json`` sidecar holding its :class:`SentFileInfo` metadata.
"""

from __future__ import annotations

import mimetypes
import re
import secrets
from pathlib import Path

from ..models.tooling import SentFileInfo

_FILE_ID_RE = re.compile(r"^[0-9a-f]{16}$")

# Types safe to render inline on the app origin. SVG is deliberately absent: it
# carries script.
INLINE_MIME_TYPES = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp", "image/avif"})


def files_dir(data_dir: Path, session_id: str) -> Path:
    return data_dir / "sessions" / session_id / "files"


def guess_mime(name: str) -> str:
    mime, _ = mimetypes.guess_type(name)
    return mime or "application/octet-stream"


def reserve(data_dir: Path, session_id: str, name: str) -> tuple[str, Path]:
    """Allocate a ``file_id`` + destination path for *name* (blob not yet written)."""
    file_id = secrets.token_hex(8)
    ext = Path(name).suffix
    target_dir = files_dir(data_dir, session_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    return file_id, target_dir / f"{file_id}{ext}"


def finalize(data_dir: Path, session_id: str, file_id: str, name: str, size: int) -> SentFileInfo:
    """Write the sidecar for an already-stored blob and return its metadata."""
    info = SentFileInfo(file_id=file_id, name=name, mime=guess_mime(name), size=size)
    sidecar = files_dir(data_dir, session_id) / f"{file_id}.json"
    sidecar.write_text(info.model_dump_json())
    return info


def resolve(data_dir: Path, session_id: str, file_id: str) -> tuple[Path, SentFileInfo] | None:
    """Return ``(blob_path, info)`` for *file_id*, or ``None`` if unknown/invalid."""
    if not _FILE_ID_RE.match(file_id):
        return None
    target_dir = files_dir(data_dir, session_id)
    sidecar = target_dir / f"{file_id}.json"
    if not sidecar.exists():
        return None
    info = SentFileInfo.model_validate_json(sidecar.read_text())
    blob = target_dir / f"{file_id}{Path(info.name).suffix}"
    if not blob.exists():
        return None
    return blob, info
