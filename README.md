# Carapace

A security-first personal AI agent with rule-based information flow control.

Carapace is a self-hosted AI agent gateway that connects to Matrix (and future channels) and lets you interact with an AI assistant from anywhere. Unlike other agent frameworks that start with broad access and lock down after the fact, Carapace starts with **zero access** and grants capabilities through **plain-English security rules** evaluated by an LLM.

## Key ideas

- **Rules, not permissions.** Security is defined in plain English ("if the agent read something from the internet, it can't do any write ops without approval"). An LLM evaluates whether each rule applies to the current operation in context.
- **Plan before act.** The agent always proposes a plan before executing multi-step tasks. Rules are pre-evaluated against the plan and the user gets one consolidated approval prompt instead of being asked at every step.
- **Read-only by default.** The agent's base workspace is a read-only Docker container with no network. It can explore files, read skills, search memory freely. All actions (writes, network, API calls) go through skill containers with explicit sandboxing.
- **Skills are portable.** Skills follow the open [AgentSkills](https://agentskills.io/) format (SKILL.md + scripts). They work in Claude Code, Cursor, Gemini CLI too. Carapace extends the format with `carapace.yaml` for credentials and security hints, and optional `Dockerfile` for dependency isolation.
- **The agent improves itself.** Carapace can write new skills, update its memory, and evolve its personality -- all gated by the same rule system. No special "architect mode", just rules the user can temporarily relax.
- **Credentials stay in your vault.** Carapace doesn't store secrets. It fetches credentials from your password manager (Vaultwarden, 1Password, pass) on demand, with per-session approval.

## Architecture overview

```text
Channels (Matrix, cron, webhook, ...)
        |
   Channel Router
        |
   Session Manager ---- Rule Engine (LLM-evaluated)
        |                     |
   Pydantic AI Agent --- Approval Gate
        |                     |
   Skill Registry       Channel (sends approval requests)
        |
  Docker Containers
   ├── Base Container (read-only, no network)
   └── Skill Containers (from Dockerfile, with credentials)
```

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

## Status

Architecture design phase. No code yet.
