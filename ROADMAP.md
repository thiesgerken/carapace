# Roadmap

> This roadmap outlines planned features and improvements. Items are grouped by area and roughly ordered by priority within each section.

- [ ] Proper Icon + Logo, rewrite README to be more ... advertising
- [ ] Compaction
- [ ] image input ([plan](docs/plans/images.md))
- [ ] image output — agent tools producing images (screenshots, charts, renders)
- [ ] custom sentinel instructions for skills, e.g. moneydb: make sure that the agent only does mutations based on user approval
- [ ] conversation history: fork session
- [ ] "daily" session that is recreated every day and that should persist some of its memories during the night
- [ ] forbid session to use some skills (include/exclude) — useful for cronjobs
- [ ] harden sandbox so trusted exec allowlists are meaningful (run as non-root, read-only root fs where possible, avoid command alias / path tampering) — important prerequisite for auto-approving read-only commands like `rg`, `ls`, `cat`

## Knowledge Repo Handling

- [ ] indicator how many commits ahead/behind the session's knowledge repo is + the ability to pull/push inside the sandbox without telling the agent
- [ ] warn user if deleting a session that has commits not pushed
- [ ] replace pull / push slash commands (that aren't really tied to the session anyway) with a global indicator how many commits ahead/behind the backend's global repo is compared to the remote repo

## Authentication & Multi-User

- [ ] **OIDC / OAuth 2.0** — replace the static bearer token with a proper OIDC provider (Keycloak, Authentik, Authelia, etc.) for login on both the web UI and CLI
- [ ] **Multi-user support** — per-user sessions, memory, and security context; map OIDC subject to a carapace user identity
- [ ] **Session token lifecycle** — short-lived access tokens with refresh, proper logout / revocation
- [ ] **Per-user data isolation** — each user gets their own memory, session history, and workspace files

## Memory

- [ ] **Structured memory layout** — organized directories (`CORE.md`, `daily/`, `topics/`) with predictable conventions
- [ ] **Vector search** — local sentence-transformers embeddings with a SQLite index in `memory/.index/`
- [ ] **Incremental index updates** — rebuild index automatically on memory file changes
- [ ] **Smarter context loading** — load only `CORE.md` + recent daily logs at startup; older content available via search

## Channels & Scheduling

- [ ] **Cron channel** — scheduled jobs defined in `HEARTBEAT.md` or `config.yaml`, creating non-interactive sessions on a schedule
- [ ] **Cross-channel approval routing** — non-interactive sessions route approval requests to an interactive channel (e.g. Matrix DM) via tagged system messages
- [ ] **Matrix E2EE** — end-to-end encryption support via matrix-nio
- [ ] **Webhook channel** — inbound HTTP/email triggers

## Sessions & Multi-Agent

- [ ] **Session history summarization** — compress long conversations to manage context window limits
- [ ] **History processor integration** — use Pydantic AI's `history_processors` for token budgeting
- [ ] **Sub-agent sessions** — `sessions_spawn` to run isolated sub-agent sessions and receive results back
- [ ] **Cross-session interaction** — `sessions_list`, `sessions_history`, `sessions_send` for inspecting and messaging other sessions
- [ ] **Sub-agent tool policy** — restrict which tools sub-agents can use

## Workspace Files

- [ ] **`HEARTBEAT.md` support** — cron reads this for periodic task definitions
- [ ] **`TOOLS.md` read gating** — optionally treat reading tool definitions as a security-sensitive operation
