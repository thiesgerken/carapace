# AGENTS.md

## Project overview

carapace is a security-first personal AI agent with LLM-powered security gating. Python 3.12+, async, Pydantic AI.

## Setup commands

- Enter the pinned toolchain: `nix develop` (or `direnv allow` with nix-direnv). uv still manages `.venv`; the shell sets `UV_PYTHON` and disables interpreter downloads.
- Install client-only deps: `uv sync` (base package is the CLI client; ~16 light deps)
- Install server stack: `uv sync --extra server`
- Install with dev deps: `uv sync --dev` (includes the `server` extra)
- Start the dev stack (server, frontend, Redis, builder, sandboxes): `process-compose up` in the dev shell; ports from `CARAPACE_DEV_STACK` in `.env` (stack 0: frontend 7300, server 7301), demo data via `process-compose process start demo`. See "Dev stack" in `docs/development.md`
- Start server alone: `uv run python -m carapace` (or `uv run carapace-server`) — needs the `server` extra
- Start CLI client: `uv run python -m carapace.cli` (or `uv run carapace`)
- Start frontend: `cd frontend && npm ci && npm run dev`
- Run type checks: `uv run pyrefly check`
- Run tests: `uv run pytest`
- Run single test: `uv run pytest tests/test_cli.py -k test_help`
- Build runtime images: `nix build .#packages.<system>.{server,frontend,bitwarden,sandbox,builder}-image`; use `aarch64-linux` via the native Linux builder on Apple Silicon.
- Nix checks: `nix flake check` on Linux, or `nix flake check --system aarch64-linux` through the builder. See `docs/development.md`.

## Code style

- Python 3.12+ — use modern syntax (`match`, f-strings, `str | None`, lowercase generics)
- Fully typed: all function signatures have type annotations (params + return)
- `from __future__ import annotations` in every module
- Async by default for I/O-bound code
- Concise, functional style: comprehensions, early returns, small pure helpers
- Pydantic `BaseModel` / `@dataclass` for structured data — no raw dicts
- `pathlib.Path` over `os.path`
- Logging: `loguru` (`from loguru import logger`) — never stdlib `logging`. Use f-strings in log calls.
- No silent failures: don't swallow exceptions with bare `except` or `except Exception` + `logger.warning`. Let errors propagate; catch only specific, expected exceptions. If something goes wrong, it should be loud.
- Imports ordered: stdlib → third-party → local, separated by blank lines
- Local `carapace` imports should be relative inside the package (`from .foo` / `from ..foo`) unless an import string or external integration requires an absolute path.
- No deferred (in-function) imports or `TYPE_CHECKING` guards — restructure modules to break circular dependencies instead
- Linting: `uvx ruff check src/` — fix all warnings before committing
- Git hooks use [prek](https://github.com/j178/prek) (`prek install`). Stage your changes, then run `prek run` before committing to catch issues early — this avoids the commit being rejected and having to re-run the git command.

## Project structure

```text
src/carapace/          # main package
  server/              # FastAPI server package (REST, WebSocket, startup wiring)
    __init__.py        # public facade: app, sandbox_app, main, shared runtime state
    auth.py            # FastAPI bearer/WebSocket auth dependencies
    notifications.py   # notification and presence routes
    websocket.py       # WebSocket chat and small web-facing routes
  cli.py               # Thin CLI client (HTTP + WS)
  auth.py              # Bearer token generation and validation
  bootstrap.py         # first-run directory and file seeding
  config.py            # configuration loading
  models.py            # Pydantic models and dataclasses
  ws_models.py         # WebSocket message protocol models
  usage.py             # token usage tracking (ModelUsage, UsageTracker)
  spans.py             # timing spans of a running turn (TurnTrace, span(), attach_sandbox_call)
  prompt_prefix.py     # shared system prompt prefix (AGENTS/SOUL/USER.md, skill catalog)
  prompt_preview.py    # what every LLM role sends, split into sections (GET /api/prompts/preview)
  skills.py            # skill registry
  credentials.py       # password-manager-backed credentials
  agent/
    __init__.py        # re-exports (create_agent, build_system_prompt, run_agent_turn)
    tools.py           # Pydantic AI agent definition and tools
    loop.py            # channel-agnostic agent turn runner
    tool_stream.py     # streams tool calls to clients while the model writes them
  session/
    __init__.py        # re-exports (SessionEngine, SessionManager)
    engine.py          # session lifecycle, slash commands, agent turn orchestration
    manager.py         # session persistence (load, save, list, delete)
    titler.py          # LLM-powered session title generation
    timeline.py        # turn list and turn timeline read model (spans joined with LLM requests)
  git/
    __init__.py        # re-exports (GitHttpHandler, GitStore)
    http.py            # Git HTTP Smart Protocol handler (git http-backend CGI)
    store.py           # Git CLI wrapper (init, commit, push, pull, hooks)
  builder/
    app.py             # skill builder service (carapace-builder): build API, start-up sandbox probe
    nix.py             # the nix build/eval subprocesses behind it
    client.py          # the server's client for the builder
  memory/
    service.py         # MemoryService facade: long-term memory tasks, worker, queries (see docs/memory.md)
  security/
    __init__.py        # public API: record_tool_call(), evaluate_domain_with(), boundary and push evaluations
    sentinel.py        # LLM-powered security agent (shadow conversation)
    context.py         # action log entries, sentinel verdict, session security state
  sandbox/
    manager.py         # sandbox container lifecycle and auth
    proxy.py           # HTTP forward proxy with per-exec domain approvals
    runtime.py         # abstract container runtime interface
    docker.py          # Docker runtime implementation
    kubernetes.py      # Kubernetes runtime implementation
  channels/
    matrix/            # Matrix chat channel integration
frontend/              # Next.js web UI (React 19, Tailwind CSS 4)
  src/app/             # Next.js app router pages and layout
  src/components/      # React components (chat, sidebar, approval flow)
  src/hooks/           # custom hooks (WebSocket connection)
tests/                 # pytest tests
data/                  # runtime data directory (config, sessions, notifications, knowledge repo)
```

## Testing

- Framework: pytest
- Run all tests: `uv run pytest`
- Run `uv run pyrefly check` in addition to tests before opening or updating a PR
- Tests live in `tests/` and are prefixed `test_`
- CLI tests use `typer.testing.CliRunner`
- No LLM tokens needed for smoke tests

## CI

- GitHub Actions PR CI calls reusable `nix-verify.yml`: nix-fast-build realizes `ciBuilds.x86_64-linux` (pytest, pyrefly, Ruff, frontend lint/test/build, Helm, packages, and images).
- Verification loads all images, runs `scripts/smoke-images.py`, and uploads verified archives without registry write permissions.
- `prek` stays a separate job because its hooks fetch from the network.
- Trusted `workflow_run` PR publication checks open-PR/same-repo/same-SHA provenance before publishing archives and charts.
- `release.yml` releases every push to `main` with Presswerk (declared in the flake's `presswerk.default`): the push run prepares and pushes the release commit, the dispatched candidate run verifies it with `nix-verify.yml` and publishes tag, Nix images, chart and GitHub Release from Cachix.
- Python 3.14 comes from pinned nixpkgs; Python dependencies come from `uv.lock` via uv2nix. Nix is the single build/check definition for application images.

## Key conventions

- Commit messages use [gitmoji](https://gitmoji.dev/) (e.g. `🐛 fix:`, `✨ feat:`, `♻️ refactor:`). The emoji sets the release level per [Presswerk's Gitmoji catalog](https://presswerk.dev/reference/analyzers/gitmoji/), with ♻️ and 👷 raised to patch
- Try to commit isolated fixes / features
- Security policy is a natural-language `SECURITY.md` that becomes the sentinel agent's system prompt
- Tool calls are not reviewed: `security.record_tool_call()` puts each one into the action log. The LLM sentinel reviews what crosses the sandbox boundary (proxy domains, credentials, `cgate request`, git pushes)
- The sentinel maintains a persistent shadow conversation per session for contextual decisions
- An append-only action log tracks all agent actions, user messages, and security decisions
- Skills follow the open [AgentSkills](https://agentskills.io/) format
- All runtime state lives under `$CARAPACE_DATA_DIR` (defaults to `./data`)
- Secrets come from a password manager, never stored in the repo
- Frontend colors come from the semantic tokens in `frontend/src/app/globals.css` (`primary`, `success`, `info`, `warning`, `destructive`, the `surface`/`inset` levels), never from raw Tailwind palette classes; only categorical series (debug timeline, context breakdown, budget gauges, prompt sections) keep a palette. Panels differ by background, not by bordered cards
- UI PRs get screenshots of the changed pages (before/after, light/dark, phone if the layout changes), demo data only, attached with `gh pr edit --attach`; see "Screenshots" in `docs/development.md`
- Prefix caching is a hard requirement, not an optimization: a miss re-bills the whole system prompt and conversation (as a cache write on Anthropic). LLM system prompts put the stable shared prefix first (`prompt_prefix.shared_prompt_prefix()`), then role instructions, and anything volatile (current time, session ID, per-call data) last. Never put volatile text or a per-role split before the long shared text, and don't change tool definitions or instructions mid-session. Anything that has to break the prefix needs a stated reason and a mention in `docs/persistent-context.md` (see its known breaks)
