# Memory and Workspace Files

Carapace has two kinds of persistent agent context: **memory** (facts, notes, and topics that grow over time) and **workspace files** (identity, behavioral guide, user context).

---

## Memory system

Memory is persistent context that survives across sessions. It's a Markdown-based file store under the knowledge directory's `memory/` sub-folder (Git-tracked).

### Operations

| Tool | Description |
| --- | --- |
| `read_memory` | Read a specific file by path, or search all memory files by query |

**Read**: The agent can always read memory files. Memory is available inside the sandbox at `/workspace/memory/` (part of the Git-cloned knowledge repo), and the agent also has the `read_memory` tool which reads directly from the host.

**Write**: The agent edits memory files inside the sandbox and persists changes via `git commit` + `git push`. Every push is evaluated by the security sentinel through a pre-receive hook, which gates persistent writes per the `SECURITY.md` policy.

**Search**: Case-insensitive text search over all `.md` files in the memory directory. Returns matching lines grouped by file.

### Bootstrapped files

On first run, `memory/CORE.md` is seeded from the built-in template. The agent and user can build up memory over time by writing additional files.

### Agent behavior

The agent is instructed (via `AGENTS.md`) to proactively suggest memory writes when it learns durable facts about the user, their preferences, or their projects. The user decides what persists through the security approval flow (the sentinel evaluates each `git push`).

---

## Workspace files

These are top-level Markdown files in the knowledge directory that define the agent's identity, knowledge of the user, and behavioral guidelines. They are part of the Git-tracked knowledge repo and cloned into each session's sandbox at `/workspace/`. Changes are loaded into the agent's system prompt at session start.

| File | Purpose | Agent-writable? |
| --- | --- | --- |
| `AGENTS.md` | Master behavioral guide: what to do, safety rules, memory management. The agent's "operating manual." | Yes (via `git push`, sentinel-gated) |
| `SOUL.md` | Agent personality, tone, boundaries. "Who you are." | Yes (via `git push`, sentinel-gated) |
| `USER.md` | About the human: name, timezone, preferences, projects. Built up over time. | Yes (via `git push`, sentinel-gated) |
| `SECURITY.md` | Natural-language security policy for the sentinel agent. | Yes (via `git push`, sentinel-gated) |

### How workspace file editing works

1. On container creation, the knowledge repo is **Git-cloned** into the session's `/workspace/` directory
2. The agent can freely edit these working copies inside the sandbox (via `read`, `write`, `edit`)
3. To make changes permanent, the agent uses `git add`, `git commit`, and `git push` inside the sandbox
4. Every push is **evaluated by the sentinel** via a pre-receive hook — changes that violate the security policy are denied or escalated for user approval

### System prompt loading

When an agent turn starts, `build_system_prompt()` loads the following into the system prompt (in order):

1. `AGENTS.md` — behavioral guide
2. `SOUL.md` — personality
3. `USER.md` — context about the human
4. Skill catalog — names and descriptions only
5. Sandbox environment info — explains container paths and available tools
6. Session ID
