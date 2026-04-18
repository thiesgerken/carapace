---
name: example
description: A template skill showing the AgentSkills format with provider-based activation, Python and Node entrypoints, and post-activation setup.
---

# Example Skill

This is a template skill that demonstrates the [AgentSkills](https://agentskills.io/) format
with a Python package, a pnpm-managed Node entrypoint, provider-based activation, and post-activation setup.

## Instructions

When this skill is activated, run the example commands to verify the sandbox environment:

```text
uv run --directory /workspace/skills/example hello
pnpm --dir /workspace/skills/example run hello:node
```

`setup.sh` is intentionally minimal in this template and just prints `hello world` during
activation to show where post-activation hooks run.

## Skill Structure

```text
skills/example/
  SKILL.md              # This file — metadata + instructions for the agent
  carapace.yaml         # Optional — network allowlist + credential declarations for Carapace
  pyproject.toml        # Python project with dependencies and CLI entrypoints
  uv.lock               # Locked dependency versions
  package.json          # Node project manifest using the pnpm workflow
  pnpm-lock.yaml        # Locked dependency graph for pnpm installs
  setup.sh              # Minimal post-activation hook example
  scripts/hello-node.mjs# Node entrypoint demonstrating the pnpm workflow
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
- **`package.json`** — Declares the Node-side entrypoint. When present with `pnpm-lock.yaml`,
  `use_skill` runs `pnpm install --frozen-lockfile` automatically.
- **`pnpm-lock.yaml`** — Lock file for reproducible pnpm installs. Always commit it with `package.json`.
- **`setup.sh`** — Runs after dependency installation. This example keeps it intentionally minimal
  and just prints `hello world` so the hook remains easy to understand. Only the pushed upstream copy is executed automatically.
- **`scripts/hello-node.mjs`** — Simple Node entrypoint invoked via `pnpm run hello:node`.
- **`src/example_skill/`** — Python package. Modules with `main()` functions are
  wired as CLI commands via `[project.scripts]` in `pyproject.toml`.

## Creating Your Own Skills

1. Create a directory under `skills/` (e.g. `skills/my-skill/`)
2. Add a `SKILL.md` with YAML frontmatter (`name`, `description`)
3. Optionally add `carapace.yaml` for domains and credentials (see `create-skill` skill)
4. Add the provider files you need: `pyproject.toml` + `uv.lock`, `package.json` + `pnpm-lock.yaml`, and/or `setup.sh`
5. Put Python code in `src/<package_name>/` with an `__init__.py` and modules containing `main()` functions
6. Put Node entrypoints or scripts under `scripts/` and wire them through `package.json`
7. Call `use_skill("my-skill")` to activate — this copies the skill into the sandbox and runs the matching setup providers from the pushed upstream revision
8. Run commands via `uv run --directory /workspace/skills/my-skill <command>` or `pnpm --dir /workspace/skills/my-skill run <script>`
9. Commit and push to persist any edits back to the repository
