from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, model_validator


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


# What a skill needs from outside the sandbox is declared in its flake now (docs/skill-flakes.md).
_MOVED_TO_FLAKE = ("network", "credentials", "commands")


class SkillCarapaceConfig(BaseModel):
    """Parsed carapace config declared inline in SKILL.md frontmatter."""

    disabled: Annotated[bool, Field(strict=True)] = False
    mcp: list[SkillMcpDecl] = []
    hints: dict[str, str] = {}

    @model_validator(mode="before")
    @classmethod
    def _reject_moved_declarations(cls, data: Any) -> Any:
        # Ignoring them would leave a skill that looks declared and gets nothing.
        if isinstance(data, dict) and (moved := [key for key in _MOVED_TO_FLAKE if key in data]):
            raise ValueError(
                f"{', '.join(moved)} moved out of the frontmatter into the skill's flake "
                "(mkSkill needs, see docs/skill-flakes.md)"
            )
        return data

    @model_validator(mode="after")
    def _validate_mcp(self) -> SkillCarapaceConfig:
        seen_mcp: set[str] = set()
        for server in self.mcp:
            if server.name in seen_mcp:
                raise ValueError(f"duplicate skill mcp name {server.name!r} is not allowed")
            seen_mcp.add(server.name)
        return self


class SkillInfo(BaseModel):
    name: str
    description: str = ""
    path: Path
