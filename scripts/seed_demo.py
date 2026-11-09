#!/usr/bin/env python3
"""Seed a throwaway carapace data dir with a demo user and ready-made sessions for screenshots.

Usage: ``uv run python scripts/seed_demo.py DATA_DIR``. Run it against the data dir of an already
started server (see "Screenshots" in docs/development.md): server startup closes approval
requests left open by a previous process, and two demo sessions show open requests.

Nothing here calls an LLM. All sessions are written directly as events, with fixed IDs and
timestamps relative to the seeding time, so the same script gives the same pictures.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic_ai.usage import RunUsage
from sqlalchemy.engine import make_url

from carapace.auth import AuthStore
from carapace.config import build_config
from carapace.database.engine import create_engine_and_factory, resolve_database_url, run_migrations
from carapace.models.session import SessionAttributes, SessionBudget, SessionState
from carapace.sandbox.snapshot import SessionSandboxSnapshot
from carapace.session.manager import SessionManager, SessionMeta
from carapace.usage import UsageTracker, usage_budget_exceeded_error

DEMO_USER = "demo"
DEMO_PASSWORD = "carapace-demo"
DEMO_MODEL = "anthropic:claude-sonnet-4-6"


@dataclass
class Transcript:
    """Builds one session's event list; ``at`` advances a few seconds per event."""

    at: datetime
    events: list[dict[str, Any]] = field(default_factory=list)
    _next_tool: int = 0

    def _stamp(self, seconds: int) -> str:
        self.at += timedelta(seconds=seconds)
        return self.at.isoformat()

    def user(self, content: str) -> None:
        self.events.append({"role": "user", "content": content, "timestamp": self._stamp(20)})

    def thinking(self, content: str, duration_ms: int) -> None:
        self.events.append(
            {"role": "thinking", "content": content, "reasoning_duration_ms": duration_ms, "timestamp": self._stamp(1)}
        )

    def assistant(self, content: str) -> None:
        self.events.append(
            {
                "role": "assistant",
                "content": content,
                "timestamp": self._stamp(6),
                "usage": {"model": DEMO_MODEL, "input_tokens": 6_400, "output_tokens": 420},
            }
        )

    def error(self, content: str) -> None:
        self.events.append({"role": "error", "content": content, "timestamp": self._stamp(1)})

    def call(
        self,
        tool: str,
        args: dict[str, Any],
        *,
        source: str = "safe-list",
        verdict: str = "allow",
        explanation: str = "auto-allowed",
        parent: str | None = None,
    ) -> str:
        self._next_tool += 1
        tool_id = f"demo-tool-{self._next_tool:03d}"
        detail = f"[{source}: {verdict}] {explanation}" if source == "sentinel" else f"[{source}] {explanation}"
        event: dict[str, Any] = {
            "role": "tool_call",
            "tool": tool,
            "args": args,
            "detail": detail,
            "approval_source": source,
            "approval_verdict": verdict,
            "approval_explanation": explanation,
            "tool_id": tool_id,
            "timestamp": self._stamp(2),
        }
        if parent is not None:
            event["parent_tool_id"] = parent
        if isinstance(args.get("contexts"), list):
            event["contexts"] = args["contexts"]
        self.events.append(event)
        return tool_id

    def result(self, tool_id: str, tool: str, output: str, exit_code: int = 0) -> None:
        self.events.append(
            {
                "role": "tool_result",
                "tool": tool,
                "result": output,
                "exit_code": exit_code,
                "tool_id": tool_id,
                "timestamp": self._stamp(3),
            }
        )

    def run(
        self, command: str, output: str, *, title: str | None = None, contexts: list[str] | None = None, **call: Any
    ) -> str:
        args: dict[str, Any] = {"command": command}
        if title is not None:
            args["title"] = title
        if contexts is not None:
            args["contexts"] = contexts
        tool_id = self.call("exec", args, **call)
        self.result(tool_id, "exec", output)
        return tool_id

    def domain(self, domain: str, parent: str, *, source: str = "safe-list") -> None:
        self.call("proxy_domain", {"domain": domain}, source=source, explanation="allowed", parent=parent)

    def approval_request(self, tool: str, args: dict[str, Any], explanation: str, risk_level: str) -> None:
        self.events.append(
            {
                "role": "approval_request",
                "tool_call_id": f"demo-call-{len(self.events):03d}",
                "tool": tool,
                "args": args,
                "explanation": explanation,
                "risk_level": risk_level,
            }
        )


@dataclass(frozen=True)
class DemoSession:
    suffix: str
    title: str
    transcript: Transcript
    attributes: SessionAttributes = field(default_factory=SessionAttributes)
    budget: SessionBudget = field(default_factory=SessionBudget)
    usage: UsageTracker = field(default_factory=UsageTracker)
    sandbox: SessionSandboxSnapshot = field(default_factory=SessionSandboxSnapshot)


def _usage(input_tokens: int, output_tokens: int) -> UsageTracker:
    tracker = UsageTracker()
    tracker.record(DEMO_MODEL, "agent", RunUsage(input_tokens=input_tokens, output_tokens=output_tokens, requests=3))
    return tracker


def _sandbox(status: str, used_bytes: int, now: datetime) -> SessionSandboxSnapshot:
    return SessionSandboxSnapshot.model_validate(
        {
            "exists": True,
            "runtime": "docker",
            "status": status,
            "storage_present": True,
            "last_measured_used_bytes": used_bytes,
            "last_measured_at": now,
            "updated_at": now,
        }
    )


def _sandbox_tour(start: datetime) -> Transcript:
    t = Transcript(start)
    t.user("Hi! Who are you?")
    t.thinking("The user wants a short introduction.", 3)
    t.assistant(
        "Hi! I'm **Carapace**, a security-conscious personal AI agent.\n\n"
        "- **Personal**: I work in your knowledge repo and remember what matters.\n"
        "- **Agentic**: I run code, search the web, manage files, and use skills.\n"
        "- **Reviewed**: a sentinel checks every action against your security policy.\n\n"
        "What can I help you with?"
    )
    t.user("Please explore your sandbox. What kind of system is it? Does it have internet?")
    t.thinking("Check the OS, architecture, user, and outbound connectivity in one command.", 210)
    probe = t.run(
        "cat /etc/os-release | head -2 && uname -m && whoami && curl -sI https://example.com | head -1",
        'PRETTY_NAME="Debian GNU/Linux 13 (trixie)"\nNAME="Debian GNU/Linux"\naarch64\nroot\nHTTP/2 200',
        title="explore sandbox environment",
    )
    t.domain("example.com", probe)
    t.assistant(
        "The sandbox is a Linux environment:\n\n"
        "- **Operating system**: Debian GNU/Linux 13 (trixie)\n"
        "- **Architecture**: `aarch64` (ARM64)\n"
        "- **User**: `root`\n"
        "- **Internet access**: yes, through the carapace proxy. `example.com` answered with HTTP 200.\n\n"
        "I can run scripts, install packages with `apt` or `uv`, and work on your files here."
    )
    return t


def _pancake_recipe(start: datetime) -> Transcript:
    t = Transcript(start)
    t.user("I really need a pancake recipe")
    skill = t.call("use_skill", {"skill_name": "web"})
    t.result(skill, "use_skill", "Skill 'web' activated.")
    search = t.run(
        "web_search 'best fluffy pancake recipe'",
        '[{"title": "Fluffy Pancakes", "url": "https://recipes.example.org/fluffy-pancakes"}]',
        contexts=["web"],
        source="sentinel",
        explanation="Searching the web for a recipe is the requested, read-only action.",
    )
    t.domain("search.example.org", search)
    t.call(
        "credential_access",
        {"vault_path": "demo/web-search-api-key", "name": "Search API Key"},
        source="skill",
        explanation="declared by skill web",
        parent=search,
    )
    fetch = t.run(
        "web_fetch 'https://recipes.example.org/fluffy-pancakes'",
        '{\n  "url": "https://recipes.example.org/fluffy-pancakes",\n  "status": 200,\n'
        '  "contentType": "text/html",\n  "content": "# Fluffy Pancakes\\n\\nMix the dry ingredients, whisk in '
        'milk, eggs and melted butter, rest the batter for five minutes..."\n}',
        contexts=["web"],
        source="sentinel",
        explanation=(
            "The agent fetches a recipe page found in the search results to answer the user's request. "
            "This is a safe, read-only action."
        ),
    )
    t.domain("recipes.example.org", fetch, source="sentinel")
    t.assistant(
        "Here is a highly rated recipe for **classic fluffy pancakes** (about 8 pancakes):\n\n"
        "| Ingredient | Amount |\n| --- | --- |\n| Flour | 200 g |\n| Sugar | 2 tbsp |\n"
        "| Baking powder | 2 tsp |\n| Salt | 1 pinch |\n| Milk | 300 ml |\n| Eggs | 2 |\n"
        "| Melted butter | 30 g |\n\n"
        "1. Whisk the dry ingredients.\n"
        "2. Mix milk, eggs and butter, then fold into the dry mix. A few lumps are fine.\n"
        "3. Let the batter rest for 5 minutes.\n4. Cook on a medium-hot pan until bubbles form, flip once.\n\n"
        "Enjoy!"
    )
    return t


def _recipe_skill(start: datetime) -> Transcript:
    t = Transcript(start)
    t.user("Please write a skill that includes the pancake recipe.")
    skill = t.call("use_skill", {"skill_name": "create-skill"})
    t.result(skill, "use_skill", "Skill 'create-skill' activated.")
    read = t.call("read", {"path": "skills/create-skill/REFERENCE.md", "offset": 0, "limit": 100})
    t.result(read, "read", "# Writing skills\n\nA skill is a folder with a SKILL.md ...")
    t.run("mkdir -p /workspace/skills/recipes", "")
    write = t.call(
        "write",
        {"path": "/workspace/skills/recipes/SKILL.md", "content": "---\nname: recipes\n---\n# Recipes\n..."},
        source="sentinel",
        explanation="Writing a new skill file inside the sandbox workspace is low risk.",
    )
    t.result(write, "write", "Wrote 41 lines to /workspace/skills/recipes/SKILL.md")
    push = t.run(
        'git add skills/recipes && git commit -m "Add recipes skill" && git push',
        "[main 3f2a9c1] Add recipes skill\n 1 file changed, 41 insertions(+)\n"
        "[stderr] To http://carapace:8322/git/knowledge\n   8d41e07..3f2a9c1  main -> main",
        source="sentinel",
        explanation="The agent commits and pushes the new skill the user asked for. The change is confined to "
        "skills/recipes.",
    )
    t.call(
        "git_push",
        {"ref": "refs/heads/main", "decision": "allow"},
        source="sentinel",
        explanation="The push only adds the requested skill directory.",
        parent=push,
    )
    t.assistant("Done! The new **recipes** skill lives in `skills/recipes/SKILL.md` and is pushed to your repo.")
    t.user('Please run "git log" and show me the result. Also "tree" over the workspace.')
    t.run(
        "git log -n 3 --format='%h %an %s' && tree /workspace -L 2",
        "3f2a9c1 carapace Add recipes skill\n8d41e07 carapace 💾 session: add demo session\n"
        "1c0b5aa carapace 🔧 bootstrap: seed default files\n/workspace\n├── AGENTS.md\n├── memory\n"
        "├── sessions\n└── skills\n    ├── create-skill\n    ├── recipes\n    └── web",
    )
    t.assistant(
        "Here is the output:\n\n## Git log (recent 3 commits)\n\n```text\n"
        "3f2a9c1 carapace Add recipes skill\n8d41e07 carapace 💾 session: add demo session\n"
        "1c0b5aa carapace 🔧 bootstrap: seed default files\n```\n\n## Workspace\n\n```text\n/workspace\n"
        "├── AGENTS.md\n├── memory\n├── sessions\n└── skills\n    ├── create-skill\n    ├── recipes\n"
        "    └── web\n```"
    )
    return t


def _blocked_post(start: datetime) -> Transcript:
    t = Transcript(start)
    t.user("Please perform an HTTP POST to http://dms.example.internal/create")
    t.thinking("A POST creates something on a remote service.", 940)
    t.call(
        "exec",
        {"command": "curl -X POST http://dms.example.internal/create", "title": "perform HTTP POST request"},
        source="sentinel",
        verdict="deny",
        explanation=(
            "The session is in ask mode, which prohibits operations that modify external systems. "
            "An HTTP POST to a /create endpoint changes a remote service and must be denied."
        ),
    )
    t.assistant(
        "I can't perform that HTTP POST. This session is in **ask mode**, which allows read-only actions and "
        "sandbox-local changes only. A POST to `/create` would modify a remote service."
    )
    return t


def _pending_approval(start: datetime) -> Transcript:
    t = Transcript(start)
    t.user("Clean up backups older than 90 days on the NAS.")
    command = "ssh nas.example.internal 'find /volume1/backups -mtime +90 -delete'"
    t.call(
        "exec",
        {"command": command, "title": "delete old NAS backups"},
        source="sentinel",
        verdict="escalate",
        explanation="Deleting files on a remote host is irreversible. The user should confirm.",
    )
    t.approval_request(
        "exec",
        {"command": command, "title": "delete old NAS backups"},
        "Deleting files on a remote host is irreversible. The user should confirm.",
        "high",
    )
    return t


def _budget_stop(start: datetime, usage: UsageTracker, cost_limit: Decimal) -> Transcript:
    t = Transcript(start)
    t.user("Summarize the open issues in the carapace repo.")
    t.run("gh issue list --limit 5", "#41  Dark mode for settings\n#40  Faster session list\n#38  Export to PDF")
    t.assistant("There are three open issues: dark mode for settings, a faster session list, and PDF export.")
    t.user("Now draft a reply for each of them.")
    error = usage_budget_exceeded_error(usage, total_cost_limit=cost_limit)
    assert error is not None, "the demo usage must exceed the demo cost limit"
    t.error(str(error))
    return t


def _autonomy_limit(start: datetime) -> Transcript:
    t = Transcript(start)
    t.user("Check all three projects for outdated dependencies.")
    for project in ("api", "web", "worker"):
        t.run(f"cd /workspace/{project} && uv lock --check", f"{project}: 2 packages can be upgraded")
    t.approval_request(
        "exec",
        {"command": "cd /workspace/api && uv lock --upgrade", "title": "upgrade api dependencies"},
        "Autonomy limit reached (3 tool calls without you)",
        "",
    )
    return t


def demo_sessions(now: datetime) -> list[DemoSession]:
    budget_usage = _usage(180_000, 24_000)
    return [
        DemoSession(
            "c0de0001",
            "🧭 Getting To Know The Sandbox",
            _sandbox_tour(now - timedelta(hours=26)),
            usage=_usage(9_800, 1_100),
            sandbox=_sandbox("stopped", 252_000, now),
        ),
        DemoSession(
            "c0de0002",
            "🥞 Classic Fluffy Pancake Recipe",
            _pancake_recipe(now - timedelta(hours=23)),
            usage=_usage(21_000, 1_900),
            sandbox=_sandbox("running", 59_000_000, now),
        ),
        DemoSession(
            "c0de0003",
            "🛠️ Creating A Recipe Skill",
            _recipe_skill(now - timedelta(hours=5)),
            usage=_usage(42_000, 3_200),
            sandbox=_sandbox("running", 61_000_000, now),
        ),
        DemoSession(
            "c0de0004",
            "📮 HTTP POST Blocked In Ask Mode",
            _blocked_post(now - timedelta(hours=3)),
            attributes=SessionAttributes(ask_mode=True),
            usage=_usage(2_500, 300),
        ),
        DemoSession(
            "c0de0005",
            "🗄️ Cleaning Up NAS Backups",
            _pending_approval(now - timedelta(minutes=50)),
        ),
        DemoSession(
            "c0de0006",
            "💸 Triage Open Issues",
            _budget_stop(now - timedelta(minutes=30), budget_usage, Decimal("0.75")),
            budget=SessionBudget(cost_usd=Decimal("0.75")),
            usage=budget_usage,
        ),
        DemoSession(
            "c0de0007",
            "📦 Checking Outdated Dependencies",
            _autonomy_limit(now - timedelta(minutes=10)),
            budget=SessionBudget(autonomous_tool_calls=3),
            usage=_usage(7_200, 600),
        ),
    ]


def _require_throwaway_database(data_dir: Path, url: str) -> None:
    """Refuse anything but a SQLite file inside DATA_DIR, so a real deployment can't get demo data."""
    database = make_url(url).database
    if not url.startswith("sqlite") or not database or not Path(database).resolve().is_relative_to(data_dir):
        sys.exit(f"Refusing to seed {url}: the demo database must be a SQLite file inside {data_dir}.")


def seed(data_dir: Path, now: datetime) -> None:
    if not data_dir.is_dir():
        sys.exit(f"{data_dir} does not exist. Start the demo server on it first.")
    config = build_config(data_dir)
    _require_throwaway_database(data_dir, resolve_database_url(config.database.url, data_dir))
    engine, session_factory = create_engine_and_factory(config.database, data_dir)
    run_migrations(engine)
    session_mgr = SessionManager(session_factory, data_dir)
    if session_mgr.list_sessions():
        sys.exit(f"Refusing to seed {data_dir}: it already has sessions. Use a fresh data dir.")

    AuthStore(session_factory, config.auth, data_dir).create_user(
        username=DEMO_USER, password=DEMO_PASSWORD, display_name="Demo User"
    )
    for demo in demo_sessions(now):
        events = demo.transcript.events
        created_at = datetime.fromisoformat(events[0]["timestamp"])
        session_id = f"{created_at:%Y-%m-%d-%H-%M}-{demo.suffix}"
        session_mgr.save_state(
            SessionState(
                session_id=session_id,
                channel_type="web",
                title=demo.title,
                attributes=demo.attributes,
                budget=demo.budget,
                created_at=created_at,
                last_active=demo.transcript.at,
            )
        )
        session_mgr.save_meta(session_id, SessionMeta(user=DEMO_USER))
        session_mgr.save_events(session_id, events)
        session_mgr.save_usage(session_id, demo.usage)
        session_mgr.save_sandbox_snapshot(session_id, demo.sandbox)
        print(f"{session_id}  {demo.title}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("data_dir", type=Path, help="throwaway CARAPACE_DATA_DIR of the demo server")
    args = parser.parse_args()
    seed(args.data_dir.resolve(), datetime.now(tz=UTC).replace(second=0, microsecond=0))
    print(f"Log in as {DEMO_USER!r} with password {DEMO_PASSWORD!r}.")


if __name__ == "__main__":
    main()
