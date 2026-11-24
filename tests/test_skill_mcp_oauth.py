"""Tests for OAuth MCP auth (refresh + vault write-back) and MCP prewarm/degradation."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from carapace.agent.tools import _prewarm_skill_mcp
from carapace.credentials.protocol import CredentialBackendError
from carapace.models.skills import ContextGrant, SkillCarapaceConfig, SkillMcpDecl, SkillMcpOAuthAuth

# ── Model ───────────────────────────────────────────────────────────


class TestOAuthDecl:
    def test_oauth_http_valid(self):
        cfg = SkillCarapaceConfig.model_validate(
            {
                "mcp": [
                    {"name": "idealo", "url": "https://mcp.example/mcp", "auth": {"type": "oauth", "vault_path": "v/o"}}
                ]
            }
        )
        assert isinstance(cfg.mcp[0].auth, SkillMcpOAuthAuth)

    def test_oauth_on_stdio_rejected(self):
        with pytest.raises(ValidationError):
            SkillMcpDecl(name="x", command="run", auth=SkillMcpOAuthAuth(vault_path="v/o"))


# ── Prewarm / graceful degradation ──────────────────────────────────


class TestPrewarm:
    async def test_success_caches_and_reports_ready(self):
        decl = SkillMcpDecl(name="srv", url="https://e.example/mcp")
        ctx = MagicMock()
        ctx.deps.mcp_toolsets = {}
        grant = ContextGrant(skill_name="s", mcp_servers=[decl])
        with patch("carapace.agent.tools._build_one_mcp_toolset", AsyncMock(return_value=MagicMock())):
            lines = await _prewarm_skill_mcp(ctx, "s", grant)
        assert "s:srv" in ctx.deps.mcp_toolsets
        assert any("ready" in ln and "srv_*" in ln for ln in lines)

    async def test_failure_reports_unavailable_without_raising(self):
        decl = SkillMcpDecl(name="srv", url="https://e.example/mcp")
        ctx = MagicMock()
        ctx.deps.mcp_toolsets = {}
        grant = ContextGrant(skill_name="s", mcp_servers=[decl])
        with patch(
            "carapace.agent.tools._build_one_mcp_toolset",
            AsyncMock(side_effect=CredentialBackendError("token expired")),
        ):
            lines = await _prewarm_skill_mcp(ctx, "s", grant)
        assert "s:srv" not in ctx.deps.mcp_toolsets
        assert any("UNAVAILABLE" in ln and "token expired" in ln for ln in lines)
