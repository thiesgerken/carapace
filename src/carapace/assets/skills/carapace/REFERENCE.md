# carapace CLI Skill — Reference

Maintainer/operator notes. Runtime instructions for the agent live in `SKILL.md`.

## What this skill does

Bundles the carapace CLI inside the sandbox so an agent can drive a carapace server
non-interactively: manage sessions, send messages, resolve approvals, and manage jobs
(see `SKILL.md` for the command surface). It is a thin packaging layer — the actual CLI
is the `carapace` console script installed from the carapace package itself.

## Required setup (per deployment)

This skill ships with **placeholders** and will not work until an operator fills them in.

### 1. Create a scoped API key

In the carapace UI, create a scoped API key with the minimum scopes the agent needs
(typically `sessions:read`, `sessions:write`, and `jobs:*` depending on the task).

### 2. Store the key in the vault

Put the API key in your credential vault and note its `<backend>/<id>` path. Then edit
`SKILL.md` frontmatter, replacing the placeholder:

```yaml
credentials:
  - vault_path: <backend>/<your-carapace-api-key-id>   # <-- your vault path
    description: carapace API key (Bearer) for driving the server
    env_var: CARAPACE_API_KEY
```

On `use_skill`, carapace fetches this through the sentinel, asks for approval once, and
injects it as `CARAPACE_API_KEY` for the session. The CLI reads it automatically — the
value is never placed on a command line.

### 3. Set the server domain (TWO places, same value)

The sandbox blocks loopback and internal hostnames (`localhost`, `127.0.0.1`,
`*.internal`, `*.svc`, …), so the CLI must reach the deployment's **public** API domain.
Replace `carapace.example.com` in both spots in `SKILL.md`:

```yaml
network:
  domains:
    - carapace.example.com            # <-- 1. proxy allowlist

commands:
  - name: carapace
    command: sh -c 'CARAPACE_SERVER="https://carapace.example.com" ...'   # <-- 2. CLI target
```

Both must match. `network.domains` opens the proxy; `CARAPACE_SERVER` tells the CLI where
to connect.

## Why no uv.lock

`uv sync --locked` (the official sandbox activator's uv step) would require a committed `uv.lock`, but
locking a `git+https://…carapace.git` dependency pins a specific commit that goes stale as
carapace evolves. Instead this skill ships only `pyproject.toml` + `setup.sh`; `setup.sh`
runs `uv sync` at activation (network open), resolving carapace fresh each time and writing
an ephemeral lock inside the sandbox. Trade-off: builds are not byte-reproducible, but they
always track the current default branch.

## Install weight

The base `carapace` package is CLI-only — ~16 deps (typer, rich, httpx, websockets,
python-dotenv + their small transitive set), **no compiled wheels**, so `uv sync` at
activation takes seconds. The heavy server/agent stack (fastapi, sqlalchemy, docker, kr8s,
the LLM SDKs, …) lives in the `carapace[server]` extra and is deliberately not installed
here. Do not add `[server]` to this skill's dependency — the client needs none of it.

## File layout

```text
skills/carapace/
  SKILL.md         # frontmatter (network/credentials/commands) + agent instructions
  REFERENCE.md     # this file
  pyproject.toml   # git dependency on the carapace package
  setup.sh         # `uv sync` at activation (network open)
```

## Command alias mechanics

The `carapace` alias is registered as a shim on `PATH`. It wraps:

```sh
sh -c 'CARAPACE_SERVER="https://carapace.example.com" exec uv run --no-sync \
    --directory /workspace/skills/carapace carapace "$@"' carapace
```

- `CARAPACE_SERVER` is baked in (non-secret) so the agent never passes `--server`.
- `--no-sync` keeps command-time invocations off the network (the proxy would block the
  GitHub install anyway); all installing happens in `setup.sh`.
- `uv run` prepends the project venv's `bin` to `PATH`, so the inner `carapace` resolves to
  the installed console script, not the shim.
