---
name: example
description: A template skill showing the AgentSkills format with scripts and dependencies.
---

# Example Skill

This is a template skill that demonstrates the [AgentSkills](https://agentskills.io/) format
with Python scripts and dependency management.

## Instructions

When this skill is activated, run the example script to verify the sandbox environment:

```text
uv run --directory /workspace/skills/example scripts/hello.py
```

## Skill Structure

```text
skills/example/
  SKILL.md          # This file — metadata + instructions for the agent
  carapace.yaml     # Optional — network allowlist + credential declarations for Carapace
  pyproject.toml    # Python dependencies (managed by uv)
  uv.lock           # Locked dependency versions
  scripts/          # Executable scripts
    hello.py        # Example script demonstrating the sandbox environment
```

### Key files

- **`SKILL.md`** — YAML frontmatter provides `name` and `description` for the catalog.
  The body contains instructions the agent follows when the skill is activated.
- **`carapace.yaml`** — Optional. Declares outbound domains under `network.domains` and
  vault-backed credentials for auto-injection when the skill is activated (`use_skill`).
  This repo copy uses a fictional credential path and `httpbin.org` so `hello.py` can
  reach https://httpbin.org/get after approval; replace with your real entries.
- **`pyproject.toml`** + **`uv.lock`** — When present, `use_skill` builds a venv
  automatically. Scripts run with `uv run` which picks up the venv.
- **`scripts/`** — Executable Python scripts. Use `uv run --directory /workspace/skills/<name>/ scripts/<script>.py` to run them.

## Creating Your Own Skills

1. Create a directory under `skills/` (e.g. `skills/my-skill/`)
2. Add a `SKILL.md` with YAML frontmatter (`name`, `description`)
3. Optionally add `carapace.yaml` for domains and credentials (see `create-skill` skill)
4. Optionally add `pyproject.toml` + `uv.lock` for dependencies
5. Add scripts under `scripts/`
6. Call `use_skill("my-skill")` to activate — this copies the skill into the sandbox and builds the venv
7. Commit and push to persist any edits back to the repository
