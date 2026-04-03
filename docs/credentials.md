# Credentials

Carapace keeps credentials in external vault backends and exposes them to sandboxed tools when needed. The server never persists secret values to disk, and credential access is session-scoped with explicit approval.

## Design: pull, not push

- Credentials are fetched by sandbox workloads via the sandbox API (`/credentials`).
- Skill-declared credentials are fetched during `use_skill` and injected as env vars/files.
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
- `bitwarden`: talks to an externally managed `bw serve` endpoint (typically sidecar/companion container). The Docker Compose `bw` service uses env vars such as `BW_SERVER_URL` (vault base URL for the CLI login). Empty `BW_SERVER_URL` is applied as US cloud via `bw config server bitwarden.com` when it first differs from the value stored in ephemeral container disk (`/root/.cache/carapace-bw-sidecar/`); the sidecar only logs out and re-runs `bw config server` when that env changes. See `docs/quickstart.md` for the full sidecar variable list.

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
2. After approval, Carapace fetches the values from the configured backend.
3. `env_var` entries are stored in session env and available for subsequent `exec` calls.
4. `file` entries are written inside the sandbox with mode `0400`.

Already-approved credentials are re-injected if the sandbox is recreated.

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

- First access to a credential in a session requires user approval.
- Decisions are visible in UI approval cards (including bundled skill requests).
- Approved credential metadata is tracked in session state (`approved_credentials`).
- Access attempts are appended to the session action log as `credential_access`.

Use `/session` to inspect approved credentials for the current session.

## Security notes

- Credential values are intended to stay out of model-visible responses by workflow and policy.
- This is defense-in-depth, not a hard protocol boundary: avoid commands that echo secrets.
- Never print, log, or commit credential values.
