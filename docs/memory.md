# Memory and Workspace Files

Carapace has two kinds of persistent agent context: **memory** (facts, notes, and topics that grow over time) and **workspace files** (identity, behavioral guide, user context).

---

## Memory system

Memory is persistent context that survives across sessions. It's a Markdown-based file store under `$CARAPACE_DATA_DIR/memory/`.

### Operations

| Tool | Description |
| --- | --- |
| `read_memory` | Read a specific file by path, or search all memory files by query |
| `write_memory` | Write or update a memory file at a given path |

**Read**: The agent can always read memory files. Memory is mounted read-only into sandbox containers at `/workspace/memory/`, but the agent also has the `read_memory` tool which reads directly from the host.

**Write**: The `write_memory` tool writes directly to the memory directory. This operation goes through the security sentinel, which evaluates it per the `SECURITY.md` policy (persistent memory writes typically require user approval).

**Search**: Case-insensitive text search over all `.md` files in the memory directory. Returns matching lines grouped by file.

### Bootstrapped files

On first run, `memory/CORE.md` is seeded from the built-in template. The agent and user can build up memory over time by writing additional files.

### Agent behavior

The agent is instructed (via `AGENTS.md`) to proactively suggest memory writes when it learns durable facts about the user, their preferences, or their projects. The user decides what persists through the security approval flow.

> **Future plans**: Structured memory layout (daily logs, topic files), vector search with local embeddings, and git-backed memory. See [plans/memory.md](plans/memory.md).

---

## Workspace files

These are top-level Markdown files in `$CARAPACE_DATA_DIR/` that define the agent's identity, knowledge of the user, and behavioral guidelines. They are copied into each session's sandbox as working copies and loaded into the agent's system prompt at session start.

| File | Purpose | Agent-writable? |
| --- | --- | --- |
| `AGENTS.md` | Master behavioral guide: what to do, safety rules, memory management. The agent's "operating manual." | Yes (via `save_workspace_file`, sentinel-gated) |
| `SOUL.md` | Agent personality, tone, boundaries. "Who you are." | Yes (via `save_workspace_file`, sentinel-gated) |
| `USER.md` | About the human: name, timezone, preferences, projects. Built up over time. | Yes (via `save_workspace_file`, sentinel-gated) |
| `SECURITY.md` | Natural-language security policy for the sentinel agent. | Yes (via `save_workspace_file`, sentinel-gated) |

### How workspace file editing works

1. On container creation, workspace files are **copied** from `$CARAPACE_DATA_DIR/` into the session's workspace directory
2. The agent can freely edit these working copies inside the sandbox (via `read`, `write`, `edit`)
3. To make changes permanent, the agent calls `save_workspace_file`, which copies the file back to `$CARAPACE_DATA_DIR/`
4. The `save_workspace_file` tool is **always evaluated by the sentinel** and typically escalated for user approval

### System prompt loading

When an agent turn starts, `build_system_prompt()` loads the following into the system prompt (in order):

1. `AGENTS.md` — behavioral guide
2. `SOUL.md` — personality
3. `USER.md` — context about the human
4. Skill catalog — names and descriptions only
5. Sandbox environment info — explains container paths and available tools
6. Session ID
