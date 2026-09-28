"""Tests for skill-declared stdio MCP servers (bridged through the sandbox)."""

from __future__ import annotations

import base64
import json
import subprocess
import sys
import textwrap
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError
from pydantic_ai import ModelRetry, ToolDenied
from pydantic_ai.toolsets import FunctionToolset

from carapace.agent.tools import (
    _build_stdio_mcp_toolset,
    _parse_bridge_envelope,
    _run_stdio_bridge,
    _stdio_mcp_tool_handler,
    build_skill_mcp_toolset,
)
from carapace.models.skills import ContextGrant, SkillCarapaceConfig, SkillMcpBearerAuth, SkillMcpDecl
from carapace.security.context import SecurityDeniedError

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


class TestParseEnvelope:
    def test_extracts_marker_line_amid_noise(self):
        out = 'server stderr line\n[stderr] warning\n@@CARAPACE_MCP@@{"ok": true, "result": [1, 2]}\n'
        assert _parse_bridge_envelope(out) == {"ok": True, "result": [1, 2]}

    def test_missing_envelope_raises(self):
        with pytest.raises(ValueError, match="no result envelope"):
            _parse_bridge_envelope("just some output\n[exit code: 1]")


# ── _run_stdio_bridge ───────────────────────────────────────────────


def _bridge_ctx(*, output: str) -> MagicMock:
    ctx = MagicMock()
    ctx.deps.session_state.session_id = "sid"
    ctx.deps.session_state.context_grants = {
        "s": ContextGrant(skill_name="s", mcp_servers=[SkillMcpDecl(name="srv", command="run-server")])
    }
    ctx.deps.sandbox.get_cached_credential = MagicMock(return_value=None)
    ctx.deps.sandbox.exec_command = AsyncMock(return_value=MagicMock(output=output))
    return ctx


class TestRunStdioBridge:
    async def test_list_builds_command_and_returns_result(self):
        env = '@@CARAPACE_MCP@@{"ok": true, "result": [{"name": "t"}]}'
        ctx = _bridge_ctx(output=env)
        decl = ctx.deps.session_state.context_grants["s"].mcp_servers[0]
        result = await _run_stdio_bridge(ctx, "s", decl, "list")
        assert result == [{"name": "t"}]
        command = ctx.deps.sandbox.exec_command.await_args.args[1]
        assert command.startswith("carapace-mcp-bridge list --server ")
        server_b64 = command.split("--server ")[1]
        assert base64.b64decode(server_b64).decode() == "run-server"

    async def test_call_encodes_args(self):
        env = '@@CARAPACE_MCP@@{"ok": true, "result": "done"}'
        ctx = _bridge_ctx(output=env)
        decl = ctx.deps.session_state.context_grants["s"].mcp_servers[0]
        result = await _run_stdio_bridge(ctx, "s", decl, "call", tool="search", args={"q": "x"})
        assert result == "done"
        command = ctx.deps.sandbox.exec_command.await_args.args[1]
        assert "--tool search" in command
        args_b64 = command.split("--args ")[1]
        assert json.loads(base64.b64decode(args_b64).decode()) == {"q": "x"}

    async def test_error_envelope_raises(self):
        ctx = _bridge_ctx(output='@@CARAPACE_MCP@@{"ok": false, "error": "boom"}')
        decl = ctx.deps.session_state.context_grants["s"].mcp_servers[0]
        with pytest.raises(RuntimeError, match="boom"):
            await _run_stdio_bridge(ctx, "s", decl, "list")


# ── Tool handler gating ─────────────────────────────────────────────


def _handler_ctx(*, approved: bool = False) -> MagicMock:
    ctx = MagicMock()
    ctx.tool_call_approved = approved
    ctx.deps.config.agent.tool_output_max_chars = 16_000
    ctx.deps.tool_result_callback = None
    ctx.deps.tool_call_callback = None
    ctx.deps.assert_llm_budget_available = None
    ctx.deps.llm_usage_limits = None
    return ctx


class TestStdioToolHandler:
    async def test_denied_returns_tool_denied_without_running(self):
        decl = SkillMcpDecl(name="srv", command="run")
        handler = _stdio_mcp_tool_handler("s", decl, "search")
        ctx = _handler_ctx()
        with (
            patch("carapace.agent.tools.security.evaluate_with", AsyncMock(side_effect=SecurityDeniedError("no"))),
            patch("carapace.agent.tools._run_stdio_bridge", AsyncMock()) as run,
        ):
            result = await handler(ctx, q="x")
        assert isinstance(result, ToolDenied)
        run.assert_not_awaited()

    async def test_allowed_runs_bridge_and_returns_result(self):
        decl = SkillMcpDecl(name="srv", command="run")
        handler = _stdio_mcp_tool_handler("s", decl, "search")
        ctx = _handler_ctx()
        with (
            patch("carapace.agent.tools.security.evaluate_with", AsyncMock(return_value=None)) as gate,
            patch("carapace.agent.tools._run_stdio_bridge", AsyncMock(return_value={"hits": 3})),
        ):
            result = await handler(ctx, q="x")
        assert result == {"hits": 3}
        assert gate.await_args.args[2] == "mcp:srv:search"

    async def test_bridge_failure_becomes_model_retry(self):
        decl = SkillMcpDecl(name="srv", command="run")
        handler = _stdio_mcp_tool_handler("s", decl, "search")
        ctx = _handler_ctx()
        with (
            patch("carapace.agent.tools.security.evaluate_with", AsyncMock(return_value=None)),
            patch("carapace.agent.tools._run_stdio_bridge", AsyncMock(side_effect=RuntimeError("server down"))),
            pytest.raises(ModelRetry, match="server down"),
        ):
            await handler(ctx, q="x")


# ── Toolset build + enumeration ─────────────────────────────────────


class TestBuildStdioToolset:
    async def test_enumeration_registers_prefixed_tools(self):
        decl = SkillMcpDecl(name="srv", command="run")
        ctx = MagicMock()
        obj_schema = {"type": "object", "properties": {"q": {"type": "string"}}}
        tool_defs = [
            {"name": "search", "description": "d", "input_schema": obj_schema},
            {"name": "fetch", "description": "", "input_schema": {"type": "object", "properties": {}}},
        ]
        with patch("carapace.agent.tools._run_stdio_bridge", AsyncMock(return_value=tool_defs)):
            toolset = await _build_stdio_mcp_toolset(ctx, "s", decl)
        assert isinstance(toolset, FunctionToolset)
        assert sorted(toolset.tools.keys()) == ["srv_fetch", "srv_search"]

    async def test_empty_enumeration_returns_none(self):
        decl = SkillMcpDecl(name="srv", command="run")
        with patch("carapace.agent.tools._run_stdio_bridge", AsyncMock(return_value=[])):
            assert await _build_stdio_mcp_toolset(MagicMock(), "s", decl) is None

    async def test_factory_caches_stdio_toolset(self):
        decl = SkillMcpDecl(name="srv", command="run")
        ctx = MagicMock()
        ctx.deps.session_state.context_grants = {"s": ContextGrant(skill_name="s", mcp_servers=[decl])}
        ctx.deps.mcp_toolsets = {}
        tool_defs = [{"name": "t", "description": "", "input_schema": {"type": "object", "properties": {}}}]
        with patch("carapace.agent.tools._run_stdio_bridge", AsyncMock(return_value=tool_defs)) as run:
            first = await build_skill_mcp_toolset(ctx)
            second = await build_skill_mcp_toolset(ctx)
        assert first is second
        run.assert_awaited_once()  # enumerated once, then cached


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
