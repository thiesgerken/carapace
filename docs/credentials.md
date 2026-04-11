# Credentials

Carapace keeps credentials in external vault backends and exposes them to sandboxed tools when needed. The server never persists secret values to disk, and credential access is session-scoped with explicit approval.

## Design: pull, not push

- Credentials are fetched by sandbox workloads via the sandbox API (`/credentials`).
- Skill-declared credentials are cached at `use_skill` time, then injected per-exec via the `contexts` parameter.
- The agent should use credentials without printing them.

In short: credentials are consumed inside the sandbox, not returned to the user-facing agent response.

## Backends

Backends are configured in `config.yaml` under `credentials.backends`:

```yaml
credentials:
  backends:
    dev:
      type: file
      path: ./data/secrets.env
    personal:
      type: bitwarden
      url: http://127.0.0.1:8087
```

Supported backend types:

- `file`: reads `key=value` pairs from a secrets file (`path` defaults to `<data_dir>/secrets.env`).
- `bitwarden`: talks to an externally managed `bw serve` endpoint (typically sidecar/companion container). The Docker Compose `bw` service uses env vars such as `BW_SERVER_URL` (vault base URL for the CLI login). Empty `BW_SERVER_URL` is applied as US cloud via `bw config server bitwarden.com` when it first differs from the value stored under the sidecar data directory (`$BW_DATA_DIR/carapace-state/`, e.g. on a Docker volume or Kubernetes PVC); the sidecar only logs out and re-runs `bw config server` when that env changes. See `docs/quickstart.md` for the full sidecar variable list.

Each credential is addressed by `vault_path` as `<backend>/<id>`, for example:

- `dev/github-token`
- `personal/9742101e-68b8-4a07-b5b1-9578b5f88e6f`

### Exposure controls

Each backend can restrict visible credentials:

```yaml
credentials:
  backends:
    personal:
      type: bitwarden
      expose:
        - "9742101e-68b8-4a07-b5b1-9578b5f88e6f"
      # or:
      # hide:
      #   - "deadbeef-..."
```

- `expose`: allowlist mode (only listed IDs are accessible)
- `hide`: blocklist mode (listed IDs are hidden)

Hidden credentials are treated as not found.

## Skill-declared credentials (`carapace.yaml`)

Skills can declare credentials for auto-injection:

```yaml
credentials:
  - vault_path: personal/9742101e-68b8-4a07-b5b1-9578b5f88e6f
    description: Gmail app password
    env_var: GMAIL_APP_PASSWORD
  - vault_path: personal/7063feab-4b10-472e-b64c-785e2b870b92
    description: SSH deploy key
    file: ~/.ssh/id_ed25519
```

On `use_skill`:

1. Credential vault paths are included in the gated `use_skill` decision.
2. After approval, Carapace fetches and **caches** the values from the configured backend (in memory only, never persisted to disk).
3. A **context grant** is registered for the skill, recording which vault paths and injection mappings are available.
4. Credentials are **not injected** into the session environment. They are only available during `exec` calls that explicitly request the skill's context (see [skills.md — Context-scoped access](skills.md#context-scoped-access)).

### Per-exec injection

When the agent runs `exec(command, contexts=["skill-name"])`:

- `env_var` entries are injected as environment variables for that single command.
- `file` entries are written inside the sandbox with mode `0400` before the command, then deleted immediately after it completes (in a `finally` block).

### Container restart

Cached credential values are re-fetched from the vault when the session is reloaded. File-based credentials are re-written only for the next exec that requests the context.

## On-demand use with `ccred`

Sandbox images include the `ccred` helper:

```bash
ccred list
ccred search gmail
ccred get <backend>/<id>
ccred get <backend>/<id> -o ~/.ssh/id_ed25519
```

- `list`/`search` return metadata only (name, vault path, optional description).
- `get` returns the raw value (or writes it to `-o` file with `0400`).
- `get` blocks until the user approves, then continues.

`ccred` reads `CARAPACE_API_URL` from the sandbox environment to reach the sandbox API with session auth.

## API surface (sandbox-only)

- `GET /credentials?q=<query>`: list/search metadata
- `GET /credentials/{vault_path}`: fetch value (approval-gated per session)

These endpoints are served on the sandbox API port (`8322`) and require Basic auth (`session_id:token`).

## Approval and audit behavior

- **Every** credential access goes through the sentinel LLM for evaluation — there is no session-wide short-circuit.
- **Context fast path**: If the credential is covered by a context grant from an activated skill, and the current exec has that skill in its `contexts`, access is allowed with `approval_source="skill"` without sentinel evaluation.
- **No context match**: Credentials accessed outside a matching context always go through the sentinel, which may allow, deny, or escalate to the user.
- All access attempts are visible in the UI: skill-granted (teal badge), sentinel-allowed (green), user-approved (purple), or denied (red).
- Access attempts are appended to the session action log as `credential_access`.

Use `/session` to inspect approved credentials for the current session.

## Security notes

- Credential values are intended to stay out of model-visible responses by workflow and policy.
- This is defense-in-depth, not a hard protocol boundary: avoid commands that echo secrets.
- Never print, log, or commit credential values.
