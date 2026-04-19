---
name: example
description: A template skill showing provider-based activation, a Python entrypoint, a Node entrypoint, post-activation setup, and an exec-scoped TCP tunnel.
---

# Example Skill

This is a template skill that demonstrates the [AgentSkills](https://agentskills.io/) format
with a Python package, a pnpm-managed Node entrypoint, provider-based activation, post-activation setup,
and an exec-scoped TCP tunnel declared in `carapace.yaml`.

## Instructions

When this skill is activated, run the example commands to verify the sandbox environment and tunnel support:

```text
uv run --directory /workspace/skills/example hello
pnpm --dir /workspace/skills/example run hello:node
```

The Python command performs an unauthenticated IMAP `CAPABILITY` request against `imap.gmail.com`
through a Carapace-managed tunnel. That demonstrates the important path for non-HTTP protocols:

- `carapace.yaml` declares `network.tunnels`
- `setup.sh` materializes a tiny local config file consumed by the Python command
- `hello` connects to the real hostname on the declared local port so TLS/SNI still work

No mailbox credentials are required for this demo because `CAPABILITY` works before login.

## Skill Structure

```text
skills/example/
  SKILL.md              # This file — metadata + instructions for the agent
  carapace.yaml         # Optional — network allowlist, tunnel declarations, + credential declarations
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
- **`carapace.yaml`** — Optional. Declares outbound domains, exec-scoped tunnels, and
  vault-backed credentials for auto-injection when the skill is activated (`use_skill`).
  This repo copy uses a tunnel to `imap.gmail.com:993` and no credentials so the example
  stays runnable in a fresh sandbox.
- **`pyproject.toml`** — Declares dependencies, CLI entrypoints (`[project.scripts]`),
  and build config. When present with `uv.lock`, `use_skill` runs `uv sync --locked` automatically.
- **`uv.lock`** — Lock file for reproducible installs. Always commit alongside `pyproject.toml`.
- **`package.json`** — Declares the Node-side entrypoint. When present with `pnpm-lock.yaml`,
  `use_skill` runs `pnpm install --frozen-lockfile` automatically.
- **`pnpm-lock.yaml`** — Lock file for reproducible pnpm installs. Always commit it with `package.json`.
- **`setup.sh`** — Runs after dependency installation. This example writes a small local JSON
  config file that tells the Python entrypoint which hostname and local tunnel port to use.
  Only the pushed upstream copy is executed automatically.
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
