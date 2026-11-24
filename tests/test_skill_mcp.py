"""Tests for skill-declared MCP server connections."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from carapace.models.skills import (
    SkillCarapaceConfig,
    SkillMcpBearerAuth,
    SkillMcpDecl,
)

# ── Models ──────────────────────────────────────────────────────────


class TestSkillMcpDecl:
    def test_valid(self):
        decl = SkillMcpDecl(
            name="linear",
            url="https://mcp.linear.app/mcp",
            auth=SkillMcpBearerAuth(vault_path="dev/linear-token"),
        )
        assert decl.auth is not None and decl.auth.type == "bearer"
        assert decl.display == "linear (https://mcp.linear.app/mcp)"

    def test_auth_optional(self):
        decl = SkillMcpDecl(name="local", url="http://localhost:8000/mcp")
        assert decl.auth is None

    @pytest.mark.parametrize("name", ["1abc", "with-dash", "with.dot", "with space", ""])
    def test_invalid_name(self, name: str):
        with pytest.raises(ValidationError):
            SkillMcpDecl(name=name, url="https://example.com/mcp")

    @pytest.mark.parametrize("url", ["ftp://example.com", "example.com/mcp", "file:///tmp/x"])
    def test_invalid_url(self, url: str):
        with pytest.raises(ValidationError):
            SkillMcpDecl(name="ok", url=url)

    def test_auth_from_yaml_shape(self):
        cfg = SkillCarapaceConfig.model_validate(
            {"mcp": [{"name": "l", "url": "https://x.example/mcp", "auth": {"type": "bearer", "vault_path": "dev/t"}}]}
        )
        assert cfg.mcp[0].auth is not None and cfg.mcp[0].auth.vault_path == "dev/t"

    def test_duplicate_names_rejected(self):
        with pytest.raises(ValidationError):
            SkillCarapaceConfig.model_validate(
                {"mcp": [{"name": "a", "url": "https://x.example/mcp"}, {"name": "a", "url": "https://y.example/mcp"}]}
            )


# ── Toolset factory ─────────────────────────────────────────────────


# ── process_tool_call gating ────────────────────────────────────────


# ── Duplicate MCP name conflict (issue #2) ──────────────────────────


# ── Activation prewarm reports honest status (issue #1) ─────────────
