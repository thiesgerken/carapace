"""Tests for skill-declared stdio MCP servers (bridged through the sandbox)."""

from __future__ import annotations

import base64
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from pydantic import ValidationError

from carapace.models.skills import SkillCarapaceConfig, SkillMcpBearerAuth, SkillMcpDecl

BRIDGE = Path(__file__).resolve().parents[1] / "sandbox" / "carapace-mcp-bridge"

# ── Model ───────────────────────────────────────────────────────────


class TestStdioDecl:
    def test_valid_stdio(self):
        decl = SkillMcpDecl(name="fs", command="npx -y server-filesystem /tmp")
        assert decl.is_stdio
        assert decl.url is None
        assert decl.display == "fs (stdio: npx -y server-filesystem /tmp)"

    def test_exactly_one_transport_required(self):
        with pytest.raises(ValidationError):  # neither
            SkillMcpDecl(name="x")
        with pytest.raises(ValidationError):  # both
            SkillMcpDecl(name="x", url="https://e.example/mcp", command="run")

    def test_auth_not_allowed_on_stdio(self):
        with pytest.raises(ValidationError):
            SkillMcpDecl(name="x", command="run", auth=SkillMcpBearerAuth(vault_path="v/t"))

    def test_http_still_valid(self):
        decl = SkillMcpDecl(name="h", url="https://e.example/mcp")
        assert not decl.is_stdio

    def test_config_accepts_mixed_transports(self):
        cfg = SkillCarapaceConfig.model_validate(
            {"mcp": [{"name": "a", "url": "https://e.example/mcp"}, {"name": "b", "command": "run-b"}]}
        )
        assert [s.is_stdio for s in cfg.mcp] == [False, True]


# ── Envelope parsing ────────────────────────────────────────────────


# ── _run_stdio_bridge ───────────────────────────────────────────────


# ── Tool handler gating ─────────────────────────────────────────────


# ── Toolset build + enumeration ─────────────────────────────────────


# ── Bridge script end-to-end (real subprocess against a fake server) ─

_FAKE_SERVER = textwrap.dedent(
    """
    from mcp.server.mcpserver import MCPServer
    mcp = MCPServer("demo")

    @mcp.tool()
    def echo(text: str, times: int = 1) -> str:
        "Echo text a number of times."
        return " ".join([text] * times)

    if __name__ == "__main__":
        mcp.run()
    """
)


@pytest.fixture
def fake_server(tmp_path: Path) -> str:
    path = tmp_path / "srv.py"
    path.write_text(_FAKE_SERVER)
    return f"{sys.executable} {path}"


def _run_bridge(server_cmd: str, *args: str) -> dict:
    server_b64 = base64.b64encode(server_cmd.encode()).decode()
    proc = subprocess.run(
        [sys.executable, str(BRIDGE), args[0], "--server", server_b64, *args[1:]],
        capture_output=True,
        text=True,
    )
    for line in proc.stdout.splitlines():
        if line.startswith("@@CARAPACE_MCP@@"):
            return json.loads(line.removeprefix("@@CARAPACE_MCP@@"))
    raise AssertionError(f"no envelope. stdout={proc.stdout!r} stderr={proc.stderr!r}")


class TestBridgeScriptEndToEnd:
    def test_list_emits_real_json_schema(self, fake_server: str):
        env = _run_bridge(fake_server, "list")
        assert env["ok"] is True
        (tool,) = env["result"]
        assert tool["name"] == "echo"
        # real JSON Schema, not a flattened param list
        assert tool["input_schema"]["properties"]["text"]["type"] == "string"
        assert tool["input_schema"]["required"] == ["text"]

    def test_call_passes_structured_args(self, fake_server: str):
        args_b64 = base64.b64encode(json.dumps({"text": "hi", "times": 3}).encode()).decode()
        env = _run_bridge(fake_server, "call", "--tool", "echo", "--args", args_b64)
        assert env["ok"] is True
        assert env["result"] == {"result": "hi hi hi"}

    def test_unknown_tool_reports_clean_error(self, fake_server: str):
        env = _run_bridge(fake_server, "call", "--tool", "nope")
        assert env["ok"] is False
        assert "nope" in env["error"]
