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
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from websockets.exceptions import ConnectionClosed, InvalidHandshake

from carapace.payloads import dict_of_dicts, dict_or_empty, list_of_dicts, string_dict

load_dotenv()

app = typer.Typer(help="carapace -- security-first personal AI agent")
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
    """Resolve bearer token from flag or env var."""
    if token:
        return token
    env_token = os.environ.get("CARAPACE_TOKEN")
    if env_token:
        return env_token
    console.print("[red]No auth token found. Set --token or CARAPACE_TOKEN.[/red]")
    raise typer.Exit(1)


def _auth_headers(bearer: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {bearer}"}


def _ws_url(server: str, session_id: str, bearer: str) -> str:
    """Build WebSocket URL with token query param."""
    base = server.replace("http://", "ws://").replace("https://", "wss://")
    return f"{base}/api/chat/{session_id}?token={bearer}"


def _replay_history(server: str, session_id: str, headers: dict[str, str], limit: int) -> None:
    """Fetch and display past conversation messages."""
    params = {} if limit < 0 else {"limit": limit}
    try:
        resp = httpx.get(f"{server}/api/sessions/{session_id}/history", headers=headers, params=params)
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

        case "security":
            console.print(
                Panel(
                    f"[bold]Policy:[/bold]\n{payload.get('policy_preview', '(none)')}\n\n"
                    f"[bold]Action log entries:[/bold] {payload.get('action_log_entries', 0)}\n"
                    f"[bold]Sentinel evaluations:[/bold] {payload.get('sentinel_evaluations', 0)}",
                    title="Security Policy",
                )
            )

        case "approve-context":
            console.print(f"[green]{payload.get('message', 'Context approved.')}[/green]")

        case "retitle":
            console.print(f"[green]{payload.get('message', '')}[/green]")

        case "session":
            domain_entries: list[dict[str, str]] = payload.get("allowed_domains") or []
            if domain_entries:
                domain_lines = "\n".join(
                    f"  [cyan]{e['domain']}[/cyan]  [dim]{e['scope']}[/dim]" for e in domain_entries
                )
                domains_str = f"\n{domain_lines}"
            else:
                domains_str = " (none)"
            grants: dict[str, dict[str, Any]] = payload.get("context_grants") or {}
            if grants:
                grant_lines: list[str] = []
                for skill, info in grants.items():
                    parts_g = [f"  [bold]{skill}[/bold]"]
                    if info.get("domains"):
                        parts_g.append(f"    domains: {', '.join(info['domains'])}")
                    vps = info.get("vault_paths") or []
                    cached = info.get("cached_credentials", 0)
                    if vps:
                        parts_g.append(f"    credentials: {len(vps)} declared, {cached} cached")
                    grant_lines.append("\n".join(parts_g))
                grants_str = "\n" + "\n".join(grant_lines)
            else:
                grants_str = " (none)"
            console.print(
                Panel(
                    f"[bold]Session ID:[/bold] {payload['session_id']}\n"
                    f"[bold]Channel:[/bold] {payload['channel_type']}\n"
                    f"[bold]Context grants:[/bold]{grants_str}\n"
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

        case "budget":
            _render_budget(payload)

        case "models":
            if "models" in payload:
                for model_type, info in payload["models"].items():
                    marker = " [dim](overridden)[/dim]" if info["current"] != info["default"] else ""
                    console.print(f"  [bold]{model_type}:[/bold] {info['current']}{marker}")
                if payload.get("available"):
                    parts: list[str] = []
                    for item in payload["available"]:
                        if isinstance(item, str):
                            parts.append(item)
                        elif isinstance(item, dict) and item.get("id"):
                            s = str(item["id"])
                            mt = item.get("max_input_tokens")
                            if mt is not None:
                                s += f" (max_input_tokens={mt})"
                            parts.append(s)
                    if parts:
                        console.print()
                        console.print("  [dim]Available:[/dim] " + ", ".join(parts))

        case "model":
            if "models" in payload:
                if payload.get("error"):
                    console.print(f"[red]Error: {payload['error']}[/red]")
                for model_type, info in payload["models"].items():
                    marker = " [dim](overridden)[/dim]" if info["current"] != info["default"] else ""
                    console.print(f"  [bold]{model_type}:[/bold] {info['current']}{marker}")
                if payload.get("message"):
                    console.print(f"[green]{payload['message']}[/green]")
            elif "error" in payload:
                console.print(f"[red]Error: {payload['error']}[/red]")
            elif "message" in payload:
                console.print(f"[green]{payload['message']}[/green]")
            else:
                console.print(f"[bold]Current model:[/bold] {payload['current']}")
                if payload.get("default") and payload["default"] != payload["current"]:
                    console.print(f"[dim]Default: {payload['default']}[/dim]")

        case "model-agent" | "model-sentinel" | "model-title":
            if "error" in payload:
                console.print(f"[red]Error: {payload['error']}[/red]")
            elif "message" in payload:
                console.print(f"[green]{payload['message']}[/green]")
            else:
                console.print(f"[bold]Current model:[/bold] {payload['current']}")
                if payload.get("default") and payload["default"] != payload["current"]:
                    console.print(f"[dim]Default: {payload['default']}[/dim]")

        case "verbose":
            console.print(f"[dim]{payload['message']}[/dim]")

        case _:
            console.print(f"[dim]{payload}[/dim]")


def _render_usage(payload: dict[str, Any]) -> None:
    models = dict_of_dicts(payload.get("models"))
    categories = dict_of_dicts(payload.get("categories"))
    costs = string_dict(payload.get("costs"))
    category_costs = string_dict(payload.get("category_costs"))
    budget_gauges = list_of_dicts(payload.get("budget_gauges"))
    total_tool_calls = int(payload.get("total_tool_calls", 0) or 0)

    if not models and not categories and not budget_gauges and total_tool_calls == 0:
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

    def _make_table(
        title: str,
        rows: dict[str, dict[str, int]],
        *,
        show_cost: bool = False,
        row_costs: dict[str, str] | None = None,
    ) -> Table:
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
        lookup = row_costs if row_costs is not None else costs
        for name, usage in rows.items():
            row = [name, f"{usage.get('input_tokens', 0):,}", f"{usage.get('output_tokens', 0):,}"]
            if has_cache:
                row += [f"{usage.get('cache_read_tokens', 0):,}", f"{usage.get('cache_write_tokens', 0):,}"]
            row.append(str(usage.get("requests", 0)))
            if show_cost and has_costs:
                row.append(_styled_cost(lookup.get(name, "0")))
            table.add_row(*row)
        return table

    total_in = payload.get("total_input", 0)
    total_out = payload.get("total_output", 0)
    total_cost = costs.get("total", "0")
    cost_str = f" | {_styled_cost(total_cost)}" if total_cost != "0" else ""
    tokens_str = f"{total_in + total_out:,} tokens ({total_in:,} in + {total_out:,} out)"
    console.print(f"[bold]Total:[/bold] {tokens_str}{cost_str}")
    console.print(f"[bold]Tool calls:[/bold] {total_tool_calls:,}")

    if budget_gauges:
        console.print(_make_budget_table(budget_gauges))

    if models:
        console.print(_make_table("Usage by Model", models, show_cost=True))
    if categories:
        console.print(
            _make_table(
                "Usage by Category",
                categories,
                show_cost=True,
                row_costs=category_costs,
            ),
        )

    def _fmt_pct_cell(val: object) -> str:
        if val is None:
            return "—"
        if isinstance(val, int | float):
            return f"{float(val):.1f}%"
        return "—"

    last_rows: list[tuple[str, dict[str, Any]]] = []
    for key, src in (("last_llm_agent", "agent"), ("last_llm_sentinel", "sentinel")):
        row = dict_or_empty(payload.get(key))
        if int(row.get("context_size", 0) or 0) > 0:
            last_rows.append((src, row))

    if last_rows:
        show_other = False
        for _, row in last_rows:
            b = dict_or_empty(row.get("breakdown_pct"))
            o = b.get("other")
            if isinstance(o, int | float) and float(o) > 0:
                show_other = True
                break

        lr = Table(title="Context")
        lr.add_column("Source", style="bold")
        lr.add_column("Tokens", justify="right")
        lr.add_column("sys%", justify="right")
        lr.add_column("usr%", justify="right")
        lr.add_column("asst%", justify="right")
        lr.add_column("tool calls %", justify="right")
        lr.add_column("tool outputs %", justify="right")
        if show_other:
            lr.add_column("oth%", justify="right")
        for src, row in last_rows:
            b = dict_or_empty(row.get("breakdown_pct"))
            tok_n = int(row.get("context_size", 0))
            pct_raw = row.get("context_used_pct")
            tok_cell = f"{tok_n:,} ({float(pct_raw):.1f}%)" if isinstance(pct_raw, int | float) else f"{tok_n:,}"
            cells = [
                src,
                tok_cell,
                _fmt_pct_cell(b.get("system")),
                _fmt_pct_cell(b.get("user")),
                _fmt_pct_cell(b.get("assistant")),
                _fmt_pct_cell(b.get("tool_calls")),
                _fmt_pct_cell(b.get("tool_returns")),
            ]
            if show_other:
                cells.append(_fmt_pct_cell(b.get("other")))
            lr.add_row(*cells)
        console.print(lr)


def _make_budget_table(gauges: list[dict[str, Any]]) -> Table:
    table = Table(title="Session Budgets")
    table.add_column("Metric", style="bold")
    table.add_column("Current", justify="right")
    table.add_column("Limit", justify="right")
    table.add_column("Remaining", justify="right")
    table.add_column("Used", justify="right")
    for gauge in gauges:
        used = "blocked" if gauge.get("unavailable_reason") else f"{float(gauge.get('fill_pct', 0)):.1f}%"
        style = "red" if gauge.get("reached") else "none"
        table.add_row(
            str(gauge.get("label", "?")),
            str(gauge.get("current_value", "-")),
            str(gauge.get("limit_value", "-")),
            str(gauge.get("remaining_value") or "—"),
            f"[{style}]{used}[/{style}]" if style != "none" else used,
        )
    return table


def _render_budget(payload: dict[str, Any]) -> None:
    if payload.get("error"):
        console.print(f"[red]{payload['error']}[/red]")
        return
    gauges: list[dict[str, Any]] = payload.get("gauges", [])
    usage_hint = payload.get("usage_hint")
    if payload.get("message"):
        console.print(f"[dim]{payload['message']}[/dim]")
    if usage_hint:
        console.print(f"[dim]{usage_hint}[/dim]")
    if not gauges:
        if not payload.get("message"):
            console.print("[dim]No session budgets configured.[/dim]")
        return
    console.print(_make_budget_table(gauges))


async def _render_escalation_request(data: dict[str, Any]) -> tuple[str, str | None]:
    """Render a sentinel escalation (domain access or git push) and return the decision."""
    command = data.get("command", "")

    is_git_push = data.get("kind") == "git_push"
    title_text = "Git Push Request" if is_git_push else "Proxy Access Request"
    if is_git_push:
        label, value = "Ref", data.get("ref", "?")
    else:
        label, value = "Domain", data.get("domain", "?")

    panel_lines = [f"[bold]{label}:[/bold] {value}"]
    if command:
        panel_lines.append(f"[bold]Triggered by:[/bold] [dim]{command}[/dim]")

    console.print()
    console.print(
        Panel(
            "\n".join(panel_lines),
            title=f"[yellow]{title_text}[/yellow]",
            border_style="yellow",
        )
    )
    choice = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: console.input("[bold]\\[a]llow / \\[d]eny?[/bold] ").strip().lower(),
    )
    if choice in ("a", "allow", "y", "yes"):
        return "allow", None
    return "deny", await _render_optional_deny_message()


async def _render_optional_deny_message() -> str | None:
    message = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: console.input("[dim]Optional deny message:[/dim] ").strip(),
    )
    return message or None


async def _render_credential_escalation(data: dict[str, Any]) -> tuple[str, str | None]:
    """Render a sentinel-escalated credential request and return the decision."""
    names = data.get("names", [])
    descriptions = data.get("descriptions", [])
    explanation = data.get("explanation", "")

    panel_lines: list[str] = []
    for name, desc in zip(names, descriptions, strict=False):
        line = f"[bold]{name}[/bold]"
        if desc:
            line += f" — {desc}"
        panel_lines.append(line)
    if explanation:
        panel_lines.append(f"\n[dim]{explanation}[/dim]")

    console.print()
    console.print(
        Panel(
            "\n".join(panel_lines),
            title="[yellow]Credential Request[/yellow]",
            border_style="yellow",
        )
    )
    choice = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: console.input("[bold]\\[a]llow / \\[d]eny?[/bold] ").strip().lower(),
    )
    if choice in ("a", "allow", "y", "yes"):
        return "allow", None
    return "deny", await _render_optional_deny_message()


async def _render_approval_request(data: dict[str, Any]) -> tuple[bool, str | None]:
    """Render an approval request and return True if approved."""
    panel_lines = [
        f"[bold]Tool:[/bold] {data.get('tool', '?')}",
        f"[bold]Args:[/bold] {data.get('args', {})}",
    ]
    explanation = data.get("explanation", "")
    if explanation:
        panel_lines.append(f"[bold]Reason:[/bold] {explanation}")
    risk_level = data.get("risk_level", "")
    if risk_level:
        risk_style = {"high": "red", "medium": "yellow", "low": "green"}.get(risk_level, "dim")
        panel_lines.append(f"[bold]Risk level:[/bold] [{risk_style}]{risk_level}[/{risk_style}]")

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
    if choice in ("a", "approve", "y", "yes"):
        return True, None
    return False, await _render_optional_deny_message()


# --- WebSocket chat loop ---


async def _read_until_done(ws) -> None:
    """Drain server messages until a terminal response (done/cancelled/error) arrives."""
    while True:
        raw = await ws.recv()
        msg = json.loads(raw)
        msg_type = msg.get("type")
        if msg_type in ("done", "cancelled", "error"):
            if msg_type == "cancelled":
                console.print(f"[yellow]{msg.get('detail', 'Agent cancelled.')}[/yellow]")
            elif msg_type == "done":
                console.print()
                console.print(Markdown(msg["content"]))
            elif msg_type == "error":
                console.print(f"[red]Error: {msg['detail']}[/red]")
            return


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
                console.print("\n[yellow]Cancelling…[/yellow]")
                try:
                    await ws.send(json.dumps({"type": "cancel"}))
                    await _read_until_done(ws)
                except (ConnectionClosed, KeyboardInterrupt):
                    console.print("[dim]Interrupted.[/dim]")
    finally:
        await ws.close()


async def _read_server_responses(ws) -> None:
    """Read and render server messages until a terminal response (done/command_result/error)."""
    streamed = ""
    live: Live | None = None

    def _stop_live() -> None:
        nonlocal live, streamed
        if live is not None:
            live.stop()
            live = None
        streamed = ""

    try:
        while True:
            raw = await ws.recv()
            msg = json.loads(raw)
            msg_type = msg.get("type")

            match msg_type:
                case "done":
                    _stop_live()
                    console.print()
                    console.print(Markdown(msg["content"]))
                    return

                case "cancelled":
                    _stop_live()
                    console.print(f"\n[yellow]{msg.get('detail', 'Agent cancelled.')}[/yellow]")
                    return

                case "token":
                    streamed += msg["content"]
                    if live is None:
                        console.print()
                        live = Live(Markdown(streamed), console=console, refresh_per_second=8)
                        live.start()
                    else:
                        live.update(Markdown(streamed))

                case "command_result":
                    _stop_live()
                    _render_command_result(msg)
                    return

                case "error":
                    _stop_live()
                    console.print(f"[red]Error: {msg['detail']}[/red]")
                    return

                case "tool_call":
                    _stop_live()
                    detail = msg.get("detail", "")
                    console.print(f"  [dim]{msg['tool']}({msg['args']}) {detail}[/dim]")

                case "tool_result":
                    _stop_live()
                    result_text = msg.get("result", "")
                    if result_text:
                        truncated = result_text[:500]
                        if len(result_text) > 500:
                            truncated += "…"
                        console.print(f"  [dim]→ {truncated}[/dim]")

                case "approval_request":
                    _stop_live()
                    try:
                        approved, message = await _render_approval_request(msg)
                    except (KeyboardInterrupt, EOFError):
                        approved = False
                        message = None
                        console.print("\n[dim]Denied (interrupted).[/dim]")
                    await ws.send(
                        json.dumps(
                            {
                                "type": "approval_response",
                                "tool_call_id": msg["tool_call_id"],
                                "approved": approved,
                                "message": message,
                            }
                        )
                    )

                case "proxy_approval_request" | "domain_access_approval_request":
                    _stop_live()
                    try:
                        decision, message = await _render_escalation_request(msg)
                    except (KeyboardInterrupt, EOFError):
                        decision = "deny"
                        message = None
                        console.print("\n[dim]Denied (interrupted).[/dim]")
                    await ws.send(
                        json.dumps(
                            {
                                "type": "escalation_response",
                                "request_id": msg["request_id"],
                                "decision": decision,
                                "message": message,
                            }
                        )
                    )

                case "credential_approval_request":
                    _stop_live()
                    try:
                        decision, message = await _render_credential_escalation(msg)
                    except (KeyboardInterrupt, EOFError):
                        decision = "deny"
                        message = None
                        console.print("\n[dim]Denied (interrupted).[/dim]")
                    await ws.send(
                        json.dumps(
                            {
                                "type": "escalation_response",
                                "request_id": msg["request_id"],
                                "decision": decision,
                                "message": message,
                            }
                        )
                    )

                case _:
                    pass
    finally:
        _stop_live()


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
    """Start an interactive chat session with the carapace server."""
    bearer = _get_token(data_dir, token)
    headers = _auth_headers(bearer)

    if list_sessions:
        resp = httpx.get(f"{server}/api/sessions?include_message_count=true", headers=headers)
        resp.raise_for_status()
        sessions = resp.json()
        if not sessions:
            console.print("No existing sessions.")
        else:
            table = Table(title="Sessions", show_lines=False)
            table.add_column("ID", style="bold cyan")
            table.add_column("Title")
            table.add_column("Created", style="dim")
            table.add_column("Last active", style="dim")
            table.add_column("Turns", justify="right")
            for s in sessions:
                table.add_row(
                    s["session_id"],
                    s.get("title", ""),
                    _fmt_dt(s.get("created_at", "")),
                    _fmt_dt(s.get("last_active", "")),
                    str(s.get("message_count", 0)),
                )
            console.print(table)
        raise typer.Exit()

    # Create or resume session
    if session:
        try:
            resp = httpx.get(f"{server}/api/sessions/{session}", headers=headers)
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
        resp = httpx.post(f"{server}/api/sessions", headers=headers)
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
