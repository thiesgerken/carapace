from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime
from typing import Any

import httpx
import typer
import websockets.asyncio.client
from dotenv import load_dotenv
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from websockets.exceptions import ConnectionClosed, InvalidHandshake

from carapace.auth import TOKEN_FILE
from carapace.config import get_data_dir

load_dotenv()

app = typer.Typer(help="Carapace -- security-first personal AI agent")
console = Console()

DEFAULT_SERVER = "http://127.0.0.1:8321"


def _fmt_dt(iso: str) -> str:
    """Format an ISO 8601 timestamp as a concise human-readable string."""
    if not iso:
        return "-"
    try:
        dt = datetime.fromisoformat(iso)
        return dt.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return iso


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


def _replay_history(server: str, session_id: str, headers: dict[str, str], limit: int) -> None:
    """Fetch and display past conversation messages."""
    params = {} if limit < 0 else {"limit": limit}
    try:
        resp = httpx.get(f"{server}/sessions/{session_id}/history", headers=headers, params=params)
        resp.raise_for_status()
    except httpx.HTTPStatusError:
        return

    messages = resp.json()
    if not messages:
        return

    console.print("[dim]--- conversation history ---[/dim]")
    for msg in messages:
        if msg["role"] == "user":
            console.print(f"[dim bold cyan]carapace>[/dim bold cyan] [dim]{msg['content']}[/dim]")
        elif msg["role"] == "tool_call":
            console.print(f"  [dim]{msg.get('tool', '?')}({msg.get('args', {})})[/dim]")
        else:
            console.print()
            console.print(Markdown(msg["content"]))
    console.print("[dim]--- end of history ---[/dim]")
    console.print()


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
            domain_entries: list[dict[str, str]] = payload.get("allowed_domains") or []
            if domain_entries:
                domain_lines = "\n".join(
                    f"  [cyan]{e['domain']}[/cyan]  [dim]{e['scope']}[/dim]" for e in domain_entries
                )
                domains_str = f"\n{domain_lines}"
            else:
                domains_str = " (none)"
            console.print(
                Panel(
                    f"[bold]Session ID:[/bold] {payload['session_id']}\n"
                    f"[bold]Channel:[/bold] {payload['channel_type']}\n"
                    f"[bold]Activated rules:[/bold] {payload.get('activated_rules') or '(none)'}\n"
                    f"[bold]Disabled rules:[/bold] {payload.get('disabled_rules') or '(none)'}\n"
                    f"[bold]Approved credentials:[/bold] {payload.get('approved_credentials') or '(none)'}\n"
                    f"[bold]Allowed domains:[/bold]{domains_str}",
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

        case "usage":
            _render_usage(payload)

        case "verbose":
            console.print(f"[dim]{payload['message']}[/dim]")

        case _:
            console.print(f"[dim]{payload}[/dim]")


def _render_usage(payload: dict[str, Any]) -> None:
    models: dict[str, dict[str, int]] = payload.get("models", {})
    categories: dict[str, dict[str, int]] = payload.get("categories", {})
    costs: dict[str, str] = payload.get("costs", {})

    if not models and not categories:
        console.print("[dim]No token usage recorded yet.[/dim]")
        return

    all_buckets = {**models, **categories}
    has_cache = any(b.get("cache_read_tokens") or b.get("cache_write_tokens") for b in all_buckets.values())
    has_costs = any(v != "0" for k, v in costs.items() if k != "total")

    def _cost_style(val: float) -> str:
        if val >= 0.25:
            return "red"
        if val >= 0.1:
            return "yellow"
        return "green"

    def _styled_cost(raw: str) -> str:
        n = float(raw)
        if not n:
            return "-"
        return f"[{_cost_style(n)}]${n:.4f}[/{_cost_style(n)}]"

    def _make_table(title: str, rows: dict[str, dict[str, int]], show_cost: bool = False) -> Table:
        table = Table(title=title)
        table.add_column("Source", style="bold")
        table.add_column("Input", justify="right")
        table.add_column("Output", justify="right")
        if has_cache:
            table.add_column("Cache Read", justify="right")
            table.add_column("Cache Write", justify="right")
        table.add_column("Requests", justify="right")
        if show_cost and has_costs:
            table.add_column("Cost", justify="right")
        for name, usage in rows.items():
            row = [name, f"{usage.get('input_tokens', 0):,}", f"{usage.get('output_tokens', 0):,}"]
            if has_cache:
                row += [f"{usage.get('cache_read_tokens', 0):,}", f"{usage.get('cache_write_tokens', 0):,}"]
            row.append(str(usage.get("requests", 0)))
            if show_cost and has_costs:
                row.append(_styled_cost(costs.get(name, "0")))
            table.add_row(*row)
        return table

    if models:
        console.print(_make_table("Usage by Model", models, show_cost=True))
    if categories:
        console.print(_make_table("Usage by Category", categories))

    total_in = payload.get("total_input", 0)
    total_out = payload.get("total_output", 0)
    total_cost = costs.get("total", "0")
    cost_str = f" | {_styled_cost(total_cost)}" if total_cost != "0" else ""
    tokens_str = f"{total_in + total_out:,} tokens ({total_in:,} in + {total_out:,} out)"
    console.print(f"[bold]Total:[/bold] {tokens_str}{cost_str}")


async def _render_proxy_approval_request(data: dict[str, Any]) -> str:
    """Render a proxy domain approval request and return the decision string."""
    domain = data.get("domain", "?")
    command = data.get("command", "")

    panel_lines = [f"[bold]Domain:[/bold] {domain}"]
    if command:
        panel_lines.append(f"[bold]Triggered by:[/bold] [dim]{command}[/dim]")

    console.print()
    console.print(
        Panel(
            "\n".join(panel_lines),
            title="[yellow]Proxy Access Request[/yellow]",
            border_style="yellow",
        )
    )
    console.print(
        f"  [bold]\\[o][/bold] Allow [cyan]{domain}[/cyan] once (this tool call only)\n"
        f"  [bold]\\[O][/bold] Allow [yellow]all[/yellow] internet once (this tool call only)\n"
        f"  [bold]\\[t][/bold] Allow [cyan]{domain}[/cyan] for 15 minutes\n"
        f"  [bold]\\[T][/bold] Allow [yellow]all[/yellow] internet for 15 minutes\n"
        f"  [bold]\\[d][/bold] Deny"
    )
    choice = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: console.input("[bold]Choice?[/bold] ").strip(),
    )
    match choice.lower():
        case "o" | "once":
            return "allow_once"
        case "t" | "timed":
            return "allow_15min"
        case _:
            pass
    match choice:
        case "O":
            return "allow_all_once"
        case "T":
            return "allow_all_15min"
        case _:
            return "deny"


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
        lambda: console.input("[bold]\\[a]pprove / \\[d]eny?[/bold] ").strip().lower(),
    )
    return choice in ("a", "approve", "y", "yes")


# --- WebSocket chat loop ---


async def _connect_ws(ws_url: str, *, max_backoff: float = 30.0) -> websockets.asyncio.client.ClientConnection:
    """Connect to the WebSocket, retrying with exponential backoff on failure."""
    delay = 1.0
    while True:
        try:
            return await websockets.asyncio.client.connect(ws_url)
        except (OSError, ConnectionClosed, InvalidHandshake) as exc:
            console.print(f"[dim]Connection failed ({exc}), retrying in {delay:.0f}s…[/dim]")
            await asyncio.sleep(delay)
            delay = min(delay * 2, max_backoff)


async def _chat_loop(ws_url: str) -> None:
    """Connect to the server WebSocket and run the interactive REPL."""
    ws = await _connect_ws(ws_url)
    pending_message: str | None = None
    try:
        while True:
            if pending_message is None:
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

                if user_input.lower() in ("/quit", "/exit"):
                    await ws.send(json.dumps({"type": "message", "content": user_input}))
                    console.print("[dim]Goodbye.[/dim]")
                    break
            else:
                user_input = pending_message
                pending_message = None

            try:
                await ws.send(json.dumps({"type": "message", "content": user_input}))
            except ConnectionClosed:
                console.print("[dim]Server disconnected — reconnecting…[/dim]")
                pending_message = user_input
                ws = await _connect_ws(ws_url)
                console.print("[green]Reconnected.[/green]")
                continue

            try:
                await _read_server_responses(ws)
            except ConnectionClosed:
                console.print("[dim]Server disconnected while reading response — reconnecting…[/dim]")
                ws = await _connect_ws(ws_url)
                console.print("[green]Reconnected.[/green]")
            except KeyboardInterrupt:
                console.print("\n[dim]Interrupted.[/dim]")
    finally:
        await ws.close()


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

            case "proxy_approval_request":
                try:
                    decision = await _render_proxy_approval_request(msg)
                except (KeyboardInterrupt, EOFError):
                    decision = "deny"
                    console.print("\n[dim]Denied (interrupted).[/dim]")
                await ws.send(
                    json.dumps(
                        {
                            "type": "proxy_approval_response",
                            "request_id": msg["request_id"],
                            "decision": decision,
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
    history: int = typer.Option(
        -1, "--history", "-H", help="Number of past messages to show on resume (-1 = all, 0 = none)"
    ),
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
            table = Table(title="Sessions", show_lines=False)
            table.add_column("ID", style="bold cyan")
            table.add_column("Created", style="dim")
            table.add_column("Last active", style="dim")
            table.add_column("Turns", justify="right")
            table.add_column("Active rules", justify="right")
            for s in sessions:
                table.add_row(
                    s["session_id"],
                    _fmt_dt(s.get("created_at", "")),
                    _fmt_dt(s.get("last_active", "")),
                    str(s.get("message_count", 0)),
                    str(len(s.get("activated_rules", []))),
                )
            console.print(table)
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

    if session and history != 0:
        _replay_history(server, session_id, headers, history)

    url = _ws_url(server, session_id, bearer)
    try:
        asyncio.run(_chat_loop(url))
    except Exception as e:
        console.print(f"[red]Connection error: {e}[/red]")


if __name__ == "__main__":
    app()
