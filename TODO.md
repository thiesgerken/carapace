# TODO: PoC to Production

## Security Pipeline

- [ ] Plan-based approval: agent proposes a plan, `request_approval` tool pre-evaluates all rules, sends one consolidated prompt instead of per-tool approval
- [ ] Classifier result caching per `(rule_id, operation_signature)` within a session to avoid redundant LLM calls
- [ ] Rule evaluation caching (same -- avoid re-evaluating the same rule+operation pair)
- [ ] Support `block` mode rules (currently only `approve` is exercised)
- [ ] Partial plan approval (`/approve 1-3 only`)

## Sandbox / Docker

- [ ] Credential injection into skill containers (env var, file, or stdin)
- [ ] Health check / readiness probe

## Channels

- [ ] Matrix E2EE support (currently plain-text only)
- [ ] Cron channel: scheduled jobs, approval routing to Matrix
- [ ] Webhook channel: inbound HTTP/email triggers
- [ ] Cross-channel approval routing (tagged system messages to avoid session interference)

## Credentials

- [ ] Real credential broker: fetch from Vaultwarden/Bitwarden via CLI or API (just this one backend for now, but make it possible to add more in the future)
- [ ] Per-session in-memory caching (never persist to disk)

## Skills

- [ ] Skill self-improvement flow: agent writes to `/tmp/shared/pending/skills/`, user sees diff, orchestrator applies
- [ ] Skill image rebuild detection (Dockerfile or requirements change)

## Memory

- [ ] Vector search: local embeddings (sentence-transformers), SQLite index in `memory/.index/`
- [ ] Incremental index updates on memory file changes
- [ ] Smarter context loading: only load CORE.md + recent daily logs upfront, rest via search
- [ ] Memory write diffs shown to user in approval prompts

## Session Management

- [ ] Session history summarization for long conversations (context window management)
- [ ] History processor integration (Pydantic AI's `history_processors` for token budgeting)

## Workspace Files

- [ ] `HEARTBEAT.md` support: cron reads this for periodic task checklists
- [ ] Gated writes to workspace files (SOUL.md, USER.md, etc.) through the same pending-write mechanism
- [ ] `TOOLS.md` read as a potential security-sensitive operation (optional rule)

## Observability

- [ ] Container lifecycle tracing
- [ ] Structured logging to `$CARAPACE_DATA_DIR/logs/`

## Sessions / Multi-Agent

- [ ] `sessions_spawn`: agent can spawn a sub-agent run in an isolated session and receive the result back
- [ ] `sessions_list` / `sessions_history` / `sessions_send`: inspect and interact with other sessions
- [ ] Sub-agent tool policy (restrict which tools sub-agents can use)

## Misc

- [ ] Streaming output in CLI (currently waits for full response)
