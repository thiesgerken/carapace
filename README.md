# Carapace

> **Disclaimer:** This is a pet project, born out of curiosity to
>
> - find out what hurdles arise when trying to build a "safe" OpenClaw,
> - see how far I can get by only assuming the reviewer / architect role, letting Cursor do the rest.

A security-first personal AI agent with rule-based information flow control.

Carapace is a self-hosted AI agent gateway that connects to Matrix (and future channels) and lets you interact with an AI assistant from anywhere. Unlike other agent frameworks that start with broad access and lock down after the fact, Carapace starts with **zero access** and grants capabilities through **plain-English security rules** evaluated by an LLM.

## Key ideas

- **Escalating friction.** The more access the agent has requested during a session, the harder it becomes for it to do anything without human approval. Early actions may be auto-approved; later ones require explicit consent.
- **Rules, not permissions.** Security is defined in plain English ("if the agent read something from the internet, it can't do any write ops without approval"). An LLM evaluates whether each rule applies to the current operation in context.
- **Plan before act.** The agent always proposes a plan before executing multi-step tasks. Rules are pre-evaluated against the plan and the user gets one consolidated approval prompt instead of being asked at every step.
- **Read-only by default.** The agent's base workspace is a read-only Docker container with no network. It can explore files, read skills, search memory freely. All actions (writes, network, API calls) go through skill containers with explicit sandboxing.
- **Skills are trusted code.** A personal agent has access to so much of your data and life that running completely untrusted skills through it would be reckless. The user (or an LLM acting on their behalf) is responsible for reviewing skills before installing them. The security model protects against the agent being _influenced by outside data_ to misuse skills, not against malicious skills themselves.
- **Skills are portable.** Skills follow the open [AgentSkills](https://agentskills.io/) format (SKILL.md + scripts). They work in Claude Code, Cursor, Gemini CLI too. Carapace extends the format with `carapace.yaml` for credentials and security hints, and optional `Dockerfile` for dependency isolation.
- **The agent improves itself.** Carapace can write new skills, update its memory, and evolve its personality -- all gated by the same rule system. No special "architect mode", just rules the user can temporarily relax.
- **Credentials stay in your vault.** Carapace doesn't store secrets. It fetches credentials from your password manager (Vaultwarden, 1Password, pass) on demand, with per-session approval.

## Architecture overview

```text
CLI Client (typer + rich)    Web UI (Next.js)
        \                      /
         REST + WebSocket (bearer token auth)
                    |
              FastAPI Server
                    |
         Session Manager ---- Rule Engine (LLM-evaluated)
              |                     |
         Pydantic AI Agent --- Approval Gate
              |                     |
         Skill Registry       WebSocket (sends approval requests)
              |
        Docker Containers
         ├── Base Container (read-only, no network)
         └── Skill Containers (from Dockerfile, with credentials)
```

The server runs the agent and all logic. The CLI and web UI are thin clients that connect via HTTP (sessions) and WebSocket (chat, slash commands, approval flow).

See [docs/architecture.md](docs/architecture.md) for the full architecture with diagrams.

## Core concepts

| Concept             | Description                                              | Doc                                                            |
| ------------------- | -------------------------------------------------------- | -------------------------------------------------------------- |
| Rules               | Plain-English security policies evaluated by LLM         | [docs/rules.md](docs/rules.md)                                 |
| Skills              | AgentSkills-compatible, Dockerfile-isolated capabilities | [docs/skills.md](docs/skills.md)                               |
| Sandbox             | Docker-first execution with read-only base container     | [docs/sandbox.md](docs/sandbox.md)                             |
| Sessions & Channels | Channel-decoupled persistent sessions                    | [docs/sessions-and-channels.md](docs/sessions-and-channels.md) |
| Memory              | Markdown-based memory with vector search                 | [docs/memory.md](docs/memory.md)                               |
| Credentials         | Password-manager-backed, per-session approval            | [docs/credentials.md](docs/credentials.md)                     |

## Technology stack

- **Python 3.12+** with **Pydantic AI** (agents, tools, dependency injection)
- **FastAPI** + **uvicorn** for the server, **WebSockets** for real-time chat
- **Next.js 16** + **React 19** + **Tailwind CSS 4** for the web UI
- **matrix-nio** for Matrix E2EE
- **Docker** for all tool execution (docker-py SDK)
- **Pydantic v2** for config and models
- **Pydantic Logfire** for observability (OpenTelemetry)
- **uv** for packaging, **Docker Compose** for deployment

## Data directory

All state lives under `$CARAPACE_DATA_DIR` (defaults to `./data`).

```
$CARAPACE_DATA_DIR/
  config.yaml            # main configuration
  rules.yaml             # security rules (plain English)
  server.token           # bearer token (auto-generated on first start)
  AGENTS.md              # agent behavioral guide
  SOUL.md                # agent personality
  USER.md                # about the human
  TOOLS.md               # local environment notes
  HEARTBEAT.md           # periodic task checklist
  skills/                # AgentSkills-format skill folders
  memory/                # Markdown-based persistent memory
  sessions/              # per-session history and state
  tmp/                   # shared writable volume for containers
  logs/
```

## Comparison with OpenClaw

Carapace is inspired by [OpenClaw](https://docs.openclaw.ai/) but differs fundamentally in security philosophy:

- **OpenClaw** is perimeter-based: control who can talk to the bot, then trust the bot broadly.
- **Carapace** is flow-based: the bot starts untrusted and every capability is gated by rules that track what happened in the session so far.

Other differences: Carapace is Python (not Node), uses Pydantic AI (not a custom agent loop), runs everything in Docker (not on the host), delegates credentials to a password manager (not built-in storage), and uses the open AgentSkills format (not a custom skill system).

## Getting started

### Prerequisites

- **Python 3.12+** (3.14 recommended)
- **[uv](https://docs.astral.sh/uv/)** for dependency management
- An **Anthropic API key** (set `ANTHROPIC_API_KEY` in `.env` or your environment)

### Installation

```bash
git clone https://github.com/thiesgerken/carapace.git
cd carapace
uv sync
```

### Running

Start the server:

```bash
uv run python -m carapace        # or: uv run carapace-server
```

Connect via the CLI client (in another terminal):

```bash
uv run python -m carapace.cli    # or: uv run carapace
```

Or start the web UI (in another terminal):

```bash
cd frontend
npm install
npm run dev
```

On first server start a bearer token is generated in `data/server.token`. The CLI reads it automatically from the same data directory. The web UI prompts for the server URL and token on first connect. For remote CLI access, pass `--token` or set `CARAPACE_TOKEN`.

### Configuration

1. Copy `.env.example` to `.env` and set your API key.
2. Customise files under `data/` — see [Data directory](#data-directory) above.

## Demo

```
$ carapace-server
INFO:     Carapace server ready — model=anthropic:claude-sonnet-4-5, rules=7, skills=1, token=a1b2c3d4…

$ carapace
New session c72188b27225
Server: http://127.0.0.1:8321 | Type /help for commands

carapace> hi

Hello! I'm Carapace, your personal AI assistant. How can I help you today?

carapace> what can you do

I can help you with a variety of tasks:

File Management
 • Read, write, and edit files
 • Organize and manage documents

Command Execution
 • Run shell commands and scripts
 • Execute code and tools

Information & Research
 • Search the web for information
 • Look up facts and research topics

Memory
 • Remember important information about you and your preferences
 • Maintain context across our conversations

Task Planning
 • Break down complex tasks into steps
 • Help organize and execute multi-step projects

carapace> find out about your environment
  bash(command='ls -la')     [read_local] (shell)
  bash(command='uname -a')   [read_local] (shell)
  bash(command='pwd')        [read_local] (shell)

Here's what I found about the environment:

Location & System
 • Working directory: /home/user/carapace/data
 • OS: macOS (Darwin kernel, ARM64 - Apple Silicon)
 • Shell: zsh

Available Files & Directories
 • AGENTS.md, SOUL.md, USER.md - configuration files
 • config.yaml - system configuration
 • rules.yaml - security/operational rules
 • logs/, memory/, sessions/, skills/

Programming Languages Available
 • Python 3 (in virtual environment)
 • Node.js

carapace> ^D
Goodbye.
```

## Status

Early development — client-server architecture with FastAPI + WebSocket, rule-evaluated tool execution, and interactive CLI.
