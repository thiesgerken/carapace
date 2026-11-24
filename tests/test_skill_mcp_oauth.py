"""Tests for OAuth MCP auth (refresh + vault write-back) and MCP prewarm/degradation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from carapace.models.skills import SkillCarapaceConfig, SkillMcpDecl, SkillMcpOAuthAuth

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
