# Example Skill Reference

This file documents the maintainer-facing details for the example skill. Runtime instructions stay in `SKILL.md`.

## Skill Structure

```text
skills/example/
  SKILL.md              # metadata and runtime instructions for the agent
  REFERENCE.md          # this maintainer reference
  carapace.yaml         # network declarations and command aliases for the demo entrypoints
  pyproject.toml        # Python project with dependencies and CLI entrypoints
  uv.lock               # locked dependency versions
  package.json          # Node project manifest using the pnpm workflow
  pnpm-lock.yaml        # locked dependency graph for pnpm installs
  setup.sh              # minimal post-activation hook example
  scripts/hello-node.mjs# Node entrypoint demonstrating the pnpm workflow
  src/example_skill/    # Python package
    __init__.py
    hello.py            # CLI entrypoint demonstrating the sandbox environment
```

## Key Files

- `SKILL.md`: YAML frontmatter plus the instructions the agent follows after activation, including the exposed command list near the top.
- `carapace.yaml`: declares the exec-scoped tunnel to `imap.gmail.com:993` and the `example-hello` / `example-node` command aliases; no credentials are required for this demo.
- `pyproject.toml`: declares Python dependencies, CLI entrypoints, and build config.
- `uv.lock`: lock file for reproducible Python installs.
- `package.json`: declares the Node-side entrypoint.
- `pnpm-lock.yaml`: lock file for reproducible pnpm installs.
- `setup.sh`: writes the local JSON config used by the Python entrypoint.
- `scripts/hello-node.mjs`: simple Node entrypoint invoked through `pnpm run hello:node`.
- `src/example_skill/`: Python package wired through `[project.scripts]`.

## Template Notes

Use this skill as a concrete provider example, not as the main authoring guide. For general skill creation rules, activate the `create-skill` skill and read its `REFERENCE.md` first.

When adapting this example:

1. Keep `SKILL.md` focused on runtime behavior.
2. Move provider and file-layout explanations into sidecar docs.
3. Keep lockfiles committed alongside provider manifests.
4. If the skill exposes command aliases, list them near the top of `SKILL.md` and prefer those aliases in the runtime instructions.
5. Keep the underlying raw `uv run --directory ...` or `pnpm --dir ... run ...` commands in `carapace.yaml`, not in frontmatter.
6. Keep setup hooks deterministic and avoid printing secrets.

## Activation Flow

When the skill is activated, Carapace copies the skill into the sandbox and runs the matching setup providers from the pushed upstream revision:

- `uv sync --locked` for `pyproject.toml` plus `uv.lock`
- `pnpm install --frozen-lockfile` for `package.json` plus `pnpm-lock.yaml`
- `setup.sh` after dependency setup

The runtime agent does not need these details to run the demo commands, so they stay out of `SKILL.md`.
