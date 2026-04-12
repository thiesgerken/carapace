---
name: example
description: A template skill showing the AgentSkills format with package entrypoints and dependencies.
---

# Example Skill

This is a template skill that demonstrates the [AgentSkills](https://agentskills.io/) format
with a Python package, CLI entrypoints, and dependency management.

## Instructions

When this skill is activated, run the example command to verify the sandbox environment:

```text
uv run --directory /workspace/skills/example hello
```

## Skill Structure

```text
skills/example/
  SKILL.md              # This file — metadata + instructions for the agent
  carapace.yaml         # Optional — network allowlist + credential declarations for Carapace
  pyproject.toml        # Python project with dependencies and CLI entrypoints
  uv.lock               # Locked dependency versions
  src/example_skill/    # Python package (underscores, matching project name)
    __init__.py         # Empty file (required for package)
    hello.py            # CLI entrypoint demonstrating the sandbox environment
```

### Key files

- **`SKILL.md`** — YAML frontmatter provides `name` and `description` for the catalog.
  The body contains instructions the agent follows when the skill is activated.
- **`carapace.yaml`** — Optional. Declares outbound domains under `network.domains` and
  vault-backed credentials for auto-injection when the skill is activated (`use_skill`).
  This repo copy uses a fictional credential path and `httpbin.org` so `hello` can
  reach https://httpbin.org/get after approval; replace with your real entries.
- **`pyproject.toml`** — Declares dependencies, CLI entrypoints (`[project.scripts]`),
  and build config. When present, `use_skill` builds a venv automatically.
- **`uv.lock`** — Lock file for reproducible installs. Always commit alongside `pyproject.toml`.
- **`src/example_skill/`** — Python package. Modules with `main()` functions are
  wired as CLI commands via `[project.scripts]` in `pyproject.toml`.

## Creating Your Own Skills

1. Create a directory under `skills/` (e.g. `skills/my-skill/`)
2. Add a `SKILL.md` with YAML frontmatter (`name`, `description`)
3. Optionally add `carapace.yaml` for domains and credentials (see `create-skill` skill)
4. Create `pyproject.toml` with dependencies, `[project.scripts]` entrypoints, and build config
5. Put code in `src/<package_name>/` with an `__init__.py` and modules containing `main()` functions
6. Run `uv lock` to generate `uv.lock`
7. Call `use_skill("my-skill")` to activate — this copies the skill into the sandbox and builds the venv
8. Run commands via `uv run --directory /workspace/skills/my-skill <command>`
9. Commit and push to persist any edits back to the repository
