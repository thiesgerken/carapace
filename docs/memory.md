# Memory and Workspace Files

Carapace has two kinds of persistent agent context: **memory** (facts, logs, topics that grow over time) and **workspace files** (identity, behavioral guide, user context).

---

## Memory system

Memory is persistent context that survives across sessions. It's Markdown-based with rule-gated writes and vector search.

### Layout

```
memory/
  CORE.md              # long-term facts, preferences, identity
  daily/
    2026-02-14.md      # daily log
    2026-02-13.md
  topics/
    projects.md        # organized by topic
    contacts.md
    preferences.md
  .index/              # vector search index (SQLite)
```

### Operations

**Read**: The agent can always read memory. At session startup, `CORE.md` and today/yesterday daily logs are loaded into context. Everything else is available via semantic search.

**Write**: Governed by the `memory-write` rule (always-on, `mode: approve`). The agent proposes a write, the user sees exactly what will be added or changed, and approves or denies. Writes are staged to `/tmp/shared/pending/memory/` and applied by the orchestrator after approval. See [sandbox.md](sandbox.md) for the write mechanism.

**Search**: Vector search over all memory files using local embeddings (sentence-transformers, `all-MiniLM-L6-v2` by default). Embeddings are stored in `memory/.index/` (a small SQLite database). The search index is updated when memory files change.

### Agent behavior

The agent is instructed (via `AGENTS.md`) to proactively suggest memory writes when it learns durable facts about the user, their preferences, or their projects. The user decides what sticks. The agent should keep memory entries concise and well-organized.

### Context budget

Memory is the main area where context management matters. The approach is:

- `CORE.md` and recent daily logs are always loaded (user is responsible for keeping these concise)
- Topic files and older daily logs are loaded on demand via vector search
- The agent can reference specific memory files by path when it knows what it's looking for

---

## Workspace files

Inspired by OpenClaw's workspace templates, these are top-level Markdown files that define the agent's identity, knowledge of the user, and behavioral guidelines. They are mounted into every container (read-only) and loaded into context at session start.

| File           | Purpose                                                                                                                                  | Agent-writable?                    |
| -------------- | ---------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------- |
| `AGENTS.md`    | Master behavioral guide: what to do every session, safety rules, memory management, group chat behavior. The agent's "operating manual." | Yes (gated by `memory-write` rule) |
| `SOUL.md`      | Agent personality, tone, boundaries. "Who you are." The agent can evolve this over time.                                                 | Yes (gated)                        |
| `USER.md`      | About the human: name, timezone, preferences, projects. Built up over time.                                                              | Yes (gated)                        |
| `TOOLS.md`     | Local environment notes: SSH hosts, device names, API endpoints. Separate from skills so skills stay portable.                           | Yes (gated)                        |
| `HEARTBEAT.md` | Checklist for cron/periodic sessions. The agent can edit to schedule its own periodic checks.                                            | Yes (gated)                        |

All workspace files live at the root of `$CARAPACE_DATA_DIR/`. They are distinct from the system prompt that Carapace injects -- workspace files are for the agent's evolving self-knowledge.

Writes to workspace files go through the same gated mechanism as memory writes: staged to `/tmp/shared/pending/`, rule-checked, user-approved, applied by the orchestrator.

### Session startup sequence

When a session starts or resumes, the following context is loaded (in order):

1. `AGENTS.md` -- behavioral guide
2. `SOUL.md` -- personality
3. `USER.md` -- context about the human
4. `memory/daily/YYYY-MM-DD.md` -- today + yesterday
5. `memory/CORE.md` -- long-term memory (for DM/main sessions)
6. Skill catalog -- names and descriptions only

All of these are reads from the agent's own workspace (not external/untrusted), so they don't activate flow rules like `no-write-after-web`. However, `TOOLS.md` contains infrastructure details, so a rule could optionally gate outbound communication after reading it (similar to skill activation).
