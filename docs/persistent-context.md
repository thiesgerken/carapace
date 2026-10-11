# Persistent Context and Workspace Files

Persistent context is ordinary content in the Git-backed knowledge repo: top-level workspace files, skills, archived session snapshots, and the generated `memory/` mirror.

---

## Workspace files

Top-level Markdown files in the knowledge repo define the agent's identity, user context, and policy. They are cloned into each session sandbox at `/workspace/` and loaded into the agent's system prompt at session start.

| File          | Purpose                                                                            | Agent-writable?                      |
| ------------- | ---------------------------------------------------------------------------------- | ------------------------------------ |
| `AGENTS.md`   | Master behavioral guide: what to do, safety rules, and coding/project conventions. | Yes (via `git push`, sentinel-gated) |
| `SOUL.md`     | Agent personality, tone, and boundaries.                                           | Yes (via `git push`, sentinel-gated) |
| `USER.md`     | User context and durable preferences.                                              | Yes (via `git push`, sentinel-gated) |
| `SECURITY.md` | Natural-language security policy for the sentinel agent.                           | Yes (via `git push`, sentinel-gated) |

## Archived sessions

When session commit/autosave is enabled, conversation snapshots are written into the knowledge repo under `sessions/YYYY/MM/<session_id>/conversation.json`. These archives are plain files, so the agent can search them with tools such as `rg` when it needs prior context.

Session runtime state still lives under `$CARAPACE_DATA_DIR/sessions/`; archived session files are the Git-backed copy intended for long-term recall and review.

## Memory mirror

[Long-term memory](memory.md) distills archived sessions into per-session extractions and weekly and monthly digests. Its source of truth is carapace's database; a one-way mirror renders the current records into the knowledge repo so the agent can read and search them like any other file:

```
memory/README.md
memory/sessions/YYYY/MM/<session_id>.md
memory/weeks/YYYY-Www.md
memory/months/YYYY-MM.md
```

The mirror owns `memory/`: each run rewrites it from the database in one commit and deletes files of removed records, so edits pushed there are reverted. Change memory in the Memory area of the web UI instead.

## How editing works

1. On container creation, the knowledge repo is Git-cloned into the session's `/workspace/` directory.
2. The agent can edit working-copy files inside the sandbox with `read`, `write`, `str_replace`, and `exec`.
3. To make changes permanent, the agent uses `git add`, `git commit`, and `git push` inside the sandbox.
4. Every push is evaluated by the sentinel via a pre-receive hook. Changes that violate the security policy are denied or escalated for user approval.

## System prompt loading

Every role that acts as the user's agent starts its system prompt with the same **shared prefix** (`prompt_prefix.shared_prompt_prefix()`):

1. `AGENTS.md`: behavioral guide
2. `SOUL.md`: personality
3. `USER.md`: context about the human
4. Skill catalog: names and descriptions only

The roles are agent turns, compaction summaries, session extraction, and week and month digests. Each role puts its own instructions after the prefix:

- **Agent turns** (`build_system_prompt()`): sandbox environment, response format, then the session's mode (unattended, ask), and last the date and session ID.
- **Compaction**: the fold or tool-output summary instructions.
- **Memory tasks**: the extraction or digest instructions. Dates and periods travel in the user prompt.

The sentinel and the titler stay out on purpose. The sentinel must judge the agent independently, and `SOUL.md`/`USER.md` are agent-writable. A title isn't worth the prefix tokens.

### Prefix caching

Providers cache prompts by prefix, so the order is stable first, volatile last. Nothing per session or per call (the current date, the session ID, a role split) may come before the long shared text. Each role's own prefix is what gets cached between its calls. Two roles share a cache entry only when they run on the same model, and some providers cache tool definitions ahead of the system prompt, so the agent (with tools) and the tool-less roles may still miss each other. carapace builds nothing provider-specific for caching.
