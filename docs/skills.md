# Skill System

Carapace uses the open [AgentSkills](https://agentskills.io/) format for skills. This makes skills portable to any AgentSkills-compatible agent (Claude Code, Cursor, Gemini CLI, etc.) while Carapace adds its own security layer on top.

## Skill structure

A skill is a directory with a `SKILL.md` file (Markdown instructions with YAML frontmatter) plus optional `scripts/`, `references/`, and `assets/` directories.

Carapace extends the format with two optional files:

- **`carapace.yaml`** -- security metadata: credential declarations, classification hints, sandbox config
- **`Dockerfile`** -- custom runtime environment for script execution

```
skills/
  web-search/
    SKILL.md             # required: AgentSkills standard
    carapace.yaml        # optional: Carapace extensions
    Dockerfile           # optional: custom runtime
    scripts/
      search.py
    references/
      api-docs.md
  expense-tracker/
    SKILL.md
    carapace.yaml
    Dockerfile
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

## Dockerfile-based execution

If a skill contains a `Dockerfile`, Carapace builds and caches an image for that skill. All script execution for that skill happens inside a container from that image. The skill author fully controls their dependencies.

```dockerfile
FROM python:3.12-slim
WORKDIR /skill
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# No COPY for scripts/ -- they are mounted at runtime
# along with /skills, /memory, and /tmp/shared
```

Key points:

- The `Dockerfile` should install dependencies, not copy scripts. Scripts are mounted at runtime.
- The image is built once and cached. Carapace rebuilds when the Dockerfile or requirements change.
- Shared volumes (`/skills`, `/memory`, `/workspace`, `/tmp/shared`) are mounted into every skill container. See [sandbox.md](sandbox.md) for mount details.

If no `Dockerfile` is present, scripts run in Carapace's default sandbox container (a generic image with Python and common tools).

## Discovery (progressive disclosure)

At startup, Carapace loads only `name` and `description` from each skill's frontmatter (~100 tokens per skill). These are injected into the agent's system prompt as a skill catalog. The agent sees what's available without the full instructions consuming context.

The full `SKILL.md` body is loaded only when the agent decides a skill is relevant -- and that activation is itself a classified, rule-checked operation.

## Skill activation as a security event

When the agent activates a skill (loads its full `SKILL.md` into context), this goes through the Operation Classifier and Rule Engine like any other operation. Skill instructions reveal the user's personal infrastructure -- which services they use, credential paths, workflow patterns.

Rules can gate what happens after skill activation:

```yaml
- id: no-exfil-after-skill-read
  trigger: "the agent has read skill instructions (activated a skill)"
  effect: "block outbound communication (email, API calls) without approval"
  mode: approve
```

This prevents a prompt injection attack from using the agent to read skill instructions (to learn about the user's setup) and then exfiltrate that information.

## Self-improvement

The agent can create new skills by writing files to the `skills/` directory (SKILL.md, carapace.yaml, scripts, Dockerfile). This triggers the `skill-modification` rule (always-on, `mode: approve`). The user sees a diff in their channel and approves or denies.

There is no special "architect mode". Skill creation, editing, and deletion are governed by the same rule system as everything else. If the user wants a development session with fewer interruptions, they can `/disable skill-modification` and `/disable shell-write` temporarily, then `/reset` the session when done.

The workflow for the agent to create a skill via chat:

1. User asks for a new skill (or the agent proposes one)
2. Agent plans the skill (SKILL.md, scripts, optional Dockerfile, optional carapace.yaml)
3. Agent proposes writes to `/tmp/shared/pending/skills/<skill-name>/`
4. `skill-modification` rule fires -- user sees the proposed files
5. On approval, Carapace orchestrator copies the files to `skills/`
6. Agent can test the skill in the same session
