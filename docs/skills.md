# Skill System

Carapace uses the open [AgentSkills](https://agentskills.io/) format for skills. This makes skills portable to any AgentSkills-compatible agent (Claude Code, Cursor, Gemini CLI, etc.) while Carapace adds its own security layer on top.

## Skill structure

A skill is a directory with a `SKILL.md` file (Markdown instructions with YAML frontmatter) plus optional `scripts/`, `references/`, and `assets/` directories.

Carapace extends the format with optional files:

- **`carapace.yaml`** — security metadata: network domain declarations, credential needs
- **`pyproject.toml`** + **`uv.lock`** — Python dependencies installed via `uv sync --locked`
- **`package.json`** + **`package-lock.json`** or **`pnpm-lock.yaml`** — Node dependencies installed with the matching package manager
- **`setup.sh`** — optional post-activation setup script for local config generation or other derived artifacts

```text
skills/
  web-search/
    SKILL.md             # required: AgentSkills standard
    carapace.yaml        # optional: Carapace extensions
    pyproject.toml       # optional: Python dependencies
    uv.lock              # optional: required alongside pyproject.toml
    scripts/
      search.py
  node-tool/
    SKILL.md
    package.json
    package-lock.json
    setup.sh
    scripts/
      run.mjs
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
  - vault_path: "dev/searxng-url"
    description: Base URL for the SearXNG instance
    env_var: SEARXNG_URL
  - vault_path: "dev/searxng-cert"
    description: Optional client certificate
    file: "~/.config/searxng/client.pem"
```

### Fields

**`network.domains`** — list of domains the skill needs to access. These are registered as a **context grant** when the skill is activated. The domains are only allowed during commands that explicitly request the skill's context (see [Context-scoped access](#context-scoped-access) below). Supports wildcard matching (`*.example.com`).

**`credentials`** — list of credentials the skill needs. Each entry has:

- `vault_path` — path in the password manager
- `description` — human-readable explanation shown in approval prompts
- `env_var` — environment variable name for per-exec injection (optional)
- `file` — file path for per-exec injection with mode `0400` (optional)
- `base64` — if `true`, the stored value is base64-decoded before injection (optional, default `false`). Useful for multi-line secrets (e.g. kubeconfig) that cannot be stored verbatim in a single-line password field.

> **Note**: Credential declarations are implemented. See [credentials.md](credentials.md) for approval flow, backend config, and `ccred` usage.

## Context-scoped access

Skill-declared domains and credentials are **not globally available** in the session. Instead, they're scoped to individual `exec` calls via the `contexts` parameter.

### How it works

1. **Activation** creates a context grant: `use_skill("moneydb")` registers the skill's declared domains and credential vault paths as a grant keyed by `"moneydb"`.
2. **Exec requests contexts**: The agent passes `contexts=["moneydb"]` when running commands that need the skill's resources.
3. **Per-exec injection**: Domains are temporarily allowed in the proxy. Credential values are injected as env vars or written as files for the duration of that single exec. File-based credentials are deleted immediately after the command completes.
4. **No context = no access**: An exec without `contexts` (or with unrelated contexts) does not get the skill's domains or credentials. The sentinel evaluates any credential access without a matching context.

### Matching semantics

- **Subset matching**: `contexts=["moneydb", "example"]` matches grants for both `"moneydb"` and `"example"` (union of both grants' resources).
- **Validation**: Every context string must correspond to an activated skill. Unknown context names are rejected.
- **Piping**: When piping output between skill scripts, pass all relevant contexts: `contexts=["moneydb", "web-search"]`.

## Automatic setup providers

When `use_skill` activates a skill, Carapace checks a fixed provider chain and runs every matching provider in order:

1. `pyproject.toml` + `uv.lock` → `uv sync --locked`
2. `package.json` + `package-lock.json` (without `pnpm-lock.yaml`) → `npm ci`
3. `package.json` + `pnpm-lock.yaml` → `pnpm install --frozen-lockfile`
4. `setup.sh` → `sh ./setup.sh`

The provider files above are security-sensitive. Carapace restores them from the skill's **pushed upstream revision** before running them, so local uncommitted or merely local committed sandbox edits are not executed automatically.

All automatic setup providers run with the proxy temporarily bypassed. This includes `setup.sh` by design: it is a committed, human-authored setup hook restored from upstream, and is treated as more intentional and reviewable than arbitrary lifecycle scripts inside third-party package installs.

### Credential ordering

Skill-declared credentials are approved and cached before any automatic setup provider runs. This is important for `setup.sh`, whose main use case is often to transform injected secrets into the local config files a tool actually expects.

Examples:

- Write an API token from an env var into `~/.config/<tool>/config.toml`
- Decode a base64 kubeconfig into a file under the skill directory
- Generate a `.npmrc` or other tool config from approved credentials

Providers must never print raw secret values. Treat them as internal setup steps only.

## Python dependencies

A skill can include a `pyproject.toml` plus `uv.lock` to declare its Python dependencies. Dependency management uses **uv** exclusively — it is pre-installed in every sandbox container.

### Lifecycle

1. **Activation** (`use_skill`): Carapace copies the skill into the sandbox at `/workspace/skills/<name>/`. If `pyproject.toml` and `uv.lock` are present, it runs `uv sync --locked` in that directory. The proxy is temporarily bypassed during install.
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

## Node dependencies

Skills can also use Node-based tooling. The sandbox image includes `npm` and `pnpm` for skill activation.

### Supported lockfile workflows

- `package.json` + `package-lock.json` → `npm ci`
- `package.json` + `pnpm-lock.yaml` → `pnpm install --frozen-lockfile`

If both `package-lock.json` and `pnpm-lock.yaml` are present, Carapace treats the skill as pnpm-based and skips `npm ci`.

As with Python skills, commit the lockfile alongside the manifest so activation is reproducible.

## setup.sh

If `setup.sh` exists, Carapace runs it after the dependency providers above.

Use it for local, deterministic post-processing such as:

- Materializing approved credentials into config files consumed by a CLI or SDK
- Generating derived files that depend on injected secrets
- Finalizing a tool-specific workspace layout after dependency installation

Keep `setup.sh` idempotent. It runs on first activation and again after sandbox recreation.

Because it runs automatically and may execute with approved credentials available, `setup.sh` should be treated like code, not documentation. Only the pushed upstream copy is executed.

Like the dependency providers above, `setup.sh` runs under the temporary proxy-bypass window. The trust model here is deliberate: `setup.sh` is the explicit, committed setup hook for the skill, so Carapace treats it as more trustworthy than transitive package installation behavior.

## Discovery (progressive disclosure)

At startup, Carapace loads only `name` and `description` from each skill's frontmatter (~100 tokens per skill). These are injected into the agent's system prompt as a skill catalog. The agent sees what's available without the full instructions consuming context.

The full `SKILL.md` body is loaded only when the agent decides a skill is relevant — via the `use_skill` tool.

## Skill activation as a security event

When the agent activates a skill (loads its full `SKILL.md` into context), a `SkillActivatedEntry` is recorded in the action log. The `use_skill` tool call goes through the sentinel (not the safe-list); the activation is logged so the sentinel has context for evaluating subsequent actions.

For example, after the agent reads skill instructions describing email credentials, the sentinel will be more cautious about outbound network requests — it knows the agent now has knowledge that could be exfiltrated.

The sentinel can also read skill files directly (via its `list_skill_files` and `read_skill_file` tools) to understand what a skill-related tool call will actually do.

## Self-improvement

The agent can create new skills by writing files to `/workspace/skills/` in the sandbox (SKILL.md, scripts, optional pyproject.toml, optional carapace.yaml) and then committing and pushing them via Git.

The workflow for the agent to create a skill via chat:

1. User asks for a new skill (or the agent proposes one)
2. Agent plans the skill (SKILL.md, scripts, optional provider files such as pyproject/package.json/setup.sh, optional carapace.yaml)
3. Agent writes the files in the sandbox at `/workspace/skills/<skill-name>/`
4. Agent tests the skill in the sandbox
5. Agent commits and pushes via Git — the sentinel evaluates the push via the pre-receive hook
6. On approval, the skill is persisted in the workspace repository and becomes available in future sessions

A built-in `create-skill` skill is seeded on first run to guide the agent through this process.
