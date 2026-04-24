from __future__ import annotations

from datetime import datetime
from pathlib import Path
from threading import RLock

import yaml
from pydantic import BaseModel

from carapace.sandbox.runtime import SandboxRuntimeKind, SandboxStatus


class SessionSandboxSnapshot(BaseModel):
    exists: bool = False
    runtime: SandboxRuntimeKind | None = None
    status: SandboxStatus = "missing"
    resource_id: str | None = None
    resource_kind: str | None = None
    storage_present: bool = False
    provisioned_bytes: int | None = None
    last_measured_used_bytes: int | None = None
    last_measured_at: datetime | None = None
    updated_at: datetime | None = None
    last_error: str | None = None


_snapshot_cache_lock = RLock()
_snapshot_cache: dict[Path, tuple[int | None, int | None, SessionSandboxSnapshot | None]] = {}


def load_sandbox_snapshot(path: Path) -> SessionSandboxSnapshot | None:
    resolved_path = path.resolve()
    if not resolved_path.exists():
        with _snapshot_cache_lock:
            _snapshot_cache[resolved_path] = (None, None, None)
        return None

    stat = resolved_path.stat()
    cache_key = (stat.st_mtime_ns, stat.st_size)
    with _snapshot_cache_lock:
        cached = _snapshot_cache.get(resolved_path)
        if cached is not None and cached[:2] == cache_key:
            snapshot = cached[2]
            return snapshot.model_copy(deep=True) if snapshot is not None else None

    with open(resolved_path) as f:
        raw = yaml.safe_load(f)
    if not raw:
        with _snapshot_cache_lock:
            _snapshot_cache[resolved_path] = (stat.st_mtime_ns, stat.st_size, None)
        return None

    snapshot = SessionSandboxSnapshot.model_validate(raw)
    with _snapshot_cache_lock:
        _snapshot_cache[resolved_path] = (stat.st_mtime_ns, stat.st_size, snapshot)
    return snapshot.model_copy(deep=True)


def save_sandbox_snapshot(path: Path, snapshot: SessionSandboxSnapshot) -> None:
    resolved_path = path.resolve()
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    with open(resolved_path, "w") as f:
        yaml.dump(snapshot.model_dump(mode="json"), f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    stat = resolved_path.stat()
    with _snapshot_cache_lock:
        _snapshot_cache[resolved_path] = (stat.st_mtime_ns, stat.st_size, snapshot.model_copy(deep=True))


def clear_sandbox_snapshot(path: Path) -> None:
    resolved_path = path.resolve()
    resolved_path.unlink(missing_ok=True)
    with _snapshot_cache_lock:
        _snapshot_cache[resolved_path] = (None, None, None)
