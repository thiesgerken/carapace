from __future__ import annotations

import asyncio

import typer
from dotenv import load_dotenv
from httpx import AsyncClient, HTTPStatusError
from pydantic_ai import DeferredToolRequests, DeferredToolResults, ToolDenied
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.retries import AsyncTenacityTransport, RetryConfig, wait_retry_after
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from tenacity import (
    RetryCallState,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from carapace.agent import create_agent
from carapace.bootstrap import ensure_data_dir
from carapace.config import get_data_dir, load_config, load_rules
from carapace.models import Deps
from carapace.session import SessionManager
from carapace.skills import SkillRegistry

load_dotenv()

app = typer.Typer(help="Carapace -- security-first personal AI agent")
console = Console()


def _create_anthropic_model(model_name: str) -> AnthropicModel:
    """Build an AnthropicModel with automatic retry on 429/5xx errors."""

    def _before_sleep(state: RetryCallState) -> None:
        wait = state.next_action.sleep if state.next_action else 0
        console.print(f"[yellow]Rate limited (attempt {state.attempt_number}). Retrying in {wait:.0f}s...[/yellow]")

    transport = AsyncTenacityTransport(
        config=RetryConfig(
            retry=retry_if_exception_type((HTTPStatusError, ConnectionError)),
            wait=wait_retry_after(
                fallback_strategy=wait_exponential(multiplier=1, max=60),
                max_wait=300,
            ),
            stop=stop_after_attempt(5),
            before_sleep=_before_sleep,
            reraise=True,
        ),
        validate_response=lambda r: r.raise_for_status() if r.status_code in (429, 502, 503, 504) else None,
    )
    http_client = AsyncClient(transport=transport)

    model_id = model_name.removeprefix("anthropic:")
    return AnthropicModel(model_id, provider=AnthropicProvider(http_client=http_client))


def _replay_history(messages: list, n: int) -> None:
    """Re-print previous conversation turns. *n=-1* means all."""
    # Collect (user_text, assistant_text) pairs
    pairs: list[tuple[str, str]] = []
    user_text: str | None = None
    for msg in messages:
        if isinstance(msg, ModelRequest):
            for part in msg.parts:
                if isinstance(part, UserPromptPart) and isinstance(part.content, str):
                    user_text = part.content
        elif isinstance(msg, ModelResponse) and user_text is not None:
            assistant_text = "".join(p.content for p in msg.parts if isinstance(p, TextPart))
            if assistant_text:
                pairs.append((user_text, assistant_text))
            user_text = None

    if not pairs:
        console.print("[dim]No previous messages to show.[/dim]")
        return

    show = pairs if n < 0 else pairs[-n:]
    for user_msg, ai_msg in show:
        console.print(f"[bold cyan]carapace>[/bold cyan] {user_msg}")
        console.print()
        console.print(Markdown(ai_msg))
        console.print()
    console.print(f"[dim]({len(show)} previous turn{'s' if len(show) != 1 else ''} replayed)[/dim]")
    console.print()


def _handle_slash_command(command: str, deps: Deps, session_mgr: SessionManager) -> bool:
    """Handle slash commands. Returns True if the command was handled."""
    parts = command.strip().split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    if cmd == "/help":
        table = Table(title="Slash Commands")
        table.add_column("Command", style="bold")
        table.add_column("Description")
        table.add_row("/rules", "List all rules and their status")
        table.add_row("/disable <id>", "Disable a rule for this session")
        table.add_row("/enable <id>", "Re-enable a disabled rule")
        table.add_row("/session", "Show current session state")
        table.add_row("/reset", "Create a new session (clears state)")
        table.add_row("/skills", "List available skills")
        table.add_row("/memory", "List memory files")
        table.add_row("/verbose", "Toggle tool call display")
        table.add_row("/quit", "Exit")
        table.add_row("/help", "Show this help")
        console.print(table)
        return True

    if cmd == "/rules":
        table = Table(title="Security Rules")
        table.add_column("ID", style="bold")
        table.add_column("Trigger")
        table.add_column("Mode")
        table.add_column("Status")
        for rule in deps.rules:
            if rule.id in deps.session_state.disabled_rules:
                status = "[red]disabled[/red]"
            elif rule.id in deps.session_state.activated_rules:
                status = "[yellow]activated[/yellow]"
            elif rule.trigger.strip().lower() == "always":
                status = "[green]always-on[/green]"
            else:
                status = "inactive"
            table.add_row(
                rule.id,
                rule.trigger[:50] + ("..." if len(rule.trigger) > 50 else ""),
                rule.mode.value,
                status,
            )
        console.print(table)
        return True

    if cmd == "/disable":
        if not arg:
            console.print("[red]Usage: /disable <rule-id>[/red]")
            return True
        rule_ids = [r.id for r in deps.rules]
        if arg not in rule_ids:
            console.print(f"[red]Unknown rule: {arg}[/red]")
            return True
        if arg not in deps.session_state.disabled_rules:
            deps.session_state.disabled_rules.append(arg)
            session_mgr.save_state(deps.session_state)
        console.print(f"[yellow]Rule '{arg}' disabled for this session.[/yellow]")
        return True

    if cmd == "/enable":
        if not arg:
            console.print("[red]Usage: /enable <rule-id>[/red]")
            return True
        if arg in deps.session_state.disabled_rules:
            deps.session_state.disabled_rules.remove(arg)
            session_mgr.save_state(deps.session_state)
        console.print(f"[green]Rule '{arg}' re-enabled.[/green]")
        return True

    if cmd == "/session":
        console.print(
            Panel(
                f"[bold]Session ID:[/bold] {deps.session_state.session_id}\n"
                f"[bold]Channel:[/bold] {deps.session_state.channel_type}\n"
                f"[bold]Activated rules:[/bold] {deps.session_state.activated_rules or '(none)'}\n"
                f"[bold]Disabled rules:[/bold] {deps.session_state.disabled_rules or '(none)'}\n"
                f"[bold]Approved credentials:[/bold] {deps.session_state.approved_credentials or '(none)'}",
                title="Session State",
            )
        )
        return True

    if cmd == "/skills":
        registry = SkillRegistry(deps.data_dir / "skills")
        catalog = registry.scan()
        if not catalog:
            console.print("No skills available.")
        else:
            for s in catalog:
                console.print(f"  [bold]{s.name}[/bold]: {s.description.strip()}")
        return True

    if cmd == "/memory":
        from carapace.memory import MemoryStore

        store = MemoryStore(deps.data_dir)
        files = store.list_files()
        if not files:
            console.print("No memory files.")
        else:
            for f in files:
                console.print(f"  {f}")
        return True

    if cmd in ("/quit", "/exit"):
        raise typer.Exit()

    return False


async def _run_agent_loop(
    user_input: str,
    deps: Deps,
    session_mgr: SessionManager,
    message_history: list,
) -> list:
    """Run the agent, handling approval loops."""
    agent = create_agent(deps)

    result = await agent.run(
        user_input,
        deps=deps,
        message_history=message_history or None,
    )
    messages = result.all_messages()

    while isinstance(result.output, DeferredToolRequests):
        requests = result.output
        deferred_results = DeferredToolResults()

        for call in requests.approvals:
            meta = requests.metadata.get(call.tool_call_id, {})
            triggered = meta.get("triggered_rules", [])
            descriptions = meta.get("descriptions", [])
            classification = meta.get("classification", {})

            console.print()
            panel_lines = [
                f"[bold]Tool:[/bold] {meta.get('tool', call.tool_name)}",
                f"[bold]Args:[/bold] {call.args}",
            ]
            if classification:
                panel_lines.append(
                    f"[bold]Classified as:[/bold] {classification.get('operation_type', '?')} "
                    f"(categories: {classification.get('categories', [])})"
                )
            if triggered:
                panel_lines.append(f"[bold]Triggered rules:[/bold] {', '.join(triggered)}")
            if descriptions:
                for desc in descriptions:
                    panel_lines.append(f"  {desc}")

            console.print(
                Panel(
                    "\n".join(panel_lines),
                    title="[yellow]Approval Required[/yellow]",
                    border_style="yellow",
                )
            )

            choice = console.input("[bold][a]pprove / [d]eny?[/bold] ").strip().lower()
            if choice in ("a", "approve", "y", "yes"):
                deferred_results.approvals[call.tool_call_id] = True
            else:
                deferred_results.approvals[call.tool_call_id] = ToolDenied("User denied this operation.")

        result = await agent.run(
            deps=deps,
            message_history=messages,
            deferred_tool_results=deferred_results,
        )
        messages = result.all_messages()

    if isinstance(result.output, str):
        console.print()
        console.print(Markdown(result.output))

    session_mgr.save_history(deps.session_state.session_id, messages)
    session_mgr.save_state(deps.session_state)
    return messages


@app.command()
def chat(
    session: str | None = typer.Option(None, "--session", "-s", help="Resume a session by ID"),
    data_dir: str | None = typer.Option(None, "--data-dir", "-d", help="Data directory path"),
    list_sessions: bool = typer.Option(False, "--list", "-l", help="List existing sessions"),
    prev: int = typer.Option(-1, "--prev", "-p", help="Replay N previous turns on resume (-1 = all, 0 = none)"),
    verbose: bool = typer.Option(True, "--verbose/--quiet", "-v/-q", help="Show tool calls"),
):
    """Start an interactive chat session with the Carapace agent."""
    from pathlib import Path

    data_path = Path(data_dir) if data_dir else get_data_dir()
    created = ensure_data_dir(data_path)
    if created:
        console.print(f"[dim]Initialised: {', '.join(created)}[/dim]")
    config = load_config(data_path)
    rules = load_rules(data_path)
    session_mgr = SessionManager(data_path)

    if list_sessions:
        sessions = session_mgr.list_sessions()
        if not sessions:
            console.print("No existing sessions.")
        else:
            console.print("[bold]Existing sessions:[/bold]")
            for sid in sessions:
                state = session_mgr.resume_session(sid)
                if state:
                    console.print(
                        f"  {sid}  "
                        f"(created: {state.created_at:%Y-%m-%d %H:%M}, "
                        f"rules: {len(state.activated_rules)} activated)"
                    )
        raise typer.Exit()

    # Create or resume session
    if session:
        session_state = session_mgr.resume_session(session)
        if session_state is None:
            console.print(f"[red]Session '{session}' not found.[/red]")
            raise typer.Exit(1)
        console.print(f"[green]Resumed session {session_state.session_id}[/green]")
    else:
        session_state = session_mgr.create_session()
        console.print(f"[green]New session {session_state.session_id}[/green]")

    # Load skill catalog
    registry = SkillRegistry(data_path / "skills")
    skill_catalog = registry.scan()

    # Build deps
    agent_model = _create_anthropic_model(config.agent.model)
    deps = Deps(
        config=config,
        data_dir=data_path,
        session_state=session_state,
        rules=rules,
        skill_catalog=skill_catalog,
        classifier_model=config.agent.classifier_model,
        agent_model=agent_model,
        verbose=verbose,
    )

    # Load existing history
    message_history = session_mgr.load_history(session_state.session_id)

    if session and message_history and prev != 0:
        _replay_history(message_history, prev)

    console.print(
        f"[dim]Model: {config.agent.model} | "
        f"Rules: {len(rules)} loaded | "
        f"Skills: {len(skill_catalog)} available | "
        f"Type /help for commands[/dim]"
    )
    console.print()

    # REPL loop
    while True:
        try:
            user_input = console.input("[bold cyan]carapace>[/bold cyan] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Goodbye.[/dim]")
            break

        if not user_input:
            continue

        if user_input.startswith("/"):
            if user_input.lower() in ("/quit", "/exit"):
                console.print("[dim]Goodbye.[/dim]")
                break

            if user_input.lower() == "/reset":
                session_state = session_mgr.create_session()
                message_history = []
                deps.session_state = session_state
                console.print(f"[green]New session {session_state.session_id}[/green]")
                continue

            if user_input.lower() == "/verbose":
                verbose = not verbose
                deps.verbose = verbose
                state = "on" if verbose else "off"
                console.print(f"[dim]Verbose mode {state}[/dim]")
                continue

            if _handle_slash_command(user_input, deps, session_mgr):
                continue

            console.print(f"[red]Unknown command: {user_input.split()[0]}[/red]")
            continue

        try:
            message_history = asyncio.run(_run_agent_loop(user_input, deps, session_mgr, message_history))
        except KeyboardInterrupt:
            console.print("\n[dim]Interrupted.[/dim]")
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")


if __name__ == "__main__":
    app()
