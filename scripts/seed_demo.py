#!/usr/bin/env python3
"""Seed a throwaway carapace data dir with a demo user and ready-made sessions for screenshots.

Usage: ``uv run python scripts/seed_demo.py DATA_DIR``, or ``--dev-stack data`` for a dev stack's own
data dir (the stack's ``demo`` process does that). Run it against the data dir of an already started
server (see "Screenshots" in docs/development.md): server startup closes approval requests left open
by a previous process, and two demo sessions show open requests.

Nothing here calls an LLM. All sessions are written directly as events, with fixed IDs and
timestamps relative to the seeding time, so the same script gives the same pictures.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic_ai.messages import (
    InstructionPart,
    ModelRequest,
    ModelResponse,
    TextPart,
    ThinkingPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.usage import RequestUsage, RunUsage
from sqlalchemy.engine import make_url

from carapace.auth import AuthStore
from carapace.config import build_config, resolve_user_knowledge_dir
from carapace.database.engine import SessionFactory, create_engine_and_factory, resolve_database_url, run_migrations
from carapace.memory.input import INPUT_FORMAT_VERSION
from carapace.memory.models import (
    ExtractionResult,
    Fact,
    Provenance,
    SessionExtraction,
    SessionExtractionOutput,
    SpawnedBy,
    TaskEstimate,
    TaskKind,
    TaskOutcome,
    TaskSelection,
)
from carapace.memory.periods import month_key_for_week, week_key
from carapace.memory.prompts import SESSION_EXTRACT
from carapace.memory.store import MemoryStore
from carapace.models.session import SessionAttributes, SessionBudget, SessionState
from carapace.models.user import MemoryBudget, UserConfig, UserDefaultModelsConfig, UserMemoryConfig
from carapace.sandbox.snapshot import SessionSandboxSnapshot
from carapace.session.manager import SessionManager, SessionMeta
from carapace.spans import Span
from carapace.usage import (
    InputShapeRatios,
    LlmContext,
    LlmRequestLog,
    LlmRequestRecord,
    LlmSource,
    UsageTracker,
    request_cost,
    usage_budget_exceeded_error,
)

DEMO_USER = "demo"
DEMO_PASSWORD = "carapace-demo"
DEMO_MODEL = "anthropic:claude-sonnet-4-6"
DEMO_SUBSCRIPTION_MODEL = "openai-codex:gpt-5.5"
PANCAKE_TURN_ID = "5eedf00d"
ARTIFACT_SESSION = "demo-sales-dashboard"
# Memory runs on the subscription; an older extraction ran on the paid API model. Today's spend
# sits close to the day limits, so the home page shows the budget notice.
DEMO_MEMORY_BUDGET = MemoryBudget(
    cost_usd_per_day=Decimal("0.024"),
    cost_usd_per_month=Decimal("1.00"),
    equivalent_cost_usd_per_day=Decimal("0.07"),
)
DEMO_USER_CONFIG = UserConfig(
    default_models=UserDefaultModelsConfig(memory_low=DEMO_SUBSCRIPTION_MODEL),
    memory=UserMemoryConfig(budget=DEMO_MEMORY_BUDGET),
)


@dataclass
class Transcript:
    """Builds one session's event list; ``at`` advances a few seconds per event."""

    at: datetime
    events: list[dict[str, Any]] = field(default_factory=list)
    _next_tool: int = 0

    def _stamp(self, seconds: int) -> str:
        self.at += timedelta(seconds=seconds)
        return self.at.isoformat()

    def user(self, content: str, *, turn_id: str | None = None) -> None:
        event: dict[str, Any] = {"role": "user", "content": content, "timestamp": self._stamp(20)}
        if turn_id is not None:
            event["turn_id"] = turn_id
        self.events.append(event)

    def thinking(self, content: str, duration_ms: int) -> None:
        self.events.append(
            {"role": "thinking", "content": content, "reasoning_duration_ms": duration_ms, "timestamp": self._stamp(1)}
        )

    def assistant(self, content: str, *, turn_id: str | None = None, seconds: int = 6) -> None:
        event: dict[str, Any] = {
            "role": "assistant",
            "content": content,
            "timestamp": self._stamp(seconds),
            "usage": {"model": DEMO_MODEL, "input_tokens": 6_400, "output_tokens": 420},
        }
        if turn_id is not None:
            event["turn_id"] = turn_id
        self.events.append(event)

    def error(self, content: str, *, traceback: str | None = None) -> None:
        event: dict[str, Any] = {"role": "error", "content": content, "timestamp": self._stamp(1)}
        if traceback is not None:
            event["traceback"] = traceback
        self.events.append(event)

    def call(
        self,
        tool: str,
        args: dict[str, Any],
        *,
        source: str | None = None,
        verdict: str = "allow",
        explanation: str | None = None,
        comment: str | None = None,
        parent: str | None = None,
    ) -> str:
        self._next_tool += 1
        tool_id = f"demo-tool-{self._next_tool:03d}"
        # An agent tool call carries no decision: nothing reviews it by itself.
        detail = (
            ""
            if source is None
            else f"[{source}: {verdict}] {explanation}"
            if source == "sentinel"
            else f"[{source}] {explanation}"
        )
        event: dict[str, Any] = {
            "role": "tool_call",
            "tool": tool,
            "args": args,
            "detail": detail,
            "approval_source": source,
            "approval_verdict": verdict if source is not None else None,
            "approval_explanation": explanation,
            "tool_id": tool_id,
            "timestamp": self._stamp(2),
        }
        if parent is not None:
            event["parent_tool_id"] = parent
        if comment is not None:
            event["approval_comment"] = comment
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

    def run(self, command: str, output: str, *, title: str | None = None, **call: Any) -> str:
        args: dict[str, Any] = {"command": command}
        if title is not None:
            args["title"] = title
        tool_id = self.call("exec", args, **call)
        self.result(tool_id, "exec", output)
        return tool_id

    def domain(self, domain: str, parent: str) -> None:
        self.call(
            "proxy_domain",
            {"domain": domain},
            source="sentinel",
            explanation="The command's stated purpose needs this domain.",
            parent=parent,
        )

    def approval_request(self, tool: str, args: dict[str, Any], explanation: str) -> None:
        self.events.append(
            {
                "role": "approval_request",
                "tool_call_id": f"demo-call-{len(self.events):03d}",
                "tool": tool,
                "args": args,
                "explanation": explanation,
            }
        )


@dataclass(frozen=True)
class DemoSession:
    session_id: str
    title: str
    transcript: Transcript
    attributes: SessionAttributes = field(default_factory=SessionAttributes)
    budget: SessionBudget = field(default_factory=SessionBudget)
    usage: UsageTracker = field(default_factory=UsageTracker)
    sandbox: SessionSandboxSnapshot = field(default_factory=SessionSandboxSnapshot)
    llm_contexts: list[LlmContext] = field(default_factory=list)
    llm_requests: list[LlmRequestRecord] = field(default_factory=list)
    turn_spans: dict[str, list[Span]] = field(default_factory=dict)


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
    t.user("I really need a pancake recipe", turn_id=PANCAKE_TURN_ID)
    skill = t.call("read_skill", {"skill_name": "web"})
    t.result(skill, "read_skill", _WEB_SKILL)
    # Access decisions happen while their exec runs, so they come before its result.
    search = t.call("exec", {"command": _SEARCH})
    t.domain("search.example.org", search)
    t.call(
        "credential_access",
        {"vault_path": "demo/web-search-api-key", "name": "Search API Key"},
        source="user",
        explanation="released by the user",
        parent=search,
    )
    t.result(search, "exec", '[{"title": "Fluffy Pancakes", "url": "https://recipes.example.org/fluffy-pancakes"}]')
    fetch = t.call("exec", {"command": _FETCH})
    t.domain("recipes.example.org", fetch)
    t.result(
        fetch,
        "exec",
        '{\n  "url": "https://recipes.example.org/fluffy-pancakes",\n  "status": 200,\n'
        '  "contentType": "text/html",\n  "content": "# Fluffy Pancakes\\n\\nMix the dry ingredients, whisk in '
        'milk, eggs and melted butter, rest the batter for five minutes..."\n}',
    )
    t.assistant(
        "Here is a highly rated recipe for **classic fluffy pancakes** (about 8 pancakes):\n\n"
        "| Ingredient | Amount |\n| --- | --- |\n| Flour | 200 g |\n| Sugar | 2 tbsp |\n"
        "| Baking powder | 2 tsp |\n| Salt | 1 pinch |\n| Milk | 300 ml |\n| Eggs | 2 |\n"
        "| Melted butter | 30 g |\n\n"
        "1. Whisk the dry ingredients.\n"
        "2. Mix milk, eggs and butter, then fold into the dry mix. A few lumps are fine.\n"
        "3. Let the batter rest for 5 minutes.\n4. Cook on a medium-hot pan until bubbles form, flip once.\n\n"
        "Enjoy!",
        turn_id=PANCAKE_TURN_ID,
        # The answer's request thinks for over a minute, so the timeline shows a long LLM row.
        seconds=80,
    )
    return t


def _recipe_skill(start: datetime) -> Transcript:
    t = Transcript(start)
    t.user("Please write a skill that includes the pancake recipe.")
    skill = t.call("read_skill", {"skill_name": "create-skill"})
    t.result(
        skill,
        "read_skill",
        "# Create Skill\n\nCreate or update skills under `skills/<name>/`. Read REFERENCE.md first.\n\n"
        "The skill has no flake.nix, so it has no commands.",
    )
    read = t.call("read", {"path": "skills/create-skill/REFERENCE.md", "offset": 0, "limit": 100})
    t.result(read, "read", "# Writing skills\n\nA skill is a folder with a SKILL.md ...")
    t.run("mkdir -p /workspace/skills/recipes", "")
    write = t.call(
        "write",
        {"path": "/workspace/skills/recipes/SKILL.md", "content": "# Recipes\n..."},
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
    t.user("Please perform an HTTP POST to https://dms.example.com/create")
    t.thinking("A POST creates something on a remote service.", 940)
    command = "curl -sf -X POST https://dms.example.com/create"
    post = t.call("exec", {"command": command, "title": "perform HTTP POST request"})
    t.call(
        "proxy_domain",
        {"domain": "dms.example.com"},
        source="sentinel",
        verdict="deny",
        explanation=(
            "The session is in ask mode, which prohibits operations that modify external systems. "
            "A POST to a /create endpoint changes a remote service."
        ),
        parent=post,
    )
    t.result(post, "exec", "curl: (56) CONNECT tunnel failed, response 403", exit_code=56)
    t.assistant(
        "I can't perform that HTTP POST. This session is in **ask mode**, which allows read-only actions and "
        "sandbox-local changes only, so the sentinel refused the connection to `dms.example.com`."
    )
    return t


def _internal_host(start: datetime) -> Transcript:
    t = Transcript(start)
    t.user("Is the document server at docs.home.arpa up?")
    t.thinking("A quick HEAD request answers that.", 620)
    command = "curl -sI https://docs.home.arpa | head -1"
    check = t.call("exec", {"command": command, "title": "check document server"})
    t.call(
        "proxy_domain",
        {"domain": "docs.home.arpa"},
        source="policy",
        verdict="deny",
        explanation=(
            "docs.home.arpa is a private or internal address or resolves to one. The proxy does not connect "
            "sandboxes to internal destinations unless an operator allows them with "
            "CARAPACE_SANDBOX_PROXY_ALLOWED_NETWORKS (CIDRs) or CARAPACE_SANDBOX_PROXY_ALLOWED_HOSTS (exact host "
            "names); in the Helm chart sandbox.allowedInternalNetworks and sandbox.allowedInternalHosts."
        ),
        parent=check,
    )
    t.result(check, "exec", "curl: (56) CONNECT tunnel failed, response 403", exit_code=56)
    t.assistant(
        "I can't reach `docs.home.arpa` from the sandbox: it resolves to an address on your local network, and "
        "the proxy only connects to internal hosts an operator allowed. Add it to "
        "`CARAPACE_SANDBOX_PROXY_ALLOWED_HOSTS` (Helm: `sandbox.allowedInternalHosts`) if I should check it."
    )
    return t


def _change_request(start: datetime) -> Transcript:
    t = Transcript(start)
    t.user('The recipes skill says "flour" twice in the pancake ingredients. Please fix that.')
    fix = t.call(
        "str_replace",
        {"path": "/workspace/skills/recipes/SKILL.md", "old_string": "- flour\n- flour", "new_string": "- flour"},
    )
    t.result(fix, "str_replace", "Replaced 1 occurrence in /workspace/skills/recipes/SKILL.md")
    first = t.call("exec", {"command": 'git commit -am "Fix duplicate flour" && git push', "title": "commit and push"})
    t.call(
        "git_push",
        {"ref": "refs/heads/main", "decision": "deny"},
        source="sentinel",
        verdict="deny",
        explanation="The commit also rewrites skills/web/SKILL.md, which the user did not ask to change. "
        "Push the recipes fix on its own.",
        parent=first,
    )
    t.result(
        first,
        "exec",
        "[main 9c1e04a] Fix duplicate flour\n 2 files changed, 3 insertions(+), 4 deletions(-)\n"
        "[stderr] remote: Push rejected: Sentinel denied this operation. The commit also rewrites "
        "skills/web/SKILL.md, which the user did not ask to change. Push the recipes fix on its own.\n"
        "[stderr]  ! [remote rejected] main -> main (pre-receive hook declined)",
        exit_code=1,
    )
    second = t.call(
        "exec",
        {
            "command": "git reset --soft HEAD~1 && git restore --staged skills/web/SKILL.md && "
            'git commit -m "Fix duplicate flour" && git push',
            "title": "push only the recipes fix",
        },
    )
    t.call(
        "git_push",
        {"ref": "refs/heads/main", "decision": "allow"},
        source="sentinel",
        explanation="The push only removes the duplicate line.",
        comment="The web skill change is still uncommitted in the workspace. Ask the user before pushing it.",
        parent=second,
    )
    t.result(
        second,
        "exec",
        "[main 5be71d2] Fix duplicate flour\n 1 file changed, 1 deletion(-)\n"
        "[stderr] To http://carapace:8322/git/knowledge\n   3f2a9c1..5be71d2  main -> main",
    )
    t.assistant(
        "Fixed and pushed: the pancake ingredients list **flour** once now. I also had an unrelated change to the "
        "web skill in my working copy; it is not pushed. Should I keep it?"
    )
    return t


def _pending_approval(start: datetime) -> Transcript:
    t = Transcript(start)
    t.user("Clean up backups older than 90 days on the NAS.")
    t.call("exec", {"command": "nas-backups prune --older-than 90d", "title": "delete old NAS backups"})
    t.events.append(
        {
            "role": "credential_approval",
            "request_id": "demo-escalation-nas",
            "vault_paths": ["demo/nas-admin-token"],
            "names": ["NAS admin token"],
            "descriptions": ["Admin API token of the NAS"],
            "domains": ["nas.example.com"],
            "explanation": "Deleting backups on the NAS is irreversible. The user should confirm.",
        }
    )
    return t


def _budget_stop(start: datetime, usage: UsageTracker, budget: SessionBudget) -> Transcript:
    t = Transcript(start)
    t.user("Summarize the open issues in the carapace repo.")
    t.run("gh issue list --limit 5", "#41  Dark mode for settings\n#40  Faster session list\n#38  Export to PDF")
    t.assistant("There are three open issues: dark mode for settings, a faster session list, and PDF export.")
    t.user("Now draft a reply for each of them.")
    error = usage_budget_exceeded_error(usage, budget)
    assert error is not None, "the demo usage must exceed the demo cost limit"
    t.error(str(error))
    return t


def _unexpected_error(start: datetime) -> Transcript:
    t = Transcript(start)
    t.user("Collect the wiring and pinout docs of the LED controller into one page.")
    t.run("curl -s https://example.com/controller/", "<html>… 412 KB …</html>", title="load the product page")
    summary = "InvalidURL: URL component 'query' too long"
    pinout = {"command": "curl -s https://example.com/controller/pinout", "title": "load the pinout page"}
    failed = t.call("exec", pinout)
    t.result(failed, "exec", f"The turn stopped on an unexpected error before this call completed: {summary}", 130)
    t.error(
        f"The turn stopped on an unexpected error: {summary}",
        traceback=(
            "Traceback (most recent call last):\n"
            '  File "/app/carapace/agent/tools.py", line 1602, in exec\n'
            "    result = await _prepare_exec_tool_result(ctx, result)\n"
            '  File "/app/httpx/_urlparse.py", line 269, in urlparse\n'
            "    raise InvalidURL(f\"URL component '{key}' too long\")\n"
            f"httpx.{summary}\n"
        ),
    )
    return t


def _subscription_usage() -> UsageTracker:
    """The agent runs on a ChatGPT subscription (no actual cost), the sentinel on a paid API model."""
    tracker = UsageTracker()
    tracker.record(DEMO_SUBSCRIPTION_MODEL, "agent", RunUsage(input_tokens=240_000, output_tokens=18_000, requests=12))
    tracker.record(DEMO_MODEL, "sentinel", RunUsage(input_tokens=36_000, output_tokens=2_400, requests=6))
    return tracker


def _subscription(start: datetime) -> Transcript:
    t = Transcript(start)
    t.user("Refactor the date parsing in /workspace/api into one helper and run the tests.")
    t.run("grep -rn 'strptime' /workspace/api/src", "src/orders.py:14\nsrc/invoices.py:22\nsrc/reports.py:9")
    t.run("cd /workspace/api && uv run pytest -q", "48 passed in 3.1s", title="run api tests")
    t.assistant(
        "Done. The three `strptime` calls now go through `parse_date()` in `src/dates.py`, and all 48 tests pass."
    )
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
    )
    return t


_EXEC_TOOL = ToolDefinition(
    name="exec",
    description=(
        "Run a shell command in the session **sandbox**.\n\n"
        "- Domains and credentials it reaches are reviewed by the sentinel."
    ),
    parameters_json_schema={
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "The command, run with `bash -c`."},
            "title": {"type": "string"},
        },
        "required": ["command"],
    },
)
_READ_SKILL_TOOL = ToolDefinition(
    name="read_skill",
    description="Read a skill: its SKILL.md, its commands and whether they are on PATH. Call before using a skill.",
    parameters_json_schema={
        "type": "object",
        "properties": {"skill_name": {"type": "string"}},
        "required": ["skill_name"],
    },
)
_SEARCH = "web_search 'best fluffy pancake recipe'"
_WEB_SKILL = (
    "# Web\n\nSearch the web with `web_search`, read a page with `web_fetch`.\n\n"
    "# Commands\n"
    "- `web_fetch`: Fetch a web page as readable text\n"
    "- `web_search`: Search the web. Asks for: domain search.example.org, "
    "credential demo/web-search-api-key as $SEARCH_API_KEY.\n\n"
    "The commands are on PATH."
)
_FETCH = "web_fetch 'https://recipes.example.org/fluffy-pancakes'"


def _context(
    role: Literal["agent", "sentinel", "titler", "compaction"],
    at: datetime,
    instructions: str,
    messages: list[ModelRequest | ModelResponse],
    response: ModelResponse,
    *,
    tools: list[ToolDefinition] | None = None,
    seconds: float = 4,
) -> LlmContext:
    return LlmContext(
        request_id=f"demo-{role}",
        role=role,
        compaction_target="agent" if role == "compaction" else None,
        model_name=DEMO_MODEL,
        status="completed",
        started_at=at,
        completed_at=at + timedelta(seconds=seconds),
        instructions=[InstructionPart(instructions)],
        messages=messages,
        tool_definitions=tools or [],
        response=response,
        cost=request_cost(DEMO_MODEL, response),
    )


def _pancake_contexts(prompt: datetime) -> list[LlmContext]:
    """One latest request per agent role, matching the pancake transcript and its turn's timeline."""
    search_result = '[{"title": "Fluffy Pancakes", "url": "https://recipes.example.org/fluffy-pancakes"}]'
    return [
        _context(
            "agent",
            prompt + timedelta(seconds=22.6),
            "You are carapace, a personal agent. The sentinel reviews what a command wants from outside the sandbox.",
            [
                ModelRequest(parts=[UserPromptPart("I really need a pancake recipe")]),
                ModelResponse(parts=[ToolCallPart("read_skill", {"skill_name": "web"}, tool_call_id="call-1")]),
                ModelRequest(parts=[ToolReturnPart("read_skill", _WEB_SKILL, tool_call_id="call-1")]),
                ModelResponse(parts=[ToolCallPart("exec", {"command": _SEARCH}, tool_call_id="call-2")]),
                ModelRequest(parts=[ToolReturnPart("exec", search_result, tool_call_id="call-2")]),
                ModelResponse(
                    parts=[
                        ThinkingPart("The first result is a recipe page; fetch it."),
                        ToolCallPart("exec", {"command": _FETCH}, tool_call_id="call-3"),
                    ]
                ),
                ModelRequest(
                    parts=[
                        ToolReturnPart(
                            "exec",
                            "# Fluffy Pancakes\n\nMix the dry ingredients, whisk in milk, eggs and melted butter...",
                            tool_call_id="call-3",
                        )
                    ]
                ),
            ],
            ModelResponse(
                parts=[
                    TextPart(
                        "Here is a highly rated recipe for **classic fluffy pancakes** (about 8):\n\n"
                        "1. Whisk 200 g flour, 2 tbsp sugar, 2 tsp baking powder and a pinch of salt.\n"
                        "2. Stir in 300 ml milk, 2 eggs and 30 g melted butter until *just* combined.\n"
                        "3. Cook ladlefuls in a hot buttered pan, flip once bubbles form."
                    )
                ],
                usage=RequestUsage(
                    input_tokens=8_412,
                    output_tokens=2_400,
                    cache_read_tokens=6_900,
                    details={"reasoning_tokens": 1_600},
                ),
                model_name=DEMO_MODEL,
                provider_name="anthropic",
            ),
            tools=[_EXEC_TOOL, _READ_SKILL_TOOL],
            seconds=78,
        ),
        _context(
            "sentinel",
            prompt + timedelta(seconds=16.7),
            "You are the sentinel. Judge each boundary request against SECURITY.md: allow, escalate or deny.",
            [
                ModelRequest(
                    parts=[
                        UserPromptPart(
                            "New action log entries:\n- user: I really need a pancake recipe\n"
                            f"- tool_call exec: {_FETCH}\n\nEVALUATE domain_access_request:\n"
                            f"Domains: recipes.example.org\nRunning exec: {_FETCH}"
                        )
                    ]
                )
            ],
            ModelResponse(
                parts=[
                    ToolCallPart(
                        "judge",
                        {
                            "decision": "allow",
                            "explanation": "Fetching a recipe page from the search results is read-only.",
                            "risk_level": "low",
                        },
                        tool_call_id="judge-1",
                    )
                ],
                usage=RequestUsage(input_tokens=3_150, output_tokens=60),
                model_name=DEMO_MODEL,
            ),
            seconds=0.7,
        ),
        _context(
            "titler",
            prompt + timedelta(seconds=28),
            "Write a short, specific session title with one leading emoji.",
            [ModelRequest(parts=[UserPromptPart("user: I really need a pancake recipe")])],
            ModelResponse(
                parts=[TextPart("🥞 Classic Fluffy Pancake Recipe")],
                usage=RequestUsage(input_tokens=640, output_tokens=12),
                model_name=DEMO_MODEL,
            ),
        ),
        _context(
            "compaction",
            prompt + timedelta(seconds=29),
            "Compress a single tool output to save context. Reply with ONLY the summary.",
            [ModelRequest(parts=[UserPromptPart(f"<tool_output>\n{search_result}\n</tool_output>")])],
            ModelResponse(
                parts=[TextPart("One result: Fluffy Pancakes, https://recipes.example.org/fluffy-pancakes")],
                usage=RequestUsage(input_tokens=1_020, output_tokens=24),
                model_name=DEMO_MODEL,
            ),
        ),
    ]


def _request(
    role: LlmSource,
    request_id: str,
    started_at: datetime,
    completed_at: datetime,
    usage: RequestUsage,
    input_shape: InputShapeRatios | None = None,
) -> LlmRequestRecord:
    return LlmRequestRecord(
        ts=completed_at,
        request_id=request_id,
        source=role,
        model_name=DEMO_MODEL,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read_tokens=usage.cache_read_tokens,
        cache_write_tokens=usage.cache_write_tokens,
        cost=request_cost(DEMO_MODEL, ModelResponse(parts=[], usage=usage)),
        started_at=started_at,
        completed_at=completed_at,
        reasoning_tokens=usage.details.get("reasoning_tokens"),
        usage_details=dict(usage.details),
        input_shape=input_shape,
    )


# The server estimates these with tiktoken; fixed here so the seed stays offline and the pictures stable.
_INPUT_SHAPES = {
    "agent": InputShapeRatios(system=0.46, user=0.03, assistant=0.06, tool_calls=0.07, tool_returns=0.38),
    "sentinel": InputShapeRatios(system=0.71, user=0.29),
}


def _pancake_turn(prompt: datetime, contexts: list[LlmContext]) -> tuple[list[Span], list[LlmRequestRecord]]:
    """The pancake turn as the server records it, in seconds after the prompt, lined up with the transcript.

    Its LLM requests are the session's request log: the latest agent and sentinel requests are the
    role contexts; the titler and the tool-output compaction run outside the turn.
    """
    spans: list[Span] = []
    records: list[LlmRequestRecord] = []

    def at(seconds: float) -> datetime:
        return prompt + timedelta(seconds=seconds)

    def span(span_id: str, parent: str | None, kind: str, name: str, begin: float, end: float, **attrs: Any) -> str:
        spans.append(
            Span(
                span_id=span_id,
                parent_id=parent,
                kind=kind,
                name=name,
                started_at=at(begin),
                ended_at=at(end),
                status="ok",
                attrs=attrs,
            )
        )
        return span_id

    def request(
        record: LlmRequestRecord,
        parent: str,
        first_token: float,
        *,
        thinking: tuple[float, float] | None = None,
        first_text: float | None = None,
    ) -> None:
        records.append(
            record.model_copy(
                update={
                    "turn_id": PANCAKE_TURN_ID,
                    "span_id": parent,
                    "first_token_at": at(first_token),
                    "first_thinking_at": at(thinking[0]) if thinking else None,
                    "last_thinking_at": at(thinking[1]) if thinking else None,
                    "first_text_at": at(first_text) if first_text is not None else None,
                }
            )
        )

    def earlier(role: Literal["agent", "sentinel"], request_id: str, begin: float, end: float, usage: RequestUsage):
        return _request(role, request_id, at(begin), at(end), usage)

    context = {c.role: c for c in contexts}
    context_records = {
        role: _request(role, c.request_id, c.started_at, c.completed_at, c.response.usage, _INPUT_SHAPES.get(role))
        for role, c in context.items()
        if c.response is not None and c.completed_at is not None
    }

    root = span("demo-turn", None, "turn", "turn", 0, 101, prompt="I really need a pancake recipe")
    span("demo-prepare", root, "turn.prepare", "prepare", 0, 0.3)
    request(
        earlier(
            "agent",
            "demo-agent-1",
            0.3,
            1.8,
            RequestUsage(input_tokens=5_120, output_tokens=46, cache_write_tokens=4_900),
        ),
        root,
        0.8,
        thinking=(0.8, 1.3),
    )
    skill_tool = span("demo-tool-skill", root, "tool", "read_skill", 1.8, 5.0)
    span("demo-skill-build", skill_tool, "skill", "build wait", 2.0, 3.6, skill="web")
    span("demo-skill-sync", skill_tool, "skill", "profile sync", 3.6, 4.9, paths=4)
    request(
        earlier(
            "agent",
            "demo-agent-2",
            5.0,
            5.9,
            RequestUsage(input_tokens=5_890, output_tokens=58, cache_read_tokens=4_900, cache_write_tokens=760),
        ),
        root,
        5.6,
    )
    search = span("demo-tool-search", root, "tool", "exec", 5.9, 14.0)
    search_exec = span("demo-exec-search", search, "exec", "exec", 6.0, 14.0, command=_SEARCH, exit_code=0)
    sandbox = span("demo-sandbox", search_exec, "sandbox", "ensure", 6.0, 7.2)
    span("demo-sandbox-resume", sandbox, "sandbox", "resume", 6.0, 6.5)
    span("demo-sandbox-ready", sandbox, "sandbox", "wait_for_ready", 6.5, 7.2, ready=True)
    span(
        "demo-domain-search",
        search_exec,
        "domain",
        "search.example.org",
        8.6,
        9.0,
        domain="search.example.org",
        allowed=True,
    )
    span("demo-wait", search_exec, "wait", "demo/web-search-api-key", 9.1, 10.8, reason="credential")
    span("demo-credential", search_exec, "credential", "demo/web-search-api-key", 10.8, 11.0, fetch="password")
    request(
        earlier(
            "agent",
            "demo-agent-3",
            14.0,
            15.1,
            RequestUsage(input_tokens=6_970, output_tokens=71, cache_read_tokens=5_660, cache_write_tokens=1_080),
        ),
        root,
        14.7,
    )
    fetch = span("demo-tool-fetch", root, "tool", "exec", 15.1, 21.0)
    fetch_exec = span("demo-exec-fetch", fetch, "exec", "exec", 15.2, 21.0, command=_FETCH, exit_code=0)
    fetch_domain = span(
        "demo-domain-fetch",
        fetch_exec,
        "domain",
        "recipes.example.org",
        16.6,
        18.0,
        domain="recipes.example.org",
        allowed=True,
    )
    fetch_review = span(
        "demo-sentinel-fetch",
        fetch_domain,
        "sentinel",
        "domain_access",
        16.65,
        17.95,
        subject=f"recipes.example.org via {_FETCH}",
        verdict="allow",
    )
    request(context_records["sentinel"], fetch_review, 17.2, first_text=17.2)
    request(context_records["agent"], root, 23.4, thinking=(23.4, 60.0), first_text=60.0)

    records += [context_records["titler"], context_records["compaction"]]
    return spans, sorted(records, key=lambda record: record.ts)


def _artifact_page(title: str, *, trend: bool) -> str:
    bars = "".join(
        f'<div class="row"><span>{region}</span><i style="width:{share}%"></i><b>{revenue}</b></div>'
        for region, share, revenue in (("North", 92, "€1.84M"), ("West", 74, "€1.48M"), ("South", 51, "€1.02M"))
    )
    months = (
        '<h2>Monthly trend</h2><div class="trend"><i style="height:58%"></i><i style="height:71%"></i>'
        '<i style="height:96%"></i></div><p class="legend">July · August · September</p>'
        if trend
        else ""
    )
    return (
        f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{title}</title>'
        '<meta name="viewport" content="width=device-width, initial-scale=1"><style>'
        ":root{--bg:#fff;--fg:#1c1917;--muted:#78716c;--bar:#0d9488}"
        "@media (prefers-color-scheme: dark){:root{--bg:#1c1917;--fg:#f5f5f4;--muted:#a8a29e;--bar:#2dd4bf}}"
        "body{margin:0;padding:24px;font:15px/1.5 system-ui,sans-serif;background:var(--bg);color:var(--fg)}"
        "h1{margin:0 0 4px;font-size:22px}h2{margin:24px 0 8px;font-size:16px}p{margin:0;color:var(--muted)}"
        ".row{display:grid;grid-template-columns:64px 1fr 72px;gap:12px;align-items:center;margin-top:12px}"
        ".row i,.trend i{display:block;background:var(--bar);border-radius:4px}.row i{height:14px}"
        ".row b{text-align:right}.trend{display:flex;align-items:flex-end;gap:16px;height:120px}"
        ".trend i{flex:1}.legend{margin-top:6px;font-size:13px}"
        f"</style></head><body><h1>{title}</h1><p>Revenue by region, demo data</p>{bars}{months}</body></html>"
    )


def _artifact_reference(t: Transcript, slug: str, title: str) -> None:
    tool_id = t.call("show_artifact", {"slug": slug})
    t.result(tool_id, "show_artifact", json.dumps({"slug": slug, "title": title}))


def _sales_dashboard(start: datetime) -> Transcript:
    t = Transcript(start)
    t.user("Sketch a quick sales overview I can look at in the chat.")
    write = t.call(
        "write",
        {"path": "/workspace/artifacts/sales-draft/index.html", "content": _artifact_page("Sales draft", trend=False)},
    )
    t.result(write, "write", "Wrote 1 line to /workspace/artifacts/sales-draft/index.html")
    t.run(
        'git add artifacts/sales-draft && git commit -m "Add sales draft" && git push',
        "[main 4a1c2e9] Add sales draft\n 1 file changed, 1 insertion(+)",
        source="sentinel",
        explanation="A self-contained artifact without scripts or external URLs.",
    )
    _artifact_reference(t, "sales-draft", "Sales draft")
    t.assistant("Here is a first draft with revenue per region.")
    t.user("Make it a proper Q3 dashboard with a stable name, and drop the draft.")
    t.run(
        'git mv artifacts/sales-draft artifacts/q3-sales && git commit -m "Turn the draft into the Q3 dashboard" '
        "&& git push",
        "[main 7be03d4] Turn the draft into the Q3 dashboard\n 1 file changed, 1 insertion(+), 1 deletion(-)",
        source="sentinel",
        explanation="Renames the user's artifact as requested; no navigation or external resources.",
    )
    _artifact_reference(t, "q3-sales", "Q3 sales by region")
    t.assistant("The dashboard now lives at `q3-sales`. The old draft is gone.")
    t.user("Add the monthly trend, please.")
    t.run(
        'git commit -am "Add the monthly trend" && git push',
        "[main c91f5b0] Add the monthly trend\n 1 file changed, 1 insertion(+), 1 deletion(-)",
        source="sentinel",
        explanation="Adds a static chart to the same artifact.",
    )
    _artifact_reference(t, "q3-sales", "Q3 sales by region")
    t.assistant("Done: the dashboard shows the monthly trend below the regions.")
    return t


def _seed_artifacts(data_dir: Path, start: datetime) -> None:
    """Commit the sales dashboard's history into the demo user's knowledge repo, as the session pushed it."""
    repo = resolve_user_knowledge_dir(data_dir, DEMO_USER)
    repo.mkdir(parents=True, exist_ok=True)

    def git(*args: str, at: datetime | None = None) -> None:
        dates = {"GIT_AUTHOR_DATE": at.isoformat(), "GIT_COMMITTER_DATE": at.isoformat()} if at else {}
        subprocess.run(
            ["git", "-c", "user.name=carapace", "-c", "user.email=carapace@demo", *args],
            cwd=repo,
            check=True,
            capture_output=True,
            env={**os.environ, **dates},
        )

    def commit(message: str, minutes: int) -> None:
        git(
            "commit",
            "-m",
            message,
            "-m",
            f"carapace-session: {ARTIFACT_SESSION}",
            at=start + timedelta(minutes=minutes),
        )

    git("init", "-b", "main")
    draft = repo / "artifacts" / "sales-draft" / "index.html"
    draft.parent.mkdir(parents=True)
    draft.write_text(_artifact_page("Sales draft", trend=False), encoding="utf-8")
    git("add", "artifacts")
    commit("Add sales draft", 1)
    git("mv", "artifacts/sales-draft", "artifacts/q3-sales")
    (repo / "artifacts" / "q3-sales" / "index.html").write_text(
        _artifact_page("Q3 sales by region", trend=False), encoding="utf-8"
    )
    git("add", "artifacts")
    commit("Turn the draft into the Q3 dashboard", 3)
    (repo / "artifacts" / "q3-sales" / "index.html").write_text(
        _artifact_page("Q3 sales by region", trend=True), encoding="utf-8"
    )
    git("add", "artifacts")
    commit("Add the monthly trend", 5)


def demo_sessions(now: datetime) -> list[DemoSession]:
    budget_usage = _usage(180_000, 24_000)
    budget_stop_budget = SessionBudget(cost_usd=Decimal("0.75"))
    return [
        DemoSession(
            "demo-sandbox-tour",
            "🧭 Getting To Know The Sandbox",
            _sandbox_tour(now - timedelta(hours=26)),
            usage=_usage(9_800, 1_100),
            sandbox=_sandbox("stopped", 252_000, now),
        ),
        DemoSession(
            "demo-pancake-recipe",
            "🥞 Classic Fluffy Pancake Recipe",
            pancake := _pancake_recipe(now - timedelta(hours=23)),
            usage=_usage(21_000, 4_300),
            sandbox=_sandbox("running", 59_000_000, now),
            llm_contexts=(
                pancake_contexts := _pancake_contexts(
                    pancake_prompt := datetime.fromisoformat(pancake.events[0]["timestamp"])
                )
            ),
            llm_requests=(pancake_turn := _pancake_turn(pancake_prompt, pancake_contexts))[1],
            turn_spans={PANCAKE_TURN_ID: pancake_turn[0]},
        ),
        DemoSession(
            "demo-recipe-skill",
            "🛠️ Creating A Recipe Skill",
            _recipe_skill(now - timedelta(hours=5)),
            usage=_usage(42_000, 3_200),
            sandbox=_sandbox("running", 61_000_000, now),
        ),
        DemoSession(
            "demo-blocked-post",
            "📮 HTTP POST Blocked In Ask Mode",
            _blocked_post(now - timedelta(hours=3)),
            attributes=SessionAttributes(ask_mode=True),
            usage=_usage(2_500, 300),
        ),
        DemoSession(
            "demo-internal-host",
            "🏠 Checking The Document Server",
            _internal_host(now - timedelta(hours=2, minutes=30)),
            usage=_usage(2_300, 260),
        ),
        DemoSession(
            "demo-change-request",
            "🥞 Fixing The Pancake Ingredients",
            _change_request(now - timedelta(hours=2)),
            usage=_usage(4_100, 380),
        ),
        DemoSession(
            "demo-pending-approval",
            "🗄️ Cleaning Up NAS Backups",
            _pending_approval(now - timedelta(minutes=50)),
        ),
        DemoSession(
            "demo-budget-stop",
            "💸 Triage Open Issues",
            _budget_stop(now - timedelta(minutes=30), budget_usage, budget_stop_budget),
            budget=budget_stop_budget,
            usage=budget_usage,
        ),
        DemoSession(
            "demo-unexpected-error",
            "🔌 LED Controller Pinout",
            _unexpected_error(now - timedelta(minutes=20)),
            usage=_usage(3_200, 410),
        ),
        DemoSession(
            "demo-autonomy-limit",
            "📦 Checking Outdated Dependencies",
            _autonomy_limit(now - timedelta(minutes=10)),
            budget=SessionBudget(autonomous_tool_calls=3),
            usage=_usage(7_200, 600),
        ),
        DemoSession(
            ARTIFACT_SESSION,
            "📊 Q3 Sales Dashboard",
            _sales_dashboard(now - timedelta(minutes=15)),
            usage=_usage(12_400, 2_900),
        ),
        DemoSession(
            "demo-subscription",
            "🔁 Refactoring Date Parsing",
            _subscription(now - timedelta(minutes=5)),
            budget=SessionBudget(cost_usd=Decimal("0.50"), equivalent_cost_usd=Decimal("2.00")),
            usage=_subscription_usage(),
        ),
    ]


@dataclass(frozen=True)
class DemoExtraction:
    session_id: str
    model: str
    cost_usd: Decimal
    abstract: str
    fact: Fact


DEMO_EXTRACTIONS = (
    DemoExtraction(
        "demo-pancake-recipe",
        DEMO_MODEL,
        Decimal("0.0214"),
        "The user wanted a fluffy pancake recipe; the agent found one and summarized it.",
        Fact(
            category="user",
            statement="Likes fluffy American-style pancakes.",
            source_seqs=[0],
            source_kind="user_said",
            confidence="medium",
            durability="durable",
        ),
    ),
    DemoExtraction(
        "demo-subscription",
        DEMO_SUBSCRIPTION_MODEL,
        Decimal("0.0386"),
        "The user had the date parsing in the api project refactored into one helper; all tests pass.",
        Fact(
            category="surroundings",
            statement="The api project parses dates through parse_date() in src/dates.py.",
            source_seqs=[2],
            source_kind="observed",
            confidence="high",
            durability="durable",
        ),
    ),
)
# Left pending, so the run dialog has something to estimate.
DEMO_PENDING_EXTRACTION = "demo-recipe-skill"


def _seed_memory(session_factory: SessionFactory, sessions: list[DemoSession], now: datetime) -> None:
    """Finished extractions with their spend in today's budget window, plus one pending task."""
    store = MemoryStore(session_factory)
    timezone = ZoneInfo(DEMO_USER_CONFIG.timezone)
    weeks = {
        demo.session_id: week_key(datetime.fromisoformat(demo.transcript.events[0]["timestamp"]), timezone)
        for demo in sessions
    }
    prompt_version = SESSION_EXTRACT.version(SessionExtractionOutput)
    for demo in DEMO_EXTRACTIONS:
        task = store.spawn(
            DEMO_USER,
            TaskKind.session_extract,
            demo.session_id,
            spawned_by=SpawnedBy.manual,
            now=now,
            session_week_key=weeks[demo.session_id],
            estimate=TaskEstimate(
                model=demo.model, input_tokens=6_000, output_tokens_cap=2_000, equivalent_cost_usd=demo.cost_usd
            ),
        )
        assert task is not None
        store.run(DEMO_USER, TaskSelection(ids=[task.id]), None, now)
        store.claim(task.id, now)
        provenance = Provenance(
            carapace_version="demo",
            model=demo.model,
            prompt_version=prompt_version,
            input_format_version=INPUT_FORMAT_VERSION,
            input_hash=f"demo-{demo.session_id}",
            input_tokens=5_800,
            output_tokens=640,
            equivalent_cost_usd=demo.cost_usd,
            duration_ms=7_400,
            task_id=task.id,
            created_at=now,
        )
        extraction = SessionExtraction(
            abstract=demo.abstract, outcomes=[], open_loops=[], on_my_mind=[], facts=[demo.fact], friction=[], tags=[]
        )
        week = weeks[demo.session_id]
        result = ExtractionResult(
            session_id=demo.session_id, week_key=week, month_key=month_key_for_week(week), extraction=extraction
        )
        store.record_outcome(task.id, TaskOutcome(provenance=provenance, result=result), now)
    store.spawn(
        DEMO_USER,
        TaskKind.session_extract,
        DEMO_PENDING_EXTRACTION,
        spawned_by=SpawnedBy.manual,
        now=now,
        session_week_key=weeks[DEMO_PENDING_EXTRACTION],
        estimate=TaskEstimate(
            model=DEMO_SUBSCRIPTION_MODEL,
            input_tokens=9_000,
            output_tokens_cap=2_000,
            equivalent_cost_usd=Decimal("0.05"),
        ),
    )


def _require_throwaway_database(data_dir: Path, url: str) -> None:
    """Refuse anything but a SQLite file inside DATA_DIR, e.g. a CARAPACE_DATABASE_URL to a real Postgres."""
    database = make_url(url).database
    if not url.startswith("sqlite") or not database or not Path(database).resolve().is_relative_to(data_dir):
        sys.exit(f"Refusing to seed {url}: the demo database must be a SQLite file inside {data_dir}.")


def seed(data_dir: Path, now: datetime, *, dev_stack: bool = False) -> None:
    # A real data dir (e.g. ./data) also keeps its SQLite file inside, so only a temp dir is
    # throwaway enough, unless the caller says it is a dev stack's. A data dir with sessions is refused
    # either way. This runs before anything opens the database.
    temp_root = Path(tempfile.gettempdir()).resolve()
    if not dev_stack and not data_dir.is_relative_to(temp_root):
        sys.exit(f"Refusing to seed {data_dir}: the demo data dir must be inside {temp_root} (use mktemp -d).")
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
        username=DEMO_USER, password=DEMO_PASSWORD, display_name="Demo User", config=DEMO_USER_CONFIG
    )
    sessions = demo_sessions(now)
    for demo in sessions:
        events = demo.transcript.events
        created_at = datetime.fromisoformat(events[0]["timestamp"])
        session_id = demo.session_id
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
        for context in demo.llm_contexts:
            session_mgr.save_llm_context(session_id, context)
        session_mgr.save_llm_request_log(session_id, LlmRequestLog(records=demo.llm_requests))
        for turn_id, spans in demo.turn_spans.items():
            session_mgr.save_turn_spans(session_id, turn_id, spans)
        print(f"{session_id}  {demo.title}")
    artifact_session = next(demo for demo in sessions if demo.session_id == ARTIFACT_SESSION)
    _seed_artifacts(data_dir, datetime.fromisoformat(artifact_session.transcript.events[0]["timestamp"]))
    _seed_memory(session_factory, sessions, now)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("data_dir", type=Path, help="throwaway CARAPACE_DATA_DIR of the demo server")
    parser.add_argument(
        "--dev-stack", action="store_true", help="DATA_DIR is a dev stack's, so it need not be in the temp directory"
    )
    args = parser.parse_args()
    seed(args.data_dir.resolve(), datetime.now(tz=UTC).replace(second=0, microsecond=0), dev_stack=args.dev_stack)
    print(f"Log in as {DEMO_USER!r} with password {DEMO_PASSWORD!r}.")


if __name__ == "__main__":
    main()
