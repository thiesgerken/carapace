# Skill System

Carapace uses the open [AgentSkills](https://agentskills.io/) format for skills. This makes skills portable to any AgentSkills-compatible agent (Claude Code, Cursor, Gemini CLI, etc.) while Carapace adds its own security layer on top.

## Skill structure

A skill is a directory with a `SKILL.md` file (Markdown instructions with YAML frontmatter) plus optional `scripts/`, `references/`, and `assets/` directories.

Carapace extends the format with optional files:

- **`carapace.yaml`** -- security metadata: credential declarations, classification hints, sandbox config
- **`pyproject.toml`** -- Python project with dependencies; Carapace automatically creates a venv via `uv sync` on activation

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

Optional file that declares credentials the skill needs, hints for the Classifier, and sandbox requirements.

```yaml
credentials:
  - name: SEARXNG_URL
    vault_path: "carapace/searxng"
    inject_as: env
    env_var: SEARXNG_URL

hints:
  likely_classification: read_external

sandbox:
  network: true
```

### Fields

**`credentials`** -- list of credentials the skill needs. Each entry has:

- `name` -- identifier for the credential
- `vault_path` -- path in the password manager
- `inject_as` -- how to inject: `env` (environment variable), `file`, or `stdin`
- `env_var` -- environment variable name (when `inject_as: env`)

Credentials are fetched on demand via the Credential Broker with per-session user approval. See [credentials.md](credentials.md).

**`hints`** -- optional hints for the Operation Classifier to speed up classification. Not security-critical (the Classifier can override them).

**`sandbox`** -- per-skill sandbox configuration:

- `network` -- whether the skill container gets network access (default: `false`)

## pyproject.toml-based dependencies

A skill can include a `pyproject.toml` to declare its Python dependencies. Dependency management uses **uv** exclusively — it is pre-installed in every sandbox container.

### Lifecycle

1. **Activation** (`use_skill`): Carapace copies the skill into the sandbox. If a `pyproject.toml` is present, it runs `uv sync --directory /workspace/skills/<name>` to create a `.venv` with all declared dependencies. The proxy is temporarily bypassed during install.
2. **Runtime**: Scripts should be invoked with `uv run --directory /workspace/skills/<name> scripts/<script>.py` so they run inside the venv.
3. **Save** (`save_skill`): Copies the skill back to the master directory (excluding `.venv` and `__pycache__`). If there is a `pyproject.toml`, the master venv is rebuilt.
4. **Container restart**: Venvs are rebuilt for all activated skills automatically.

### Managing dependencies

Inside the sandbox, use standard `uv` commands:

```bash
# Add a dependency (updates pyproject.toml + uv.lock)
uv add --directory /workspace/skills/my-skill httpx

# Remove a dependency
uv remove --directory /workspace/skills/my-skill httpx

# Generate/update the lock file without adding packages
uv lock --directory /workspace/skills/my-skill

# Install from existing lock file
uv sync --directory /workspace/skills/my-skill
```

Always commit a `uv.lock` alongside `pyproject.toml` to ensure reproducible installs.

## Discovery (progressive disclosure)

At startup, Carapace loads only `name` and `description` from each skill's frontmatter (~100 tokens per skill). These are injected into the agent's system prompt as a skill catalog. The agent sees what's available without the full instructions consuming context.

The full `SKILL.md` body is loaded only when the agent decides a skill is relevant -- and that activation is itself recorded in the security action log.

## Skill activation as a security event

When the agent activates a skill (loads its full `SKILL.md` into context), a `SkillActivatedEntry` is recorded in the action log. This gives the sentinel agent context about what the agent has learned -- skill instructions reveal the user's personal infrastructure (services, credential paths, workflow patterns).

The sentinel uses this context when evaluating subsequent actions. For example, after the agent reads skill instructions describing email credentials, the sentinel will be more cautious about outbound network requests -- it knows the agent now has knowledge that could be exfiltrated.

The sentinel can also read skill files directly (via its `list_skill_files` and `read_skill_file` tools) to understand what a skill-related tool call will actually do.

## Self-improvement

The agent can create new skills by writing files to the `skills/` directory (SKILL.md, carapace.yaml, scripts, pyproject.toml). The sentinel will escalate this for user approval per the `SECURITY.md` policy. The user sees the proposed files in their channel and approves or denies.

There is no special "architect mode". Skill creation, editing, and deletion are governed by the same sentinel-based security system as everything else.

The workflow for the agent to create a skill via chat:

1. User asks for a new skill (or the agent proposes one)
2. Agent plans the skill (SKILL.md, scripts, optional pyproject.toml, optional carapace.yaml)
3. Agent proposes writes to `/tmp/shared/pending/skills/<skill-name>/`
4. `skill-modification` rule fires -- user sees the proposed files
5. On approval, Carapace orchestrator copies the files to `skills/`
6. Agent can test the skill in the same session
