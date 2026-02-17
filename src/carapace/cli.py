from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import httpx
import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from websockets.asyncio.client import connect as ws_connect
from websockets.exceptions import ConnectionClosed

from carapace.auth import TOKEN_FILE
from carapace.config import get_data_dir

load_dotenv()

app = typer.Typer(help="Carapace -- security-first personal AI agent")
console = Console()

DEFAULT_SERVER = "http://127.0.0.1:8321"


def _get_token(data_dir: str | None, token: str | None) -> str:
    """Resolve bearer token from flag, env var, or data dir file."""
    if token:
        return token
    env_token = os.environ.get("CARAPACE_TOKEN")
    if env_token:
        return env_token
    from pathlib import Path

    data_path = Path(data_dir) if data_dir else get_data_dir()
    token_path = data_path / TOKEN_FILE
    if token_path.exists():
        return token_path.read_text().strip()
    console.print("[red]No auth token found. Set --token, CARAPACE_TOKEN, or run the server locally first.[/red]")
    raise typer.Exit(1)


def _auth_headers(bearer: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {bearer}"}


def _ws_url(server: str, session_id: str, bearer: str) -> str:
    """Build WebSocket URL with token query param."""
    base = server.replace("http://", "ws://").replace("https://", "wss://")
    return f"{base}/chat/{session_id}?token={bearer}"


# --- Rendering helpers for server responses ---


def _render_command_result(data: dict[str, Any]) -> None:
    cmd = data.get("command", "")
    payload: Any = data.get("data", {})

    match cmd:
        case "help":
            table = Table(title="Slash Commands")
            table.add_column("Command", style="bold")
            table.add_column("Description")
            for item in payload.get("commands", []):
                table.add_row(item["command"], item["description"])
            console.print(table)

        case "rules":
            table = Table(title="Security Rules")
            table.add_column("ID", style="bold")
            table.add_column("Trigger")
            table.add_column("Mode")
            table.add_column("Status")
            status_styles = {
                "disabled": "[red]disabled[/red]",
                "activated": "[yellow]activated[/yellow]",
                "always-on": "[green]always-on[/green]",
            }
            for rule in payload:
                styled = status_styles.get(rule["status"], rule["status"])
                table.add_row(rule["id"], rule["trigger"], rule["mode"], styled)
            console.print(table)

        case "disable":
            if "error" in payload:
                console.print(f"[red]{payload['error']}[/red]")
            else:
                console.print(f"[yellow]{payload['message']}[/yellow]")

        case "enable":
            if "error" in payload:
                console.print(f"[red]{payload['error']}[/red]")
            else:
                console.print(f"[green]{payload['message']}[/green]")

        case "session":
            console.print(
                Panel(
                    f"[bold]Session ID:[/bold] {payload['session_id']}\n"
                    f"[bold]Channel:[/bold] {payload['channel_type']}\n"
                    f"[bold]Activated rules:[/bold] {payload.get('activated_rules') or '(none)'}\n"
                    f"[bold]Disabled rules:[/bold] {payload.get('disabled_rules') or '(none)'}\n"
                    f"[bold]Approved credentials:[/bold] {payload.get('approved_credentials') or '(none)'}",
                    title="Session State",
                )
            )

        case "skills":
            if not payload:
                console.print("No skills available.")
            else:
                for s in payload:
                    console.print(f"  [bold]{s['name']}[/bold]: {s['description']}")

        case "memory":
            if not payload:
                console.print("No memory files.")
            else:
                for f in payload:
                    console.print(f"  {f}")

        case "verbose":
            console.print(f"[dim]{payload['message']}[/dim]")

        case _:
            console.print(f"[dim]{payload}[/dim]")


async def _render_approval_request(data: dict[str, Any]) -> bool:
    """Render an approval request and return True if approved."""
    panel_lines = [
        f"[bold]Tool:[/bold] {data.get('tool', '?')}",
        f"[bold]Args:[/bold] {data.get('args', {})}",
    ]
    classification = data.get("classification", {})
    if classification:
        panel_lines.append(
            f"[bold]Classified as:[/bold] {classification.get('operation_type', '?')} "
            f"(categories: {classification.get('categories', [])})"
        )
    triggered = data.get("triggered_rules", [])
    if triggered:
        panel_lines.append(f"[bold]Triggered rules:[/bold] {', '.join(triggered)}")
    for desc in data.get("descriptions", []):
        panel_lines.append(f"  {desc}")

    console.print()
    console.print(
        Panel(
            "\n".join(panel_lines),
            title="[yellow]Approval Required[/yellow]",
            border_style="yellow",
        )
    )
    choice = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: console.input("[bold][a]pprove / [d]eny?[/bold] ").strip().lower(),
    )
    return choice in ("a", "approve", "y", "yes")


# --- WebSocket chat loop ---


async def _chat_loop(ws_url: str) -> None:
    """Connect to the server WebSocket and run the interactive REPL."""
    async with ws_connect(ws_url) as ws:
        while True:
            try:
                user_input = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: console.input("[bold cyan]carapace>[/bold cyan] ").strip(),
                )
            except (EOFError, KeyboardInterrupt):
                console.print("\n[dim]Goodbye.[/dim]")
                break

            if not user_input:
                continue

            # Client-side quit
            if user_input.lower() in ("/quit", "/exit"):
                await ws.send(json.dumps({"type": "message", "content": user_input}))
                console.print("[dim]Goodbye.[/dim]")
                break

            await ws.send(json.dumps({"type": "message", "content": user_input}))

            # Read server responses until we get a terminal message
            try:
                await _read_server_responses(ws)
            except ConnectionClosed:
                console.print("[dim]Server disconnected.[/dim]")
                break
            except KeyboardInterrupt:
                console.print("\n[dim]Interrupted.[/dim]")


async def _read_server_responses(ws) -> None:
    """Read and render server messages until a terminal response (done/command_result/error)."""
    while True:
        raw = await ws.recv()
        msg = json.loads(raw)
        msg_type = msg.get("type")

        match msg_type:
            case "done":
                console.print()
                console.print(Markdown(msg["content"]))
                return

            case "token":
                # Future: incremental streaming display
                pass

            case "command_result":
                _render_command_result(msg)
                return

            case "error":
                console.print(f"[red]Error: {msg['detail']}[/red]")
                return

            case "tool_call":
                detail = msg.get("detail", "")
                console.print(f"  [dim]{msg['tool']}({msg['args']}) {detail}[/dim]")

            case "approval_request":
                try:
                    approved = await _render_approval_request(msg)
                except (KeyboardInterrupt, EOFError):
                    approved = False
                    console.print("\n[dim]Denied (interrupted).[/dim]")
                await ws.send(
                    json.dumps(
                        {
                            "type": "approval_response",
                            "tool_call_id": msg["tool_call_id"],
                            "approved": approved,
                        }
                    )
                )

            case _:
                console.print(f"[dim]Unknown server message: {msg_type}[/dim]")


# --- CLI commands ---


@app.command()
def chat(
    session: str | None = typer.Option(None, "--session", "-s", help="Resume a session by ID"),
    server: str = typer.Option(DEFAULT_SERVER, "--server", envvar="CARAPACE_SERVER", help="Server URL"),
    data_dir: str | None = typer.Option(None, "--data-dir", "-d", help="Data directory (for token lookup)"),
    token: str | None = typer.Option(None, "--token", envvar="CARAPACE_TOKEN", help="Bearer token"),
    list_sessions: bool = typer.Option(False, "--list", "-l", help="List existing sessions"),
):
    """Start an interactive chat session with the Carapace server."""
    bearer = _get_token(data_dir, token)
    headers = _auth_headers(bearer)

    if list_sessions:
        resp = httpx.get(f"{server}/sessions", headers=headers)
        resp.raise_for_status()
        sessions = resp.json()
        if not sessions:
            console.print("No existing sessions.")
        else:
            console.print("[bold]Existing sessions:[/bold]")
            for s in sessions:
                console.print(
                    f"  {s['session_id']}  "
                    f"(created: {s['created_at']}, "
                    f"rules: {len(s.get('activated_rules', []))} activated)"
                )
        raise typer.Exit()

    # Create or resume session
    if session:
        try:
            resp = httpx.get(f"{server}/sessions/{session}", headers=headers)
            resp.raise_for_status()
            session_data = resp.json()
            session_id = session_data["session_id"]
            console.print(f"[green]Resumed session {session_id}[/green]")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                console.print(f"[red]Session '{session}' not found.[/red]")
            else:
                console.print(f"[red]Server error: {exc.response.status_code}[/red]")
            raise typer.Exit(1) from None
    else:
        resp = httpx.post(f"{server}/sessions", headers=headers)
        resp.raise_for_status()
        session_data = resp.json()
        session_id = session_data["session_id"]
        console.print(f"[green]New session {session_id}[/green]")

    console.print(f"[dim]Server: {server} | Type /help for commands[/dim]")
    console.print()

    url = _ws_url(server, session_id, bearer)
    try:
        asyncio.run(_chat_loop(url))
    except Exception as e:
        console.print(f"[red]Connection error: {e}[/red]")


if __name__ == "__main__":
    app()
