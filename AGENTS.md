# AGENTS.md

## Project overview

Carapace is a security-first personal AI agent with LLM-powered security gating. Python 3.12+, async, Pydantic AI.

## Setup commands

- Install deps: `uv sync`
- Install with dev deps: `uv sync --dev`
- Start server: `uv run python -m carapace` (or `uv run carapace-server`)
- Start CLI client: `uv run python -m carapace.cli` (or `uv run carapace`)
- Start frontend: `cd frontend && npm install && npm run dev`
- Run tests: `uv run pytest`
- Run single test: `uv run pytest tests/test_cli.py -k test_help`

## Code style

- Python 3.12+ — use modern syntax (`match`, f-strings, `str | None`, lowercase generics)
- Fully typed: all function signatures have type annotations (params + return)
- `from __future__ import annotations` in every module
- Async by default for I/O-bound code
- Concise, functional style: comprehensions, early returns, small pure helpers
- Pydantic `BaseModel` / `@dataclass` for structured data — no raw dicts
- `pathlib.Path` over `os.path`
- Logging: `loguru` (`from loguru import logger`) — never stdlib `logging`. Use f-strings in log calls.
- Imports ordered: stdlib → third-party → local, separated by blank lines
- No deferred (in-function) imports or `TYPE_CHECKING` guards — restructure modules to break circular dependencies instead
- Linting: `uvx ruff check src/` — fix all warnings before committing

## Project structure

```text
src/carapace/          # main package
  server.py            # FastAPI server (REST + WebSocket)
  cli.py               # Thin CLI client (HTTP + WS)
  agent.py             # Pydantic AI agent definition and tools
  auth.py              # Bearer token generation and validation
  ws_models.py         # WebSocket message protocol models
  config.py            # configuration loading
  models.py            # Pydantic models and dataclasses
  usage.py             # token usage tracking (ModelUsage, UsageTracker)
  session.py           # session management
  memory.py            # markdown-based persistent memory
  skills.py            # skill registry
  credentials.py       # password-manager-backed credentials
  security/
    __init__.py        # public API: evaluate(), evaluate_domain(), safe-list
    sentinel.py         # LLM-powered security agent (shadow conversation)
    context.py         # action log entries, sentinel verdict, session security state
frontend/              # Next.js web UI (React 19, Tailwind CSS 4)
  src/app/             # Next.js app router pages and layout
  src/components/      # React components (chat, sidebar, approval flow)
  src/hooks/           # custom hooks (WebSocket connection)
tests/                 # pytest tests
data/                  # runtime data directory (config, security policy, memory, sessions)
```

## Testing

- Framework: pytest
- Run all tests: `uv run pytest`
- Tests live in `tests/` and are prefixed `test_`
- CLI tests use `typer.testing.CliRunner`
- No LLM tokens needed for smoke tests

## CI

- GitHub Actions on pull requests
- Steps: `uv sync --dev` → `uv run pytest` → pre-commit checks
- Python 3.14 in CI

## Key conventions

- Commit messages use [gitmoji](https://gitmoji.dev/) (e.g. `🐛 fix:`, `✨ feat:`, `♻️ refactor:`)
- Never commit without asking first. Suggest committing isolated changes by showing the proposed commit message, then wait for confirmation.
- Security policy is a natural-language `SECURITY.md` that becomes the sentinel agent's system prompt
- Every tool call goes through a safe-list check, then an LLM sentinel gate (`security.evaluate()`)
- The sentinel maintains a persistent shadow conversation per session for contextual decisions
- An append-only action log tracks all agent actions, user messages, and security decisions
- Skills follow the open [AgentSkills](https://agentskills.io/) format
- All runtime state lives under `$CARAPACE_DATA_DIR` (defaults to `./data`)
- Secrets come from a password manager, never stored in the repo
