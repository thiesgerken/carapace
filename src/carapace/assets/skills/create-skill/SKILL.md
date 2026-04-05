---
name: create-skill
description: Create and edit AgentSkills for Carapace. Use when the user wants to add a new skill, edit an existing one, or asks about the skill format.
---

# Create Skill

Guide for creating and maintaining Carapace skills that follow the open [AgentSkills](https://agentskills.io/) format.

## Skill location

Skills live under `skills/` in the data directory. Each skill is a directory containing at minimum a `SKILL.md` file:

```
skills/
  my-skill/
    SKILL.md          # required
    carapace.yaml     # optional: Carapace — proxy domains + credential declarations
    scripts/           # optional: executable code
    references/        # optional: additional docs
    assets/            # optional: templates, data files
```

## SKILL.md format

### Frontmatter (required)

```yaml
---
name: my-skill
description: What this skill does and when to use it. Be specific -- this is what the agent reads at startup to decide whether to activate the skill.
---
```

**`name` rules:**

- Must match the parent directory name exactly
- Lowercase letters, numbers, and hyphens only
- No consecutive hyphens (`--`), no leading/trailing hyphens
- Max 64 characters

**`description` rules:**

- Include keywords that help identify relevant tasks
- Describe both _what_ the skill does and _when_ to use it
- Max 1024 characters

Optional frontmatter fields:

| Field           | Purpose                                             |
| --------------- | --------------------------------------------------- |
| `license`       | License name or reference to a bundled LICENSE file |
| `compatibility` | Environment requirements (tools, network, etc.)     |
| `metadata`      | Arbitrary key-value pairs (author, version, etc.)   |

### Body (instructions)

The markdown body after the frontmatter is the actual skill content. There are no format restrictions. Write whatever helps perform the task effectively.

Recommended sections:

- When to use / when not to use
- Step-by-step instructions
- Common edge cases
- Input/output examples

## Progressive disclosure

Carapace loads skills in three tiers:

1. **Discovery** (~100 tokens): `name` + `description` loaded at startup for all skills
2. **Activation** (< 5000 tokens recommended): full `SKILL.md` body loaded via `activate_skill`
3. **Resources** (on demand): files in `scripts/`, `references/`, `assets/` loaded only when referenced

Keep `SKILL.md` under 500 lines. Move detailed reference material to separate files and reference them with relative paths:

```markdown
See [the API reference](references/api.md) for endpoint details.
```

## Carapace-specific conventions

### Security rules that apply

- **`skill-modification`** (always active): creating, editing, or deleting any file under `skills/` requires user approval. The user will be prompted automatically.
- **`no-exfil-after-skill-read`**: after activating a skill (reading its instructions), outbound communication is blocked without approval. Keep this in mind -- skills may contain sensitive workflow details.

### carapace.yaml (optional)

Carapace reads `skills/<name>/carapace.yaml` when the agent calls `use_skill("<name>")`. It declares **which hostnames the sandbox proxy may reach** and **which vault credentials to inject** (after user approval). Omit the file if the skill needs neither.

**Top-level keys** (all optional):

| Key               | Type            | Purpose                                                                                               |
| ----------------- | --------------- | ----------------------------------------------------------------------------------------------------- |
| `network`         | object          | Must contain `domains` — not a bare list under `network`.                                             |
| `network.domains` | list of strings | Hostnames added to the session allowlist (wildcards like `*.cdn.example.com` allowed).                |
| `credentials`     | list of objects | Each entry: `vault_path` (required), `description`, and either `env_var` and/or `file` for injection. |
| `hints`           | string map      | Extra metadata for tooling (does not replace `network` / `credentials`).                              |

**Valid example** (shape matters):

```yaml
network:
  domains:
    - api.example.com
    - "*.cdn.example.com"

credentials:
  - vault_path: my-backend/some-secret-id
    description: API key for Example service
    env_var: EXAMPLE_API_KEY
  - vault_path: my-backend/deploy-key
    description: SSH private key for deploys
    file: ~/.ssh/id_example_deploy
```

**Common mistake — invalid YAML for Carapace:**

```yaml
# WRONG: `network` must be an object with a `domains` key, not a YAML list.
network:
  - api.example.com
```

That parses as a list assigned to `network`, Pydantic validation fails, and **the entire `carapace.yaml` is ignored** (no domains, no credentials). Check server logs for a parse/validation warning if nothing applies.

**Rules:**

- Paths are resolved from the skill directory next to `SKILL.md` in the knowledge repo (under `skills/<name>/carapace.yaml`).
- Credential values are never echoed to the user; env vars and files are set inside the sandbox after approval.
- For full detail, see bundled `credentials` skill and project `docs/skills.md`.

### Creating a skill step by step

1. Choose a name: lowercase, hyphenated, descriptive (e.g. `email-summary`, `git-changelog`)
2. Create the directory and `SKILL.md` using the `write` tool:
   - Path: `skills/<name>/SKILL.md`
   - The `skill-modification` rule will trigger approval
3. Write clear frontmatter with a good `description`
4. Write concise instructions in the body
5. Optionally add `carapace.yaml` if the skill needs outbound domains or vault-backed secrets
6. Optionally add `scripts/`, `references/`, or `assets/` directories
7. Tell the user the skill will appear in `/skills` and be available in new sessions

### Python dependencies

Skills can declare Python dependencies via a standard `pyproject.toml`. Dependency management uses **uv** exclusively — it is pre-installed in every sandbox container.

#### Adding dependencies to a new skill

1. Create a `pyproject.toml` in the skill directory:

   ```toml
   [project]
   name = "my-skill"
   version = "0.1.0"
   requires-python = ">=3.12"
   dependencies = [
       "httpx>=0.28,<1",
   ]
   ```

2. Generate the lock file inside the sandbox:

   ```
   uv lock --directory /workspace/skills/my-skill
   ```

3. Commit and push the skill so `pyproject.toml` and `uv.lock` are persisted:

   ```
   git add /workspace/skills/my-skill && git commit -m "Add my-skill" && git push
   ```

#### Adding or removing dependencies later

Use `uv add` / `uv remove` inside the sandbox — they update both `pyproject.toml` and `uv.lock` in one step:

```
uv add --directory /workspace/skills/my-skill beautifulsoup4
uv remove --directory /workspace/skills/my-skill httpx
```

Then commit and push to persist changes.

#### How it works at activation

When `use_skill` copies a skill into the sandbox and finds a `pyproject.toml`, it automatically runs `uv sync` to create a `.venv` with all declared dependencies. Scripts should be run with `uv run` so they pick up the venv:

```
uv run --directory /workspace/skills/my-skill scripts/my_script.py
```

#### Key rules

- Always include a `uv.lock` alongside `pyproject.toml` — it ensures reproducible installs
- Never create or manage venvs manually; `uv sync` and `uv run` handle everything
- The venv is ephemeral (per session) — it is rebuilt on each activation

### Editing an existing skill

Use the `edit` tool on `skills/<name>/SKILL.md`. The same approval rule applies.

### Good description examples

```yaml
# Good -- specific, mentions triggers
description: Summarise email threads and draft replies. Use when the user mentions email, inbox, or wants to compose a message.

# Bad -- too vague
description: Helps with email.
```

### Template

When creating a new skill, start from this template and adapt it:

```markdown
---
name: <skill-name>
description: <What it does and when to use it.>
---

# <Skill Title>

## When to use

<Describe the situations where this skill applies.>

## Instructions

<Step-by-step guidance for the agent.>

## Edge cases

<Things to watch out for.>
```

If the skill needs outbound HTTP or credentials, add `carapace.yaml` with `network.domains` and/or `credentials` as in the section above.

If the skill needs Python dependencies, also create a `pyproject.toml` and generate `uv.lock` with `uv lock` in the sandbox.
