# Skill System

Carapace uses the open [AgentSkills](https://agentskills.io/) format for skills. This makes skills portable to any AgentSkills-compatible agent (Claude Code, Cursor, Gemini CLI, etc.) while Carapace adds its own security layer on top.

## Skill structure

A skill is a directory with a `SKILL.md` file (Markdown instructions with YAML frontmatter) plus optional `scripts/`, `references/`, and `assets/` directories.

Carapace extends the format with optional files:

- **`carapace.yaml`** — security metadata: network domain declarations, credential needs
- **`pyproject.toml`** — Python project with dependencies; Carapace automatically creates a venv via `uv sync` on activation

```text
skills/
  web-search/
    SKILL.md             # required: AgentSkills standard
    carapace.yaml        # optional: Carapace extensions
    pyproject.toml       # optional: Python dependencies
    scripts/
      search.py
    references/
      api-docs.md
  expense-tracker/
    SKILL.md
    carapace.yaml
    scripts/
      add_expense.py
      query_expenses.py
```

## SKILL.md (AgentSkills standard)

The skill's instructions follow the AgentSkills format: YAML frontmatter with at minimum `name` and `description`, followed by Markdown instructions.

```markdown
---
name: web-search
description: >
  Search the web using SearXNG. Use when the user asks to look
  something up, find information, or research a topic.
metadata:
  author: user
  version: "1.0"
---

# Web Search

## When to use

Use this skill when the user wants to search the web.

## How to search

Run the search script:
scripts/search.py --query "<search terms>"

Returns JSON with title, URL, and snippet for each result.
Summarize the top results for the user.
```

## carapace.yaml (Carapace extension)

Optional file that declares network domains the skill needs and credentials it uses.

```yaml
network:
  domains:
    - "api.searxng.example.com"
    - "*.search.example.com"

credentials:
  - name: SEARXNG_URL
    vault_path: "carapace/searxng"
    inject_as: env
    env_var: SEARXNG_URL
```

### Fields

**`network.domains`** — list of domains the skill needs to access. These are automatically added to the session's proxy allowlist when the skill is activated. Supports wildcard matching (`*.example.com`).

**`credentials`** — list of credentials the skill needs. Each entry has:

- `name` — identifier for the credential
- `vault_path` — path in the password manager
- `inject_as` — how to inject: `env` (environment variable), `file`, or `stdin`
- `env_var` — environment variable name (when `inject_as: env`)

> **Note**: The credential broker is not yet implemented — credential declarations are parsed but not functional. See [plans/credentials.md](plans/credentials.md).

## pyproject.toml-based dependencies

A skill can include a `pyproject.toml` to declare its Python dependencies. Dependency management uses **uv** exclusively — it is pre-installed in every sandbox container.

### Lifecycle

1. **Activation** (`use_skill`): Carapace copies the skill into the sandbox at `/workspace/skills/<name>/`. If a `pyproject.toml` is present, it runs `uv sync --directory /workspace/skills/<name>` to create a `.venv` with all declared dependencies. The proxy is temporarily bypassed during install.
2. **Runtime**: Scripts should be invoked with `uv run --directory /workspace/skills/<name> scripts/<script>.py` so they run inside the venv.
3. **Persistence**: Skills are persisted via Git — changes in `/workspace/skills/` are committed and pushed to the workspace repository.
4. **Container restart**: Venvs are rebuilt for all activated skills automatically when a container is recreated after idle timeout.

### Managing dependencies

Inside the sandbox, use standard `uv` commands:

```bash
# Add a dependency (updates pyproject.toml + uv.lock)
uv add --directory /workspace/skills/my-skill httpx

# Remove a dependency
uv remove --directory /workspace/skills/my-skill httpx

# Install from existing lock file
uv sync --directory /workspace/skills/my-skill
```

Always commit a `uv.lock` alongside `pyproject.toml` to ensure reproducible installs.

## Discovery (progressive disclosure)

At startup, Carapace loads only `name` and `description` from each skill's frontmatter (~100 tokens per skill). These are injected into the agent's system prompt as a skill catalog. The agent sees what's available without the full instructions consuming context.

The full `SKILL.md` body is loaded only when the agent decides a skill is relevant — via the `use_skill` tool.

## Skill activation as a security event

When the agent activates a skill (loads its full `SKILL.md` into context), a `SkillActivatedEntry` is recorded in the action log. The `use_skill` tool itself is safe-listed (auto-allowed without sentinel evaluation), but the activation is logged so the sentinel has context for evaluating subsequent actions.

For example, after the agent reads skill instructions describing email credentials, the sentinel will be more cautious about outbound network requests — it knows the agent now has knowledge that could be exfiltrated.

The sentinel can also read skill files directly (via its `list_skill_files` and `read_skill_file` tools) to understand what a skill-related tool call will actually do.

## Self-improvement

The agent can create new skills by writing files to `/workspace/skills/` in the sandbox (SKILL.md, scripts, optional pyproject.toml, optional carapace.yaml) and then committing and pushing them via Git.

The workflow for the agent to create a skill via chat:

1. User asks for a new skill (or the agent proposes one)
2. Agent plans the skill (SKILL.md, scripts, optional pyproject.toml, optional carapace.yaml)
3. Agent writes the files in the sandbox at `/workspace/skills/<skill-name>/`
4. Agent tests the skill in the sandbox
5. Agent commits and pushes via Git — the sentinel evaluates the push via the pre-receive hook
6. On approval, the skill is persisted in the workspace repository and becomes available in future sessions

A built-in `create-skill` skill is seeded on first run to guide the agent through this process.
