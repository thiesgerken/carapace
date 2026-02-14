# TODO: PoC to Production

## Security Pipeline

- [ ] Plan-based approval: agent proposes a plan, `request_approval` tool pre-evaluates all rules, sends one consolidated prompt instead of per-tool approval
- [ ] Classifier result caching per `(rule_id, operation_signature)` within a session to avoid redundant LLM calls
- [ ] Rule evaluation caching (same -- avoid re-evaluating the same rule+operation pair)
- [ ] Support `block` mode rules (currently only `approve` is exercised)
- [ ] Partial plan approval (`/approve 1-3 only`)

## Sandbox / Docker

- [ ] Docker-first execution: move all tool execution into containers (currently runs in-process)
- [ ] Base container: read-only Alpine+Python, no network, pre-warmed at session start
- [ ] Skill containers: build from skill `Dockerfile`, cache images, inject credentials as env vars
- [ ] Shared mount setup: `/skills` (ro), `/memory` (ro), `/workspace` (ro), `/tmp/shared` (rw per session)
- [ ] Proposed writes via `/tmp/shared/pending/` -- orchestrator applies after approval
- [ ] Container lifecycle: idle timeout, destroy on expire, pre-warm on next message
- [ ] Network policy enforcement per container (no network for base, per-skill for skill containers)
- [ ] Shell commands via `docker exec` into base container

## Channels

- [ ] Abstract channel interface (`Channel` ABC with `start`, `send_message`, `send_approval_request`, `wait_for_approval`)
- [ ] Matrix channel: matrix-nio with E2EE, reactions for approvals, threads for long output
- [ ] Decouple REPL logic from CLI -- the CLI becomes just another channel adapter
- [ ] Cron channel: scheduled jobs, approval routing to Matrix
- [ ] Webhook channel: inbound HTTP/email triggers
- [ ] Cross-channel approval routing (tagged system messages to avoid session interference)
- [ ] Web UI channel (future)

## Credentials

- [ ] Real credential broker: fetch from Vaultwarden/Bitwarden via CLI or API (just this one backend for now, but make it possible to add more in the future)
- [ ] Credential injection into skill containers (env var, file, or stdin)
- [ ] Per-session in-memory caching (never persist to disk)

## Skills

- [ ] `carapace.yaml` parsing: credential declarations, classification hints, sandbox config
- [ ] Dockerfile-based skill execution: build, cache, mount, run
- [ ] Default sandbox image for skills without a Dockerfile
- [ ] Skill self-improvement flow: agent writes to `/tmp/shared/pending/skills/`, user sees diff, orchestrator applies
- [ ] Skill image rebuild detection (Dockerfile or requirements change)

## Memory

- [ ] Vector search: local embeddings (sentence-transformers), SQLite index in `memory/.index/`
- [ ] Incremental index updates on memory file changes
- [ ] Smarter context loading: only load CORE.md + recent daily logs upfront, rest via search
- [ ] Memory write diffs shown to user in approval prompts

## Session Management

- [ ] History retention cleanup (delete sessions older than `history_retention_days`)
- [ ] Session history summarization for long conversations (context window management)
- [ ] History processor integration (Pydantic AI's `history_processors` for token budgeting)

## Workspace Files

- [ ] `HEARTBEAT.md` support: cron reads this for periodic task checklists
- [ ] Gated writes to workspace files (SOUL.md, USER.md, etc.) through the same pending-write mechanism
- [ ] `TOOLS.md` read as a potential security-sensitive operation (optional rule)

## Observability

- [ ] Pydantic Logfire integration: trace agent runs, tool calls, classifier invocations, rule evaluations
- [ ] Container lifecycle tracing
- [ ] Structured logging to `$CARAPACE_DATA_DIR/logs/`

## Deployment

- [ ] Dockerfile for Carapace itself
- [ ] Docker Compose with socket mount, env vars, data volume
- [ ] Base container image definition (Alpine + Python + common tools)
- [ ] Health check / readiness probe

## Sessions / Multi-Agent

- [ ] `sessions_spawn`: agent can spawn a sub-agent run in an isolated session and receive the result back
- [ ] `sessions_list` / `sessions_history` / `sessions_send`: inspect and interact with other sessions
- [ ] Sub-agent tool policy (restrict which tools sub-agents can use)

## Misc

- [ ] Error handling refinement: agent-decided retries per AGENTS.md guidance
- [ ] Streaming output in CLI (currently waits for full response)
- [ ] Config validation on startup with clear error messages
- [ ] `.gitignore` for data directory secrets / session state
- [ ] Tests: unit tests for classifier, rule engine, session manager, skill registry
