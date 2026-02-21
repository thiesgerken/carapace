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
  pyproject.toml    # Python dependencies (managed by uv)
  uv.lock           # Locked dependency versions
  scripts/          # Executable scripts
    hello.py        # Example script demonstrating the sandbox environment
```

### Key files

- **`SKILL.md`** — YAML frontmatter provides `name` and `description` for the catalog.
  The body contains instructions the agent follows when the skill is activated.
- **`pyproject.toml`** + **`uv.lock`** — When present, `use_skill` builds a venv
  automatically. Scripts run with `uv run` which picks up the venv.
- **`scripts/`** — Executable Python scripts. Use `uv run --directory /workspace/skills/<name>/ scripts/<script>.py` to run them.

## Creating Your Own Skills

1. Create a directory under `skills/` (e.g. `skills/my-skill/`)
2. Add a `SKILL.md` with YAML frontmatter (`name`, `description`)
3. Optionally add `pyproject.toml` + `uv.lock` for dependencies
4. Add scripts under `scripts/`
5. Call `use_skill("my-skill")` to activate — this copies the skill into the sandbox and builds the venv
6. Call `save_skill("my-skill")` to persist any edits back to the master directory
