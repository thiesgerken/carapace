from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, model_validator

from ..sandbox.runtime import NetworkTunnel


class SkillCredentialDecl(BaseModel):
    """A credential requirement declared in a skill's carapace metadata."""

    vault_path: str
    description: str = ""
    env_var: str | None = None
    file: str | None = None
    base64: Annotated[
        bool, Field(description="If true, the stored value is base64-encoded and will be decoded before injection.")
    ] = False


class SkillNetworkConfig(BaseModel):
    domains: list[str] = []
    tunnels: list[NetworkTunnel] = []

    @model_validator(mode="after")
    def _validate_tunnels(self) -> SkillNetworkConfig:
        seen_local_ports: set[int] = set()
        seen_endpoints: set[tuple[str, int]] = set()
        for tunnel in self.tunnels:
            if tunnel.local_port in seen_local_ports:
                raise ValueError(f"network.tunnels local_port {tunnel.local_port} must be unique within a skill")
            endpoint = (tunnel.host, tunnel.remote_port)
            if endpoint in seen_endpoints:
                raise ValueError(
                    f"network.tunnels duplicate endpoint {tunnel.host}:{tunnel.remote_port} is not allowed"
                )
            seen_local_ports.add(tunnel.local_port)
            seen_endpoints.add(endpoint)
        return self


_SKILL_COMMAND_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class SkillCommandDecl(BaseModel):
    """A command alias declared in a skill's carapace metadata."""

    name: str
    command: str

    @model_validator(mode="after")
    def _validate(self) -> SkillCommandDecl:
        if not _SKILL_COMMAND_NAME_RE.match(self.name):
            raise ValueError(
                "skill command name must start with an alphanumeric character and contain only letters, "
                "numbers, dots, underscores, or hyphens"
            )

        command = self.command.strip()
        if not command:
            raise ValueError("skill command must not be empty")
        if "\n" in command or "\r" in command:
            raise ValueError("skill command must be a single line")

        self.command = command
        return self


class SkillMcpBearerAuth(BaseModel):
    """Static bearer token auth for an MCP server; the token is read from the vault."""

    type: Literal["bearer"] = "bearer"
    vault_path: str


class SkillMcpOAuthAuth(BaseModel):
    """OAuth 2.0 auth for an MCP server (refresh-token grant).

    ``vault_path`` points to a JSON state blob in the vault with fields:
    ``token_url``, ``client_id``, optional ``client_secret``, ``refresh_token``,
    and optional ``access_token`` / ``expires_at`` (epoch seconds) / ``scope``.
    carapace refreshes the access token when it is missing or near expiry and
    writes the updated blob back to the vault (token rotation). The one-time
    authorization that produces the initial ``refresh_token`` is done
    out-of-band; see docs/skills.md.
    """

    type: Literal["oauth"] = "oauth"
    vault_path: str


# Discriminated union so further auth methods can be added as new variants.
SkillMcpAuth = Annotated[SkillMcpBearerAuth | SkillMcpOAuthAuth, Field(discriminator="type")]

_SKILL_MCP_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


class SkillMcpDecl(BaseModel):
    """An MCP server connection declared in a skill's carapace metadata.

    ``name`` doubles as the tool-name prefix: the server's tools are exposed to
    the agent as ``<name>_<tool>`` while the skill is active.

    A declaration is one of two transports:

    - **HTTP** — set ``url`` (streamable HTTP); optional ``auth`` (bearer token
      from the vault). The connection is made by the backend process.
    - **stdio** — set ``command`` (a shell command that starts the server); the
      process runs inside the sandbox, one spawn per operation, bridged by
      ``carapace-mcp-bridge``. The server inherits the skill's context-injected
      credentials (declare them under ``credentials`` with an ``env_var``), so
      ``auth`` does not apply.
    """

    name: str
    url: str | None = None
    command: str | None = None
    description: str = ""
    auth: SkillMcpAuth | None = None

    @model_validator(mode="after")
    def _validate(self) -> SkillMcpDecl:
        if not _SKILL_MCP_NAME_RE.match(self.name):
            raise ValueError(
                "skill mcp name must start with a letter and contain only letters, numbers, or underscores"
            )
        if bool(self.url) == bool(self.command):
            raise ValueError("skill mcp declaration must set exactly one of 'url' (HTTP) or 'command' (stdio)")
        if self.url is not None and not self.url.startswith(("http://", "https://")):
            raise ValueError("skill mcp url must be an http(s) URL")
        if self.command is not None and self.auth is not None:
            raise ValueError("skill mcp 'auth' applies to HTTP servers only; stdio servers use skill credentials")
        return self

    @property
    def is_stdio(self) -> bool:
        return self.command is not None

    @property
    def display(self) -> str:
        target = self.command if self.is_stdio else self.url
        prefix = "stdio: " if self.is_stdio else ""
        return f"{self.name} ({prefix}{target})"


class SkillCarapaceConfig(BaseModel):
    """Parsed carapace config declared inline in SKILL.md frontmatter."""

    disabled: Annotated[bool, Field(strict=True)] = False
    network: SkillNetworkConfig = SkillNetworkConfig()
    credentials: list[SkillCredentialDecl] = []
    commands: list[SkillCommandDecl] = []
    mcp: list[SkillMcpDecl] = []
    hints: dict[str, str] = {}

    @model_validator(mode="after")
    def _validate_commands(self) -> SkillCarapaceConfig:
        seen_names: set[str] = set()
        for command in self.commands:
            if command.name in seen_names:
                raise ValueError(f"duplicate skill command name {command.name!r} is not allowed")
            seen_names.add(command.name)
        seen_mcp: set[str] = set()
        for server in self.mcp:
            if server.name in seen_mcp:
                raise ValueError(f"duplicate skill mcp name {server.name!r} is not allowed")
            seen_mcp.add(server.name)
        return self


class ContextGrant(BaseModel):
    """Context-scoped grant for a skill's declared domains, tunnels, and credentials.

    Registered at ``use_skill`` time, keyed by skill name.  The agent must pass
    matching ``contexts`` on ``exec`` for these grants to take effect.
    """

    skill_name: str
    domains: set[str] = set()
    tunnels: list[NetworkTunnel] = []
    credential_decls: list[SkillCredentialDecl] = []
    credential_names: dict[str, str] = {}  # vault_path → human-readable name
    mcp_servers: list[SkillMcpDecl] = []

    @property
    def vault_paths(self) -> set[str]:
        return {c.vault_path for c in self.credential_decls}


def context_grants_session_summary(
    session_id: str,
    context_grants: Mapping[str, ContextGrant],
    get_cached_credential: Callable[[str, str], str | None],
) -> dict[str, dict[str, Any]]:
    """Build per-skill ``context_grants`` payload for ``/session`` (all channels)."""
    summary: dict[str, dict[str, Any]] = {}
    for skill, grant in context_grants.items():
        cached = sum(1 for vp in grant.vault_paths if get_cached_credential(session_id, vp) is not None)
        summary[skill] = {
            "domains": sorted(grant.domains),
            "tunnels": [tunnel.display for tunnel in grant.tunnels],
            "vault_paths": sorted(grant.vault_paths),
            "cached_credentials": cached,
            "mcp_servers": [server.display for server in grant.mcp_servers],
        }
    return summary


class SkillInfo(BaseModel):
    name: str
    description: str = ""
    path: Path
