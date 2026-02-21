# AGENTS.md

## Project overview

Carapace is a security-first personal AI agent with rule-based information flow control. Python 3.12+, async, Pydantic AI.

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

## Project structure

```
src/carapace/          # main package
  server.py            # FastAPI server (REST + WebSocket)
  cli.py               # Thin CLI client (HTTP + WS)
  agent.py             # Pydantic AI agent definition and tools
  auth.py              # Bearer token generation and validation
  ws_models.py         # WebSocket message protocol models
  config.py            # configuration loading
  models.py            # Pydantic models and dataclasses
  session.py           # session management
  memory.py            # markdown-based persistent memory
  skills.py            # skill registry
  credentials.py       # password-manager-backed credentials
  security/
    classifier.py      # LLM-based operation classifier
    engine.py          # rule evaluation engine
frontend/              # Next.js web UI (React 19, Tailwind CSS 4)
  src/app/             # Next.js app router pages and layout
  src/components/      # React components (chat, sidebar, approval flow)
  src/hooks/           # custom hooks (WebSocket connection)
tests/                 # pytest tests
data/                  # runtime data directory (config, rules, memory, sessions)
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

- Security rules are plain-English YAML evaluated by an LLM at runtime
- Every tool call goes through a classification + rule-check gate (`_gate` in `agent.py`)
- Skills follow the open [AgentSkills](https://agentskills.io/) format
- All runtime state lives under `$CARAPACE_DATA_DIR` (defaults to `./data`)
- Secrets come from a password manager, never stored in the repo
