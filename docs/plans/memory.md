# Plan: Structured Memory & Vector Search

> Status: planned. The current memory system is a simple markdown file store with grep-based search. See [../memory.md](../memory.md) for what exists today.

## Structured memory layout

Organize memory into a predictable directory structure:

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

### Daily logs

The agent should maintain daily log files (`daily/YYYY-MM-DD.md`) summarizing key interactions and events. At session startup, today's and yesterday's daily logs should be loaded into context automatically.

### Context loading at startup

When a session starts or resumes, the following memory content should be loaded into context:

1. `CORE.md` — long-term memory
2. `daily/YYYY-MM-DD.md` — today + yesterday
3. Topic files and older daily logs available via vector search on demand

## Vector search

Replace the current grep-based search with semantic vector search:

- **Embeddings**: Local sentence-transformers model (`all-MiniLM-L6-v2` or similar)
- **Storage**: SQLite database in `memory/.index/`
- **Update**: Rebuild index when memory files change
- **Usage**: The agent can search memory semantically, not just by keyword

The config model already has a `MemorySearchConfig` with `enabled: bool` — this should control whether vector search is active.

## Git-backed memory

Store the memory directory as a git repository. Agent writes would be committed automatically, providing:

- Full history of all memory changes
- Easy rollback of problematic writes
- Diff visibility for memory evolution over time

This is related to the [git-backed skills plan](kubernetes.md#git-backed-storage).
