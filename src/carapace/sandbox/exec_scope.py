"""What one running exec has been granted. Its own module so that every sandbox layer can name it."""

from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass, field

from ..models.credentials import CredentialValueKind, OAuthAccessTokenKind
from .tunnels import Tunnel

# What an approved credential request covers: a vault path in one representation, or a listing (no kind).
type CredentialGrant = tuple[str, CredentialValueKind | OAuthAccessTokenKind | None]


@dataclass(eq=False, slots=True)
class RunningExec:
    """The scope of one exec, captured when a request arrives: approvals land in it only while it still runs."""

    session_id: str
    command: str
    domains: set[str]
    credentials: set[CredentialGrant]
    # Once the sentinel has seen this exec in a boundary decision, its later requests are short follow-ups.
    boundary_reviewed: bool = False
    # Names this exec where the security layer must tell it from the next one, e.g. its domain decisions.
    exec_id: str = field(default_factory=lambda: secrets.token_hex(8))
    # Vault paths whose OAuth access token this exec already forced a refresh of: one each, after a 401.
    oauth_refreshed: set[str] = field(default_factory=set)
    # Open tunnels and the loopback address each listens on; they close when the exec ends.
    tunnels: dict[Tunnel, str] = field(default_factory=dict)
    # Opening and closing tunnels both edit /etc/hosts in the sandbox, so they take turns.
    tunnel_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
