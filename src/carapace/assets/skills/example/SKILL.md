---
name: example
description: A template skill showing the AgentSkills format with provider-based activation, package entrypoints, and dependency management.
---

# Example Skill

This is a template skill that demonstrates the [AgentSkills](https://agentskills.io/) format
with a Python package, provider-based activation, CLI entrypoints, and dependency management.

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
  setup.sh              # Optional — post-process approved credentials into local config files
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
  and build config. When present with `uv.lock`, `use_skill` runs `uv sync --locked` automatically.
- **`uv.lock`** — Lock file for reproducible installs. Always commit alongside `pyproject.toml`.
- **`setup.sh`** — Optional. Runs after dependency installation and can turn approved credentials into
  the exact config files a tool expects. Only the pushed upstream copy is executed automatically.
- **`src/example_skill/`** — Python package. Modules with `main()` functions are
  wired as CLI commands via `[project.scripts]` in `pyproject.toml`.

## Creating Your Own Skills

1. Create a directory under `skills/` (e.g. `skills/my-skill/`)
2. Add a `SKILL.md` with YAML frontmatter (`name`, `description`)
3. Optionally add `carapace.yaml` for domains and credentials (see `create-skill` skill)
4. Create `pyproject.toml` with dependencies, `[project.scripts]` entrypoints, and build config
5. Put code in `src/<package_name>/` with an `__init__.py` and modules containing `main()` functions
6. Run `uv lock` to generate `uv.lock`
7. Optionally add `setup.sh` if the skill needs to post-process approved credentials into local config files
8. Call `use_skill("my-skill")` to activate — this copies the skill into the sandbox and runs the matching setup providers from the pushed upstream revision
9. Run commands via `uv run --directory /workspace/skills/my-skill <command>`
10. Commit and push to persist any edits back to the repository
