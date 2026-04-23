from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel

SandboxRuntimeKind = Literal["docker", "kubernetes"]
SandboxStatus = Literal["running", "scaled_down", "stopped", "missing", "pending", "error"]


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


def load_sandbox_snapshot(path: Path) -> SessionSandboxSnapshot | None:
    if not path.exists():
        return None
    with open(path) as f:
        raw = yaml.safe_load(f)
    if not raw:
        return None
    return SessionSandboxSnapshot.model_validate(raw)


def save_sandbox_snapshot(path: Path, snapshot: SessionSandboxSnapshot) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        yaml.dump(snapshot.model_dump(mode="json"), f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def clear_sandbox_snapshot(path: Path) -> None:
    path.unlink(missing_ok=True)
