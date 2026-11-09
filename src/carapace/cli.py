from __future__ import annotations

import asyncio
import contextlib
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, NoReturn
from urllib.parse import quote

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

from .payloads import dict_of_dicts, dict_or_empty, list_of_dicts
from .usage_display import SUBSCRIPTION_NOTE, category_equivalent_note, equivalent_note, show_equivalent_total

load_dotenv()

app = typer.Typer(help="carapace -- security-first personal AI agent")
console = Console()

DEFAULT_SERVER = "http://127.0.0.1:8321"


@app.callback()
def main() -> None:
    """carapace -- security-first personal AI agent."""


def _fmt_dt(iso: str) -> str:
    """Format an ISO 8601 timestamp as a concise human-readable string."""
    if not iso:
        return "-"
    try:
        dt = datetime.fromisoformat(iso)
        return dt.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return iso


def _login_client(server: str, username: str | None, password: str | None) -> httpx.Client:
    resolved_username = username.strip() if username else console.input("Username: ").strip()
    if not resolved_username:
        console.print("[red]Username is required.[/red]")
        raise typer.Exit(1)
    resolved_password = password if password is not None else typer.prompt("Password", hide_input=True)
    client = httpx.Client(base_url=server)
    try:
        resp = client.post("/api/auth/login", json={"username": resolved_username, "password": resolved_password})
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        client.close()
        if exc.response.status_code == 401:
            console.print("[red]Invalid username or password.[/red]")
        else:
            console.print(f"[red]Login failed: {exc.response.status_code}[/red]")
        raise typer.Exit(1) from None
    return client


def _api_key_client(server: str, api_key: str) -> httpx.Client:
    """Build an authenticated client from an API key (Authorization: Bearer)."""
    return httpx.Client(base_url=server, headers={"Authorization": f"Bearer {api_key}"})


def _cookie_headers(client: httpx.Client) -> dict[str, str]:
    cookie_header = "; ".join(f"{cookie.name}={cookie.value}" for cookie in client.cookies.jar)
    return {"Cookie": cookie_header} if cookie_header else {}


def _ws_url(server: str, session_id: str, api_key: str | None = None) -> str:
    """Build WebSocket URL for a session.

    Browsers cannot set ``Authorization`` on a WebSocket, so the chat endpoint also
    accepts an API key via the ``api_key`` query parameter.
    """
    base = server.replace("http://", "ws://").replace("https://", "wss://")
    url = f"{base}/api/chat/{session_id}"
    if api_key:
        url += f"?api_key={quote(api_key)}"
    return url


def _replay_history(client: httpx.Client, session_id: str, limit: int) -> None:
    """Fetch and display past conversation messages."""
    params = {} if limit < 0 else {"limit": limit}
    try:
        resp = client.get(f"/api/sessions/{session_id}/history", params=params)
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 403:
            console.print("[yellow]Skipping history replay: the API key lacks the 'history:read' scope.[/yellow]")
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
        elif msg["role"] == "error":
            console.print(f"[red]Error: {msg['content']}[/red]")
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

        case "usage":
            _render_usage(payload)

        case "budget":
            _render_budget(payload)

        case "models":
            available = payload.get("available") or []
            if not available:
                console.print("No models available.")
            else:
                table = Table(title="Available Models")
                table.add_column("ID", style="bold")
                table.add_column("Provider")
                table.add_column("Name")
                table.add_column("Context", justify="right")
                for item in available:
                    if isinstance(item, str):
                        table.add_row(item, "", "", "")
                        continue
                    if not isinstance(item, dict) or not item.get("id"):
                        continue
                    max_tokens = item.get("max_input_tokens")
                    ctx = f"{max_tokens:,}" if isinstance(max_tokens, int) else ""
                    table.add_row(
                        str(item["id"]),
                        str(item.get("provider") or ""),
                        str(item.get("name") or ""),
                        ctx,
                    )
                console.print(table)

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

        case _:
            console.print(f"[dim]{payload}[/dim]")


def _render_usage(payload: dict[str, Any]) -> None:
    models = dict_of_dicts(payload.get("models"))
    categories = dict_of_dicts(payload.get("categories"))
    model_costs = dict_of_dicts(payload.get("model_costs"))
    category_costs = dict_of_dicts(payload.get("category_costs"))
    total_cost = dict_or_empty(payload.get("total_cost"))
    budget_gauges = list_of_dicts(payload.get("budget_gauges"))
    total_tool_calls = int(payload.get("total_tool_calls", 0) or 0)

    if not models and not categories and not budget_gauges and total_tool_calls == 0:
        console.print("[dim]No token usage recorded yet.[/dim]")
        return

    all_buckets = {**models, **categories}
    has_cache = any(b.get("cache_read_tokens") or b.get("cache_write_tokens") for b in all_buckets.values())
    has_costs = any(float(cost.get("cost", 0)) for cost in model_costs.values())

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
        cost_cell: Callable[[str], str] | None = None,
    ) -> Table:
        table = Table(title=title)
        table.add_column("Source", style="bold")
        table.add_column("Input", justify="right")
        table.add_column("Output", justify="right")
        if has_cache:
            table.add_column("Cache Read", justify="right")
            table.add_column("Cache Write", justify="right")
        table.add_column("Requests", justify="right")
        if cost_cell is not None and has_costs:
            table.add_column("Cost", justify="right")
        for name, usage in rows.items():
            row = [name, f"{usage.get('input_tokens', 0):,}", f"{usage.get('output_tokens', 0):,}"]
            if has_cache:
                row += [f"{usage.get('cache_read_tokens', 0):,}", f"{usage.get('cache_write_tokens', 0):,}"]
            row.append(str(usage.get("requests", 0)))
            if cost_cell is not None and has_costs:
                row.append(cost_cell(name))
            table.add_row(*row)
        return table

    total_in = payload.get("total_input", 0)
    total_out = payload.get("total_output", 0)
    actual_total = str(total_cost.get("actual", "0"))
    cost_str = f" | {_styled_cost(actual_total)}" if float(actual_total) else ""
    if show_equivalent_total(budget_gauges):
        cost_str += equivalent_note(str(total_cost.get("equivalent", "0")))
    tokens_str = f"{total_in + total_out:,} tokens ({total_in:,} in + {total_out:,} out)"
    console.print(f"[bold]Total:[/bold] {tokens_str}{cost_str}")
    console.print(f"[bold]Tool calls:[/bold] {total_tool_calls:,}")

    if budget_gauges:
        console.print(_make_budget_table(budget_gauges))

    def _model_cost(name: str) -> str:
        cost = model_costs.get(name, {})
        cell = _styled_cost(str(cost.get("cost", "0")))
        return cell + SUBSCRIPTION_NOTE if cost.get("subscription") else cell

    def _category_cost(name: str) -> str:
        cost = category_costs.get(name, {})
        return _styled_cost(str(cost.get("actual", "0"))) + category_equivalent_note(cost)

    if models:
        console.print(_make_table("Usage by Model", models, cost_cell=_model_cost))
    if categories:
        console.print(_make_table("Usage by Category", categories, cost_cell=_category_cost))

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
            str(gauge.get("limit_value") or "—"),
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


async def _connect_ws(
    ws_url: str,
    *,
    headers: dict[str, str],
    max_backoff: float = 30.0,
) -> websockets.asyncio.client.ClientConnection:
    """Connect to the WebSocket, retrying with exponential backoff on failure."""
    delay = 1.0
    while True:
        try:
            return await websockets.asyncio.client.connect(ws_url, additional_headers=headers)
        except (OSError, ConnectionClosed, InvalidHandshake) as exc:
            console.print(f"[dim]Connection failed ({exc}), retrying in {delay:.0f}s…[/dim]")
            await asyncio.sleep(delay)
            delay = min(delay * 2, max_backoff)


async def _chat_loop(ws_url: str, *, headers: dict[str, str]) -> None:
    """Connect to the server WebSocket and run the interactive REPL."""
    ws = await _connect_ws(ws_url, headers=headers)
    pending_message: str | None = None
    show_tool_events = True
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

                if user_input.lower() == "/verbose":
                    show_tool_events = not show_tool_events
                    state = "on" if show_tool_events else "off"
                    console.print(f"[dim]Tool call display {state}.[/dim]")
                    continue
            else:
                user_input = pending_message
                pending_message = None

            try:
                await ws.send(json.dumps({"type": "message", "content": user_input}))
            except ConnectionClosed:
                console.print("[dim]Server disconnected — reconnecting…[/dim]")
                pending_message = user_input
                ws = await _connect_ws(ws_url, headers=headers)
                console.print("[green]Reconnected.[/green]")
                continue

            try:
                await _read_server_responses(ws, show_tool_events=show_tool_events)
            except ConnectionClosed:
                console.print("[dim]Server disconnected while reading response — reconnecting…[/dim]")
                ws = await _connect_ws(ws_url, headers=headers)
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


async def _read_server_responses(ws, *, show_tool_events: bool = True) -> None:
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
                    if show_tool_events:
                        detail = msg.get("detail", "")
                        console.print(f"  [dim]{msg['tool']}({msg['args']}) {detail}[/dim]")

                case "tool_result":
                    _stop_live()
                    if show_tool_events:
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
    api_key: str | None = typer.Option(
        None,
        "--api-key",
        "--key",
        "-k",
        envvar="CARAPACE_API_KEY",
        help=(
            "API key for Bearer auth (needs 'sessions' scope; '--history' replay also needs 'history'). "
            "Takes precedence over username/password."
        ),
    ),
    username: str | None = typer.Option(None, "--user", "-u", envvar="CARAPACE_USER", help="Username"),
    password: str | None = typer.Option(None, "--password", envvar="CARAPACE_PASSWORD", help="Password"),
    list_sessions: bool = typer.Option(False, "--list", "-l", help="List existing sessions"),
    history: int = typer.Option(
        -1, "--history", "-H", help="Number of past messages to show on resume (-1 = all, 0 = none)"
    ),
    force: bool = typer.Option(False, "--force", help="Bypass the interactive-terminal check"),
):
    """Start an interactive chat session with the carapace server."""
    if api_key and (username or password):
        raise typer.BadParameter("pass either --api-key or --user/--password, not both")
    if api_key:
        client = _api_key_client(server, api_key)
        headers: dict[str, str] = {}  # WebSocket auths via the api_key query parameter instead
    else:
        client = _login_client(server, username, password)
        headers = _cookie_headers(client)

    if list_sessions:
        sessions: list[dict[str, Any]] = []
        cursor: str | None = None

        while True:
            params = {"include_message_count": "true", "limit": "200"}
            if cursor is not None:
                params["cursor"] = cursor

            resp = client.get("/api/sessions", params=params)
            resp.raise_for_status()
            payload = resp.json()

            if isinstance(payload, list):
                sessions.extend(payload)
                break

            page = dict_or_empty(payload)
            sessions.extend(list_of_dicts(page.get("items")))
            if not page.get("has_more", False):
                break

            next_cursor = page.get("next_cursor")
            if not isinstance(next_cursor, str) or not next_cursor:
                break
            cursor = next_cursor

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
        client.close()
        raise typer.Exit()

    if not force and not (sys.stdin.isatty() and sys.stdout.isatty()):
        client.close()
        typer.echo(
            json.dumps(
                {
                    "status": "error",
                    "error": "chat is interactive but stdin/stdout is not a TTY",
                    "hint": "use the non-interactive commands: 'carapace session send/history/get/list', "
                    "'carapace approval allow/deny', 'carapace job ...' (or pass --force)",
                }
            ),
            err=True,
        )
        raise typer.Exit(1)

    # Create or resume session
    if session:
        try:
            resp = client.get(f"/api/sessions/{session}")
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
        resp = client.post("/api/sessions")
        resp.raise_for_status()
        session_data = resp.json()
        session_id = session_data["session_id"]
        console.print(f"[green]New session {session_id}[/green]")

    console.print(f"[dim]Server: {server} | Type /help for commands[/dim]")
    console.print()

    if session and history != 0:
        _replay_history(client, session_id, history)

    url = _ws_url(server, session_id, api_key)
    try:
        asyncio.run(_chat_loop(url, headers=headers))
    except Exception as e:
        console.print(f"[red]Connection error: {e}[/red]")
    finally:
        client.close()


# --- Agent-facing (non-interactive) commands ---------------------------------
#
# These emit JSON to stdout and never render markdown/LaTeX — agent text passes through
# verbatim. Exit codes: 0 ok, 1 error, 2 needs_approval, 3 timeout.

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_NEEDS_APPROVAL = 2
EXIT_TIMEOUT = 3

# Server->client request type -> approval "kind".
_APPROVAL_TYPES = {
    "approval_request": "tool",
    "domain_access_approval_request": "domain_access",
    "proxy_approval_request": "domain_access",
    "credential_approval_request": "credential_access",
    "git_push_approval_request": "git_push",
}


@dataclass
class _AgentCtx:
    server: str
    api_key: str | None
    client: httpx.Client
    ws_headers: dict[str, str]


def _resolve_ctx(server: str, api_key: str | None, username: str | None, password: str | None) -> _AgentCtx:
    if api_key:
        return _AgentCtx(server=server, api_key=api_key, client=_api_key_client(server, api_key), ws_headers={})
    client = _login_client(server, username, password)
    return _AgentCtx(server=server, api_key=None, client=client, ws_headers=_cookie_headers(client))


def _agent_auth(
    ctx: typer.Context,
    server: str = typer.Option(DEFAULT_SERVER, "--server", envvar="CARAPACE_SERVER", help="Server URL"),
    api_key: str | None = typer.Option(
        None, "--api-key", "-k", envvar="CARAPACE_API_KEY", help="API key (Bearer). Takes precedence over login."
    ),
    username: str | None = typer.Option(None, "--user", "-u", envvar="CARAPACE_USER", help="Username"),
    password: str | None = typer.Option(None, "--password", envvar="CARAPACE_PASSWORD", help="Password"),
) -> None:
    ctx.obj = _resolve_ctx(server, api_key, username, password)


def _strip_nulls(obj: Any) -> Any:
    """Recursively drop null values to keep CLI output compact."""
    if isinstance(obj, dict):
        return {k: _strip_nulls(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        return [_strip_nulls(v) for v in obj]
    return obj


def _print_json(obj: Any) -> None:
    typer.echo(json.dumps(_strip_nulls(obj), ensure_ascii=False, indent=2, default=str))


def _fail(detail: str, *, code: int = EXIT_ERROR, status: str = "error", **extra: Any) -> NoReturn:
    _print_json({"status": status, "error": detail, **extra})
    raise typer.Exit(code)


def _safe_detail(resp: httpx.Response) -> str:
    try:
        body = resp.json()
    except ValueError:
        return resp.text
    if isinstance(body, dict) and "detail" in body:
        return str(body["detail"])
    return resp.text


def _request_json(
    cli: _AgentCtx, method: str, path: str, *, params: dict[str, Any] | None = None, json_body: Any = None
) -> Any:
    try:
        resp = cli.client.request(method, path, params=params, json=json_body)
    except httpx.HTTPError as exc:
        _fail(f"request failed: {exc}")
    if resp.status_code >= 400:
        _fail(_safe_detail(resp), http_status=resp.status_code)
    if resp.status_code == 204:
        return None
    return resp.json()


def _read_json_input(path: str) -> Any:
    raw = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        _fail(f"invalid JSON in {path!r}: {exc}")


def _approval_info(msg: dict[str, Any], session_id: str) -> dict[str, Any]:
    kind = _APPROVAL_TYPES.get(msg.get("type", ""), "unknown")
    request_id = msg.get("tool_call_id") if kind == "tool" else msg.get("request_id")
    request = {"id": request_id, "kind": kind, **{k: v for k, v in msg.items() if k != "type"}}
    return {
        "request": request,
        "allow_command": f"carapace approval allow {session_id} {request_id}",
        "deny_command": f"carapace approval deny {session_id} {request_id}",
    }


def _last_turn_terminal_content(cli: _AgentCtx, session_id: str) -> str:
    """Return the text of the most recent assistant answer or turn error from history.

    Best-effort, "" on failure. Used to recover the outcome of a turn whose terminal WebSocket
    frame was missed; for a failed/cancelled turn this surfaces the persisted error instead of
    nothing.
    """
    try:
        resp = cli.client.get(f"/api/sessions/{session_id}/history", params={"limit": 20})
        resp.raise_for_status()
        messages = resp.json()
    except (httpx.HTTPError, ValueError):
        return ""
    if not isinstance(messages, list):
        return ""
    for msg in reversed(messages):
        if isinstance(msg, dict) and msg.get("role") in {"assistant", "error"}:
            return str(msg.get("content", ""))
    return ""


async def _read_turn(
    ws: Any, *, session_id: str, timeout: float, stream: bool, observe: bool = False
) -> tuple[dict[str, Any], int]:
    """Read server frames until a terminal signal, an approval request, or timeout.

    When *observe* is set the caller is a pure observer that did not start the turn over
    this socket (e.g. ``job run --wait``): the turn was kicked off via REST beforehand.  If
    it already finished, the server replays no terminal frame, only the on-connect ``status``
    with ``agent_running=False``.  The status frame carries no outcome (the real ``done`` /
    ``error`` / ``cancelled`` is gone), so report a neutral ``finished`` rather than guessing
    success — the caller backfills the result from history.
    """
    try:
        async with asyncio.timeout(timeout):
            while True:
                msg = json.loads(await ws.recv())
                match msg.get("type"):
                    case "done":
                        return {"status": "done", "content": msg.get("content", ""), "usage": msg.get("usage")}, EXIT_OK
                    case "status" if observe and msg.get("agent_running") is False:
                        return {"status": "finished", "usage": msg.get("usage")}, EXIT_OK
                    case "error":
                        return {"status": "error", "detail": msg.get("detail", "")}, EXIT_ERROR
                    case "cancelled":
                        return {"status": "cancelled", "detail": msg.get("detail", "")}, EXIT_OK
                    case "command_result":
                        return {
                            "status": "command_result",
                            "command": msg.get("command"),
                            "data": msg.get("data"),
                        }, EXIT_OK
                    case t if t in _APPROVAL_TYPES:
                        return {"status": "needs_approval", **_approval_info(msg, session_id)}, EXIT_NEEDS_APPROVAL
                    case t if stream and t in ("token", "thinking", "tool_call", "tool_result"):
                        typer.echo(
                            json.dumps(
                                {"event": t, **{k: v for k, v in msg.items() if k != "type"}},
                                ensure_ascii=False,
                                default=str,
                            ),
                            err=True,
                        )
                    case _:
                        continue  # status, llm_activity, user_message, session_title — ignore
    except TimeoutError:
        # Leave the turn running server-side; the caller can re-read history later.
        return {"status": "timeout"}, EXIT_TIMEOUT


async def _drive_turn(
    cli: _AgentCtx,
    session_id: str,
    *,
    message: str | None = None,
    approval: dict[str, Any] | None = None,
    wait: bool,
    timeout: float,
    stream: bool = False,
) -> tuple[dict[str, Any], int]:
    url = _ws_url(cli.server, session_id, cli.api_key)
    try:
        ws = await websockets.asyncio.client.connect(url, additional_headers=cli.ws_headers)
    except (OSError, InvalidHandshake, ConnectionClosed) as exc:
        return {"status": "error", "error": f"connection failed: {exc}"}, EXIT_ERROR
    try:
        if message is not None:
            await ws.send(json.dumps({"type": "message", "content": message}))
        elif approval is not None:
            await ws.send(json.dumps(approval))
        if not wait:
            return {"status": "submitted"}, EXIT_OK
        # Pure observer (no frame sent on this socket): the turn was started elsewhere
        # (e.g. `job run` via REST), so a finished turn surfaces only as an on-connect status.
        observe = message is None and approval is None
        result, code = await _read_turn(ws, session_id=session_id, timeout=timeout, stream=stream, observe=observe)
        # The terminal frame was missed; recover the actual outcome text from history so a
        # failed/cancelled turn is not reported as an empty success.
        if result.get("status") == "finished":
            result["content"] = _last_turn_terminal_content(cli, session_id)
        return result, code
    except ConnectionClosed as exc:
        return {"status": "error", "error": f"connection closed: {exc}"}, EXIT_ERROR
    finally:
        with contextlib.suppress(Exception):
            await ws.close()


def _emit_turn(cli: _AgentCtx, result: dict[str, Any], code: int) -> None:
    _print_json(result)
    cli.client.close()
    raise typer.Exit(code)


# --- session sub-app ---

session_app = typer.Typer(help="Manage and drive sessions (non-interactive, JSON output).", no_args_is_help=True)
job_app = typer.Typer(help="Manage jobs (non-interactive, JSON output).", no_args_is_help=True)
approval_app = typer.Typer(help="Resolve pending approval/escalation requests by id.", no_args_is_help=True)
for _sub in (session_app, job_app, approval_app):
    _sub.callback()(_agent_auth)


@session_app.command("list")
def session_list(
    ctx: typer.Context,
    archived: bool = typer.Option(False, "--archived", help="Include archived sessions"),
    limit: int = typer.Option(-1, "--limit", help="Max sessions to return (-1 = all)"),
) -> None:
    """List sessions."""
    cli: _AgentCtx = ctx.obj
    sessions: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        params: dict[str, Any] = {"include_message_count": "true", "limit": 200}
        if archived:
            params["include_archived"] = "true"
        if cursor is not None:
            params["cursor"] = cursor
        payload = _request_json(cli, "GET", "/api/sessions", params=params)
        if isinstance(payload, list):
            sessions.extend(payload)
            break
        page = dict_or_empty(payload)
        sessions.extend(list_of_dicts(page.get("items")))
        if not page.get("has_more", False):
            break
        next_cursor = page.get("next_cursor")
        if not isinstance(next_cursor, str) or not next_cursor:
            break
        cursor = next_cursor
    if limit >= 0:
        sessions = sessions[:limit]
    _print_json(sessions)
    cli.client.close()


@session_app.command("get")
def session_get(ctx: typer.Context, session_id: str = typer.Argument(...)) -> None:
    """Show a single session."""
    cli: _AgentCtx = ctx.obj
    _print_json(_request_json(cli, "GET", f"/api/sessions/{session_id}"))
    cli.client.close()


@session_app.command("create")
def session_create(
    ctx: typer.Context,
    ask: bool = typer.Option(False, "--ask", help="Ask before every action"),
    yolo: bool = typer.Option(False, "--yolo", help="Auto-approve everything"),
    unattended: bool = typer.Option(False, "--unattended", help="Unattended mode"),
    model: str | None = typer.Option(None, "--model", help="Agent model name"),
    sentinel_model: str | None = typer.Option(None, "--sentinel-model", help="Sentinel model name"),
    channel: str = typer.Option("cli", "--channel", help="Channel type"),
) -> None:
    """Create a session."""
    cli: _AgentCtx = ctx.obj
    body: dict[str, Any] = {"channel_type": channel}
    if ask:
        body["ask_mode"] = True
    if yolo:
        body["yolo_mode"] = True
    if unattended:
        body["unattended"] = True
    created = _request_json(cli, "POST", "/api/sessions", json_body=body)
    if model is not None or sentinel_model is not None:
        update: dict[str, Any] = {}
        if model is not None:
            update["agent_model_name"] = model
        if sentinel_model is not None:
            update["sentinel_model_name"] = sentinel_model
        created = _request_json(cli, "PATCH", f"/api/sessions/{created['session_id']}", json_body=update)
    _print_json(created)
    cli.client.close()


@session_app.command("update")
def session_update(
    ctx: typer.Context,
    session_id: str = typer.Argument(...),
    ask: bool = typer.Option(False, "--ask"),
    yolo: bool = typer.Option(False, "--yolo"),
    unattended: bool = typer.Option(False, "--unattended"),
    model: str | None = typer.Option(None, "--model"),
    sentinel_model: str | None = typer.Option(None, "--sentinel-model"),
    archived: bool | None = typer.Option(None, "--archive/--unarchive"),
    pinned: bool | None = typer.Option(None, "--pin/--unpin"),
    favorite: bool | None = typer.Option(None, "--favorite/--unfavorite"),
) -> None:
    """Update session settings (modes, models, flags)."""
    cli: _AgentCtx = ctx.obj
    attributes: dict[str, Any] = {}
    if ask:
        attributes["ask_mode"] = True
    if yolo:
        attributes["yolo_mode"] = True
    if unattended:
        attributes["unattended"] = True
    if archived is not None:
        attributes["archived"] = archived
    if pinned is not None:
        attributes["pinned"] = pinned
    if favorite is not None:
        attributes["favorite"] = favorite
    body: dict[str, Any] = {}
    if attributes:
        body["attributes"] = attributes
    if model is not None:
        body["agent_model_name"] = model
    if sentinel_model is not None:
        body["sentinel_model_name"] = sentinel_model
    if not body:
        _fail("nothing to update")
    _print_json(_request_json(cli, "PATCH", f"/api/sessions/{session_id}", json_body=body))
    cli.client.close()


def _pending_with_hints(cli: _AgentCtx, session_id: str) -> dict[str, Any]:
    data = _request_json(cli, "GET", f"/api/sessions/{session_id}/pending-approvals")
    for entry in [*data.get("approvals", []), *data.get("escalations", [])]:
        rid = entry.get("id")
        entry["allow_command"] = f"carapace approval allow {session_id} {rid}"
        entry["deny_command"] = f"carapace approval deny {session_id} {rid}"
    return data


@session_app.command("history")
def session_history(
    ctx: typer.Context,
    session_id: str = typer.Argument(...),
    limit: int = typer.Option(-1, "--limit", help="Number of past messages (-1 = all)"),
) -> None:
    """Show a session's message history plus any pending approval requests."""
    cli: _AgentCtx = ctx.obj
    messages = _request_json(cli, "GET", f"/api/sessions/{session_id}/history", params={"limit": limit})
    _print_json({"messages": messages, "pending": _pending_with_hints(cli, session_id)})
    cli.client.close()


@session_app.command("pending")
def session_pending(ctx: typer.Context, session_id: str = typer.Argument(...)) -> None:
    """List pending approval/escalation requests for a session."""
    cli: _AgentCtx = ctx.obj
    _print_json(_pending_with_hints(cli, session_id))
    cli.client.close()


@session_app.command("send")
def session_send(
    ctx: typer.Context,
    session_id: str = typer.Argument(...),
    content: str = typer.Argument(...),
    wait: bool = typer.Option(True, "--wait/--no-wait", help="Wait for the turn to finish"),
    timeout: float = typer.Option(120.0, "--timeout", help="Seconds to wait before giving up"),
    stream: bool = typer.Option(False, "--stream", help="Emit token/tool events to stderr while waiting"),
) -> None:
    """Send input to a session and (by default) wait for the next turn to finish."""
    cli: _AgentCtx = ctx.obj
    result, code = asyncio.run(_drive_turn(cli, session_id, message=content, wait=wait, timeout=timeout, stream=stream))
    _emit_turn(cli, result, code)


@session_app.command("cancel")
def session_cancel(ctx: typer.Context, session_id: str = typer.Argument(...)) -> None:
    """Cancel the running turn of a session."""
    cli: _AgentCtx = ctx.obj
    result, code = asyncio.run(_drive_turn(cli, session_id, approval={"type": "cancel"}, wait=False, timeout=0.0))
    if result.get("status") == "submitted":
        result = {"status": "cancelled"}
    _emit_turn(cli, result, code)


# --- approval sub-app ---


def _resolve_approval(
    ctx: typer.Context,
    session_id: str,
    request_id: str,
    *,
    allow: bool,
    message: str | None,
    wait: bool,
    timeout: float,
) -> None:
    cli: _AgentCtx = ctx.obj
    data = _request_json(cli, "GET", f"/api/sessions/{session_id}/pending-approvals")
    entry = next(
        (e for e in [*data.get("approvals", []), *data.get("escalations", [])] if e.get("id") == request_id), None
    )
    if entry is None:
        _print_json({"status": "not_found", "session_id": session_id, "request_id": request_id})
        cli.client.close()
        raise typer.Exit(EXIT_ERROR)
    if entry.get("kind") == "tool":
        response = {"type": "approval_response", "tool_call_id": request_id, "approved": allow, "message": message}
    else:
        response = {
            "type": "escalation_response",
            "request_id": request_id,
            "decision": "allow" if allow else "deny",
            "message": message,
        }
    result, code = asyncio.run(_drive_turn(cli, session_id, approval=response, wait=wait, timeout=timeout))
    if not wait and result.get("status") == "submitted":
        result = {"status": "resolved", "id": request_id, "decision": "allow" if allow else "deny"}
    _emit_turn(cli, result, code)


@approval_app.command("allow")
def approval_allow(
    ctx: typer.Context,
    session_id: str = typer.Argument(...),
    request_id: str = typer.Argument(..., help="Unique id of the pending request"),
    message: str | None = typer.Option(None, "--message", "-m"),
    wait: bool = typer.Option(False, "--wait/--no-wait", help="Wait for the resumed turn to finish"),
    timeout: float = typer.Option(120.0, "--timeout"),
) -> None:
    """Approve a specific pending request by id."""
    _resolve_approval(ctx, session_id, request_id, allow=True, message=message, wait=wait, timeout=timeout)


@approval_app.command("deny")
def approval_deny(
    ctx: typer.Context,
    session_id: str = typer.Argument(...),
    request_id: str = typer.Argument(..., help="Unique id of the pending request"),
    message: str | None = typer.Option(None, "--message", "-m"),
    wait: bool = typer.Option(False, "--wait/--no-wait", help="Wait for the resumed turn to finish"),
    timeout: float = typer.Option(120.0, "--timeout"),
) -> None:
    """Deny a specific pending request by id."""
    _resolve_approval(ctx, session_id, request_id, allow=False, message=message, wait=wait, timeout=timeout)


# --- job sub-app ---


@job_app.command("list")
def job_list(ctx: typer.Context) -> None:
    """List jobs."""
    cli: _AgentCtx = ctx.obj
    _print_json(_request_json(cli, "GET", "/api/jobs"))
    cli.client.close()


@job_app.command("get")
def job_get(ctx: typer.Context, job_id: str = typer.Argument(...)) -> None:
    """Show a single job."""
    cli: _AgentCtx = ctx.obj
    _print_json(_request_json(cli, "GET", f"/api/jobs/{job_id}"))
    cli.client.close()


@job_app.command("create")
def job_create(
    ctx: typer.Context,
    file: str = typer.Option(..., "--file", "-f", help="JobDefinition JSON file ('-' for stdin)"),
) -> None:
    """Create a job from a JobDefinition JSON document."""
    cli: _AgentCtx = ctx.obj
    _print_json(_request_json(cli, "POST", "/api/jobs", json_body=_read_json_input(file)))
    cli.client.close()


@job_app.command("update")
def job_update(
    ctx: typer.Context,
    job_id: str = typer.Argument(...),
    file: str = typer.Option(..., "--file", "-f", help="JobDefinition JSON file ('-' for stdin)"),
) -> None:
    """Replace a job from a JobDefinition JSON document."""
    cli: _AgentCtx = ctx.obj
    _print_json(_request_json(cli, "PUT", f"/api/jobs/{job_id}", json_body=_read_json_input(file)))
    cli.client.close()


@job_app.command("delete")
def job_delete(ctx: typer.Context, job_id: str = typer.Argument(...)) -> None:
    """Delete a job."""
    cli: _AgentCtx = ctx.obj
    _request_json(cli, "DELETE", f"/api/jobs/{job_id}")
    _print_json({"status": "deleted", "job_id": job_id})
    cli.client.close()


@job_app.command("run")
def job_run(
    ctx: typer.Context,
    job_id: str = typer.Argument(...),
    input_: str | None = typer.Option(None, "--input", help="Input payload passed to the job"),
    wait: bool = typer.Option(False, "--wait/--no-wait", help="Wait for the started turn to finish"),
    timeout: float = typer.Option(120.0, "--timeout"),
) -> None:
    """Run a job now."""
    cli: _AgentCtx = ctx.obj
    body = {"data": input_} if input_ is not None else None
    run = _request_json(cli, "POST", f"/api/jobs/{job_id}/run", json_body=body)
    out: dict[str, Any] = {"run": run}
    if not wait:
        _print_json(out)
        cli.client.close()
        return
    result, code = asyncio.run(_drive_turn(cli, run["session_id"], wait=True, timeout=timeout))
    out["turn"] = result
    _emit_turn(cli, out, code)


app.add_typer(session_app, name="session")
app.add_typer(job_app, name="job")
app.add_typer(approval_app, name="approval")


if __name__ == "__main__":
    app()
