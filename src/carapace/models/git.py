from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class SandboxGitStatus(BaseModel):
    """Ahead/behind of the sandbox ``/workspace`` clone vs the backend repo (B1)."""

    running: bool = True
    branch: str | None = None
    upstream: bool = False
    ahead: int | None = None
    behind: int | None = None
    fetched: bool = False


class GlobalGitStatus(BaseModel):
    """Ahead/behind of the backend per-user repo vs the external remote (B2)."""

    remote_configured: bool = False
    ahead: int = 0
    behind: int = 0
    # Short hash and subject of the local HEAD; None while the repo has no commits.
    head: str | None = None
    head_subject: str | None = None


class SessionArtifactChange(BaseModel):
    """What one session's commits did to an artifact's ``index.html``."""

    slug: str
    created: bool
    last_changed: datetime


class FileCommit(BaseModel):
    """Newest commit touching a given path."""

    # Full hash for copying; `short` is git's own abbreviation, which is repo-dependent
    # and so cannot be reproduced by truncating the full one.
    hash: str
    short: str
    subject: str
    committed_at: datetime


class GitActionResult(BaseModel):
    """Result of a pull/push action."""

    ok: bool
    message: str
    denied: bool = False
