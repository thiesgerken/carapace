"""The `mcp` bridge in the sandbox: an MCP server's tools as a command line, against a real stdio server."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import textwrap
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

MCP = Path(__file__).resolve().parents[1] / "sandbox" / "mcp"

_SERVER = textwrap.dedent(
    """
    import json
    from mcp.server.mcpserver import MCPServer

    mcp = MCPServer("demo")

    @mcp.tool()
    def echo(text: str, times: int = 1, shout: bool = False) -> str:
        "Echo text a number of times.\\n\\nMore detail."
        out = " ".join([text] * times)
        return out.upper() if shout else out

    @mcp.tool()
    def tag(names: list[str], filter: dict | None = None) -> str:
        "Show what arrived."
        return json.dumps({"names": names, "filter": filter}, sort_keys=True)

    @mcp.tool()
    def fail() -> str:
        "Always fails."
        raise ValueError("broken on purpose")

    if __name__ == "__main__":
        mcp.run()
    """
)


@pytest.fixture
def server(tmp_path: Path) -> str:
    path = tmp_path / "server.py"
    path.write_text(_SERVER)
    return f"{sys.executable} {path}"


def _mcp(server: str, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(MCP), "--name", "demo", "--stdio", server, *args],
        capture_output=True,
        text=True,
        input=stdin,
        check=False,
    )


def test_list_tools_shows_names_and_first_description_lines(server: str) -> None:
    done = _mcp(server, "--list-tools")

    assert done.stdout.splitlines() == [
        "echo\tEcho text a number of times.",
        "tag\tShow what arrived.",
        "fail\tAlways fails.",
    ]


def test_list_tools_as_json_carries_the_schemas(server: str) -> None:
    tools = json.loads(_mcp(server, "--list-tools", "--json").stdout)

    assert tools[0]["input_schema"]["required"] == ["text"]


def test_typed_flags_call_the_tool(server: str) -> None:
    done = _mcp(server, "echo", "--text", "hi", "--times", "2", "--shout")

    assert (done.returncode, done.stdout) == (0, "HI HI\n")


def test_arrays_of_scalars_repeat_and_nested_values_take_json(server: str, tmp_path: Path) -> None:
    (tmp_path / "filter.json").write_text('{"state": "open"}')

    done = _mcp(server, "tag", "--names", "a", "--names", "b", "--filter", f"@{tmp_path / 'filter.json'}")

    assert json.loads(done.stdout) == {"names": ["a", "b"], "filter": {"state": "open"}}


def test_the_whole_body_can_come_from_stdin(server: str) -> None:
    done = _mcp(server, "tag", "--json", "-", stdin='{"names": ["x"]}')

    assert json.loads(done.stdout) == {"names": ["x"], "filter": None}


def test_json_body_and_flags_conflict(server: str) -> None:
    done = _mcp(server, "echo", "--json", '{"text": "a"}', "--times", "2")

    assert done.returncode == 2
    assert "--json conflicts with --times" in done.stderr


def test_a_missing_required_argument_is_a_usage_error(server: str) -> None:
    done = _mcp(server, "echo", "--times", "2")

    assert done.returncode == 2
    assert "missing required argument: --text" in done.stderr


def test_help_and_schema_describe_one_tool(server: str) -> None:
    help_text = _mcp(server, "echo", "--help").stdout
    schema = json.loads(_mcp(server, "echo", "--schema").stdout)

    assert "usage: demo echo" in help_text
    assert "--shout, --no-shout" in help_text
    assert schema["properties"]["times"]["type"] == "integer"


def test_a_tool_error_fails_with_its_message(server: str) -> None:
    done = _mcp(server, "fail")

    assert done.returncode == 1
    assert "broken on purpose" in done.stderr


def test_an_unknown_tool_points_to_the_list(server: str) -> None:
    done = _mcp(server, "nope")

    assert done.returncode == 2
    assert "unknown tool 'nope'" in done.stderr


def test_credentials_apply_to_http_servers_only(server: str) -> None:
    done = _mcp(server, "--oauth", "personal/example", "--list-tools")

    assert done.returncode == 2
    assert "apply to --url" in done.stderr


_HTTP_SERVER = textwrap.dedent(
    """
    import sys

    import uvicorn
    from mcp.server.mcpserver import MCPServer

    mcp = MCPServer("demo")

    @mcp.tool()
    def whoami() -> str:
        "Answer when authorized."
        return "authorized"

    app = mcp.streamable_http_app(stateless_http=True, json_response=True)

    async def require_token(scope, receive, send):
        headers = dict(scope.get("headers", []))
        if scope["type"] == "http" and headers.get(b"authorization") != b"Bearer good":
            await send({"type": "http.response.start", "status": 401, "headers": []})
            await send({"type": "http.response.body", "body": b""})
            return
        await app(scope, receive, send)

    uvicorn.run(require_token, host="127.0.0.1", port=int(sys.argv[1]), log_level="error")
    """
)


@pytest.fixture
def http_url(tmp_path: Path) -> Iterator[str]:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    script = tmp_path / "http_server.py"
    script.write_text(_HTTP_SERVER)
    server = subprocess.Popen([sys.executable, str(script), str(port)])
    try:
        for _ in range(100):
            with socket.socket() as probe:
                if probe.connect_ex(("127.0.0.1", port)) == 0:
                    break
            time.sleep(0.1)
        yield f"http://127.0.0.1:{port}/mcp"
    finally:
        server.terminate()
        server.wait()


def _mcp_http(tmp_path: Path, *args: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Run the bridge without proxy settings, and with a `ccred` stand-in that logs its calls."""
    stubs = tmp_path / "stubs"
    stubs.mkdir(exist_ok=True)
    ccred = stubs / "ccred"
    ccred.write_text('#!/bin/sh\necho "$*" >> "$CALLS"\ncase "$*" in *--refresh*) echo good;; *) echo stale;; esac\n')
    ccred.chmod(0o755)
    base = {k: v for k, v in os.environ.items() if "proxy" not in k.lower()}
    return subprocess.run(
        [sys.executable, str(MCP), *args],
        capture_output=True,
        text=True,
        env=base | {"PATH": f"{stubs}:{base['PATH']}", "CALLS": str(tmp_path / "calls")} | env,
        check=False,
    )


def test_an_http_server_gets_the_bearer_token(tmp_path: Path, http_url: str) -> None:
    done = _mcp_http(tmp_path, "--url", http_url, "--bearer-env", "TOKEN", "whoami", env={"TOKEN": "good"})

    assert (done.returncode, done.stdout) == (0, "authorized\n")


def test_a_rejected_oauth_token_is_refreshed_once_for_the_whole_call(tmp_path: Path, http_url: str) -> None:
    done = _mcp_http(tmp_path, "--url", http_url, "--oauth", "demo/oauth", "whoami", env={})

    assert (done.returncode, done.stdout) == (0, "authorized\n")
    assert (tmp_path / "calls").read_text().splitlines() == [
        "get demo/oauth --access-token",
        "get demo/oauth --access-token --refresh",
    ]
