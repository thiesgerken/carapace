# Skill System

carapace uses the open [AgentSkills](https://agentskills.io/) format for skills. This makes skills portable to any AgentSkills-compatible agent (Claude Code, Cursor, Gemini CLI, etc.) while carapace adds its own security layer on top.

## Skill structure

A skill is a directory with a `SKILL.md` file (Markdown instructions with YAML frontmatter) plus optional `scripts/`, `references/`, and `assets/` directories.

carapace extends the format with optional files and metadata:

- **`SKILL.md` frontmatter `metadata.carapace`** — carapace-specific metadata: network domain declarations, credential needs, and command aliases
- **`pyproject.toml`** + **`uv.lock`** — Python dependencies installed via `uv sync --locked`
- **`package.json`** + **`package-lock.json`** or **`pnpm-lock.yaml`** — Node dependencies installed with the matching package manager
- **`setup.sh`** — optional post-activation setup script for local config generation or other derived artifacts

```text
skills/
  web-search/
    SKILL.md             # required: AgentSkills standard + optional metadata.carapace
    pyproject.toml       # optional: Python dependencies
    uv.lock              # optional: required alongside pyproject.toml
    scripts/
      search.py
  node-tool/
    SKILL.md
    package.json
    package-lock.json
    setup.sh
    scripts/
      run.mjs
    references/
      api-docs.md
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

## carapace metadata

Declare carapace-specific metadata in `SKILL.md` frontmatter under `metadata.carapace`.

```yaml
---
name: web-search
description: Search the web.
metadata:
  carapace:
    network:
      domains:
        - api.searxng.example.com
        - "*.search.example.com"
      tunnels:
        - host: imap.zoho.eu
          remote_port: 993
          local_port: 1993
          description: Zoho IMAP over the carapace CONNECT proxy
    credentials:
      - vault_path: dev/searxng-url
        description: Base URL for the SearXNG instance
        env_var: SEARXNG_URL
      - vault_path: dev/searxng-cert
        description: Optional client certificate
        file: ~/.config/searxng/client.pem
    commands:
      - name: web-search
        command: uv run --directory /workspace/skills/web-search scripts/search.py
    mcp:
      - name: linear
        url: https://mcp.linear.app/mcp
        description: Linear issue tracking
        auth:
          type: bearer
          vault_path: dev/linear-mcp-token
      - name: karakeep
        command: npx -y @karakeep/mcp
        description: Karakeep bookmarks (stdio server, runs in the sandbox)
---
```

### Fields

**`network.domains`** — list of domains the skill needs to access. These are registered as a **context grant** when the skill is activated. The domains are only allowed during commands that explicitly request the skill's context (see [Context-scoped access](#context-scoped-access) below). Supports wildcard matching (`*.example.com`).

**`network.tunnels`** — list of exec-scoped TCP tunnels the skill needs. Each tunnel declaration has:

- `host` — exact remote hostname. Wildcards, IP literals, loopback names, Docker special hostnames, and Kubernetes/internal service names (`*.svc`, `*.cluster.local`, etc.) are not allowed.
- `remote_port` — target port on the remote host.
- `local_port` — unprivileged local port inside the sandbox used for the duration of the exec.
- `description` — optional human-readable explanation for approvals and docs.

carapace manages these tunnels itself during `exec(..., contexts=[...])`. Skills do not start background processes. Tunnel setup is temporary and is re-established if the sandbox has to be recreated before the command retry.

`network.domains` and `network.tunnels` may refer to the same hostname. That is intentional: HTTP and HTTPS through the proxy still work normally, while direct socket connections to the tunneled hostname are shadowed during that exec.

**`credentials`** — list of credentials the skill needs. Each entry has:

- `vault_path` — path in the password manager
- `description` — human-readable explanation shown in approval prompts
- `env_var` — environment variable name for per-exec injection (optional)
- `file` — file path for per-exec injection with mode `0400` (optional)
- `base64` — if `true`, the stored value is base64-decoded before injection (optional, default `false`). Useful for multi-line secrets (e.g. kubeconfig) that cannot be stored verbatim in a single-line password field.

> **Note**: Credential declarations are implemented. See [credentials.md](credentials.md) for approval flow, backend config, and `ccred` usage.

**`commands`** — optional list of command aliases the skill exposes. Each entry has:

- `name` — the exact alias token, for example `web-search`
- `command` — a single-line shell command to run for that alias

When the skill is activated, carapace writes a generated wrapper script for each alias into `/workspace/.carapace/bin/`, marks it executable, and exposes that directory on `PATH`. Agents should invoke the plain alias token such as `web-search`, not the absolute shim path. The wrapper looks like this conceptually:

```sh
#!/bin/sh
exec <configured command> "$@"
```

Notes:

- The wrapper preserves the caller's working directory. Do not rely on it changing cwd to the skill directory.
- Extra arguments are forwarded with `"$@"`.
- The wrapper uses shell `exec` so the launcher shell is replaced by the real command.
- `command` must be a single non-empty line.
- Alias names must be unique across active skills. If an active skill already owns an alias, activating another skill with the same alias fails.

**`mcp`** — optional list of MCP servers the skill connects to. While the skill is active, each server's tools are exposed to the agent as regular, typed tools named `<name>_<tool>` (built from the server's own JSON Schemas). Each entry is one of two transports.

Common fields:

- `name` — server name, used as the tool-name prefix. Must start with a letter and contain only letters, numbers, or underscores.
- `description` — optional human-readable explanation for approvals and docs.

**HTTP transport** — set `url`:

- `url` — the server's HTTP(S) endpoint (streamable HTTP transport).
- `auth` — optional authentication (a tagged union on `type`):
  - `type: bearer` with a `vault_path`: the token is read from the vault at activation and sent as `Authorization: Bearer <token>`.
  - `type: oauth` with a `vault_path`: the vault entry holds a JSON OAuth-state blob; carapace injects the access token, refreshes it via the refresh-token grant when missing/near-expiry/rejected (401), and **writes the rotated blob back to the vault**. See "OAuth servers" below.
- The connection is made by the **backend process**; the URL is pinned to the declared value.

**stdio transport** — set `command`:

- `command` — a shell command that starts the MCP server (e.g. `npx -y @karakeep/mcp`, `uv run --directory /workspace/skills/foo mcp-server`).
- The server process runs **inside the sandbox**, one spawn per operation (once to enumerate tools at activation, once per tool call), bridged by the baked-in `carapace-mcp-bridge`. Nothing persists between calls, so the process model matches an ordinary `exec` — no long-lived connection.
- `auth` does not apply. The server inherits the skill's context-injected credentials, so declare any secrets it needs under `credentials` with an `env_var` (or `file`); they are injected into the bridge exec under this skill's context.
- The server may reach the skill's declared `network.domains` (the bridge runs under the skill context), and stateful servers that expect a session across calls are not supported (each call is a fresh process — same limitation as invoking mcp2cli per call).

Notes (both transports):

- The declared servers are part of the `use_skill` approval, like domains and credentials. Every individual MCP tool call is still reviewed by the sentinel (shown as `mcp:<server>:<tool>`), with the usual escalate-to-user path.
- Oversized text results are spilled to a file in the sandbox (same mechanism as `exec` output).
- Server tools disappear when the session ends; there is no explicit deactivation, matching context grants.
- **Graceful degradation**: MCP servers are connected/enumerated at `use_skill` time. If a server fails (missing/expired credential, unreachable endpoint, refresh failure), the skill **still activates** — the `use_skill` result tells the agent that server is unavailable and why, and only its `<server>_*` tools are absent.
- Skills that need full control (stateful sessions, custom output shaping) can still wrap a server as a CLI with `mcp2cli` and a `commands` alias instead; `mcp` is the shortcut for the common case.

### OAuth servers (`type: oauth`)

The vault entry for an OAuth MCP server holds a compact JSON blob:

```json
{"token_url":"https://issuer/oauth2/token","client_id":"...","client_secret":"...","refresh_token":"...","access_token":"...","expires_at":1750000000,"scope":"..."}
```

Only `token_url`, `client_id`, and `refresh_token` are required (`client_secret` is omitted for public/PKCE clients; `access_token`/`expires_at` are filled in by carapace on first refresh). At connection carapace refreshes the token if it is missing or within a minute of expiry, retries once on a 401, and writes the updated blob (including a rotated `refresh_token`, if the provider returns one) back to the vault — so **the vault backend must support writes** (Bitwarden/Vaultwarden does; the file backend does too but is disabled by default).

The one-time authorization that produces the initial `refresh_token` (typically DCR + PKCE + a browser login) is done **out-of-band** — carapace only refreshes. Assemble the blob with `scripts/mcp_oauth_blob.py` and store it at the `auth.vault_path`:

```sh
python scripts/mcp_oauth_blob.py --token-url https://issuer/oauth2/token \
    --client-id <id> --refresh-token <token> > blob.json
# then store blob.json's contents in the vault entry the skill points at
```

## Context-scoped access

Skill-declared domains and credentials are **not globally available** in the session. Instead, they're scoped to individual `exec` calls via the `contexts` parameter.

### How it works

1. **Activation** creates a context grant: `use_skill("moneydb")` registers the skill's declared domains and credential vault paths as a grant keyed by `"moneydb"`.
2. **Exec requests contexts**: The agent passes `contexts=["moneydb"]` when running commands that need the skill's resources.
3. **Per-exec injection**: Domains are temporarily allowed in the proxy. Credential values are injected as env vars or written as files for the duration of that single exec. File-based credentials are deleted immediately after the command completes.
   Tunnel declarations are also applied here: carapace temporarily shadows the declared hostnames inside the sandbox, starts trusted CONNECT-backed tunnel helpers, and tears them down again after the exec.
4. **No context = no access**: An exec without `contexts` (or with unrelated contexts) does not get the skill's domains or credentials. The sentinel evaluates any credential access without a matching context.

For command aliases declared in `metadata.carapace`, carapace also recognizes the alias at the start of an `exec` command. If the owning skill is already active but missing from `contexts`, carapace adds that context automatically, resolves the command through the generated shim on `PATH`, and warns the agent to pass the context explicitly next time while continuing to use the plain alias.

### Matching semantics

- **Subset matching**: `contexts=["moneydb", "example"]` matches grants for both `"moneydb"` and `"example"` (union of both grants' resources).
- **Validation**: Every context string must correspond to an activated skill. Unknown context names are rejected.
- **Piping**: When piping output between skill scripts, pass all relevant contexts: `contexts=["moneydb", "web-search"]`.

## Sandbox-provided activation

When `use_skill` activates a skill, Carapace invokes the activator supplied by the configured sandbox image. The official image preserves the previous provider chain:

1. `pyproject.toml` + `uv.lock` → `uv sync --locked`
2. `package.json` + `package-lock.json` (without `pnpm-lock.yaml`) → `npm ci`
3. `package.json` + `pnpm-lock.yaml` → `pnpm install --frozen-lockfile`
4. `setup.sh` → `sh ./setup.sh`

Core sends the activator the exact committed source revision. The official activator detects and restores only the matching provider inputs from that revision before executing them, so later local sandbox replacements are not run automatically. Custom sandbox images may provide another implementation, such as one that realizes packages from a locked Nix flake. See [sandbox.md](sandbox.md#custom-sandbox-skill-activator-contract) for the protocol.

Activation runs with the proxy temporarily bypassed.

### Credential ordering

Skill-declared credentials are approved and cached before the sandbox activator runs. This is important for `setup.sh`, whose main use case is often to transform injected secrets into the local config files a tool actually expects.

Examples:

- Write an API token from an env var into `~/.config/<tool>/config.toml`
- Decode a base64 kubeconfig into a file under the skill directory
- Generate a `.npmrc` or other tool config from approved credentials

Activators and setup commands must never print raw secret values. Treat them as internal setup steps only.

## Python dependencies

A skill can include a `pyproject.toml` plus `uv.lock` to declare its Python dependencies. Dependency management uses **uv** exclusively — it is pre-installed in every sandbox container.

### Lifecycle

1. **Activation** (`use_skill`): with the official sandbox activator, committed `pyproject.toml` and `uv.lock` files run `uv sync --locked` in `/workspace/skills/<name>/`. The proxy is temporarily bypassed during install.
2. **Runtime**: Scripts should be invoked with `uv run --directory /workspace/skills/<name> scripts/<script>.py` so they run inside the venv.
3. **Persistence**: Skills are persisted via Git — changes in `/workspace/skills/` are committed and pushed to the workspace repository.
4. **Container restart**: Venvs are rebuilt for all activated skills automatically when a container is recreated after idle timeout.

### Managing dependencies

Inside the sandbox, use standard `uv` commands:

```bash
# Add a dependency (updates pyproject.toml + uv.lock)
uv add --directory /workspace/skills/my-skill httpx

# Remove a dependency
uv remove --directory /workspace/skills/my-skill httpx

# Install from existing lock file
uv sync --directory /workspace/skills/my-skill
```

Always commit a `uv.lock` alongside `pyproject.toml` to ensure reproducible installs.

## Node dependencies

Skills can also use Node-based tooling. The official sandbox image and activator include `npm` and `pnpm` for skill activation.

### Supported lockfile workflows

- `package.json` + `package-lock.json` → `npm ci`
- `package.json` + `pnpm-lock.yaml` → `pnpm install --frozen-lockfile`

If both `package-lock.json` and `pnpm-lock.yaml` are present, carapace treats the skill as pnpm-based and skips `npm ci`.

As with Python skills, commit the lockfile alongside the manifest so activation is reproducible.

## setup.sh

With the official sandbox activator, a committed `setup.sh` runs after the dependency providers above.

Use it for local, deterministic post-processing such as:

- Materializing approved credentials into config files consumed by a CLI or SDK
- Generating derived files that depend on injected secrets
- Finalizing a tool-specific workspace layout after dependency installation

Keep `setup.sh` idempotent. It runs on first activation and again after sandbox recreation.

Because it runs automatically and may execute with approved credentials available, `setup.sh` should be treated like code, not documentation. The official activator restores the copy from the source revision selected by core before execution.

Like the dependency providers above, `setup.sh` runs under the temporary proxy-bypass window. The trust model here is deliberate: `setup.sh` is the explicit, committed setup hook for the skill, so carapace treats it as more trustworthy than transitive package installation behavior.

## Discovery (progressive disclosure)

At startup, carapace loads only `name` and `description` from each skill's frontmatter (~100 tokens per skill). These are injected into the agent's system prompt as a skill catalog. The agent sees what's available without the full instructions consuming context.

The full `SKILL.md` body is loaded only when the agent decides a skill is relevant — via the `use_skill` tool.

## Skill activation as a security event

When the agent activates a skill (loads its full `SKILL.md` into context), a `SkillActivatedEntry` is recorded in the action log. The `use_skill` tool call goes through the sentinel (not the safe-list); the activation is logged so the sentinel has context for evaluating subsequent actions.

For example, after the agent reads skill instructions describing email credentials, the sentinel will be more cautious about outbound network requests — it knows the agent now has knowledge that could be exfiltrated.

The sentinel can also read skill files directly (via its `list_skill_files` and `read_skill_file` tools) to understand what a skill-related tool call will actually do.

## Self-improvement

The agent can create new skills by writing files to `/workspace/skills/` in the sandbox (SKILL.md, scripts, optional pyproject.toml/package.json/setup.sh provider files) and then committing and pushing them via Git.

The workflow for the agent to create a skill via chat:

1. User asks for a new skill (or the agent proposes one)
2. Agent plans the skill (SKILL.md, scripts, optional provider files such as pyproject/package.json/setup.sh)
3. Agent writes the files in the sandbox at `/workspace/skills/<skill-name>/`
4. Agent tests the skill in the sandbox
5. Agent commits and pushes via Git — the sentinel evaluates the push via the pre-receive hook
6. On approval, the skill is persisted in the workspace repository and becomes available in future sessions

A built-in `create-skill` skill is seeded on first run to guide the agent through this process.

## Bundled skills

These are seeded into every knowledge repo on first run and can be edited or deleted like any other skill:

| Skill          | Purpose                                                                        |
| -------------- | ------------------------------------------------------------------------------ |
| `carapace`     | Drive a carapace server over its JSON CLI (sessions, approvals, jobs).         |
| `create-skill` | Write and refine skills.                                                       |
| `credentials`  | List, fetch, and use secrets from the vault.                                   |
| `example`      | Reference skill showing Python and Node providers, tunnels, and setup scripts.  |
| `mermaid`      | Write Mermaid diagrams; the web UI renders ` ```mermaid ` fences as pictures.   |
| `web`          | Web search and page fetch.                                                     |
| `wikipedia`    | Wikipedia search and article fetch.                                            |
