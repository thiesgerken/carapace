# Credentials

carapace keeps credentials in external vault backends and exposes them to sandboxed tools when needed. The server never persists secret values to disk, and every credential access is approved for one `exec` at a time.

## Design: pull, not push

- Credentials are fetched by sandbox workloads via the sandbox API (`/credentials`).
- A skill command declares the credentials it needs in its flake; its wrapper asks for them with `cgate request` and fetches them with `ccred get` when it starts.
- The agent should use credentials without printing them.

In short: credentials are consumed inside the sandbox, not returned to the user-facing agent response.

## Backends

Backends are a `credentials` object in each user's config (shown as YAML below). Sessions use the credential
backends owned by their session user.

```yaml
credentials:
  backends:
    dev:
      type: file
      path: ./data/secrets.env
    personal:
      type: bitwarden
      url: http://carapace-bitwarden-alice
      basic_auth:
        username: alice
        password: user-specific-random-proxy-password
```

Users edit their own backends under Settings -> Account, which saves through `PATCH /api/user/settings` (body
`{"credentials": {...}}`). Admins can set them for any user with `PATCH /api/admin/users/{username}` (body
`{"config": {"credentials": {...}}}`).

The file backend is disabled by default. Enable it with `CARAPACE_ALLOW_FILE_CREDENTIAL_BACKEND=true` only when the
users who can influence credential backend configuration are trustworthy: a file backend path is read by the server
process and can point at arbitrary files the backend can access.

Each user can point at their own vault proxy and authentication boundary. Admin API responses redact backend proxy
passwords, and updates that omit an existing proxy password keep the stored value.

Password fields are write-only in Settings -> Account: responses report whether a password is configured, but never
return the stored value. The file backend is only accepted when `CARAPACE_ALLOW_FILE_CREDENTIAL_BACKEND=true` is set on
the server process.

Supported backend types:

- `file`: reads `key=value` pairs from a secrets file (`path` defaults to `<data_dir>/secrets.env`). This backend is
  ignored unless `CARAPACE_ALLOW_FILE_CREDENTIAL_BACKEND=true` is set on the server process.
- `bitwarden`: talks to an externally managed `bw serve` endpoint (typically a companion container or a separate Pod behind a proxy). The Docker Compose `bw` service uses env vars such as `BW_SERVER_URL` (vault base URL for the CLI login). Empty `BW_SERVER_URL` is applied as US cloud via `bw config server bitwarden.com` when it first differs from the value stored under the Bitwarden CLI data directory (`$BW_DATA_DIR/carapace-state/`, e.g. on a Docker volume or Kubernetes PVC); the Bitwarden CLI process only logs out and re-runs `bw config server` when that env changes. See `docs/quickstart.md` for the full Docker Compose variable list.

For a standalone Kubernetes `bw serve` Pod, keep `bw serve` bound to localhost inside that Pod and expose an nginx
proxy with HTTP Basic Auth. The proxy has to send `Host: 127.0.0.1:<port>` upstream and no `Origin` header: `bw serve`
answers 403 to any other Host and to any request with an Origin (the chart's sidecar does both). Configure the matching `basic_auth` block on the user's Bitwarden backend. carapace redacts
the proxy password from auth/admin API responses, but stores it in the user's `config` column in the database.

Each credential is addressed by `vault_path` as `<backend>/<id>`, for example:

- `dev/github-token`
- `personal/9742101e-68b8-4a07-b5b1-9578b5f88e6f`

### Exposure controls

Each backend can restrict visible credentials:

```yaml
users:
  thies:
    config:
      credentials:
        backends:
          personal:
            type: bitwarden
            basic_auth:
              username: thies
              password: user-specific-random-proxy-password
            expose:
              - "9742101e-68b8-4a07-b5b1-9578b5f88e6f"
            # or:
            # hide:
            #   - "deadbeef-..."
```

- `expose`: allowlist mode (only listed IDs are accessible)
- `hide`: blocklist mode (listed IDs are hidden)

Hidden credentials are treated as not found.

## Skill-declared credentials

A skill declares the credentials its commands need as credential slots in its flake (see [skill-flakes.md](skill-flakes.md#credential-slots)), not in its `SKILL.md`, and `skills/config.json` binds each slot to a vault path. The generated wrapper asks for everything the command needs with `cgate request` before it starts; `cgate` then fetches each bound credential with `ccred get` and exports it. A slot without a binding stops the command with a hint how to bind it. Nothing is cached on the server and nothing is injected from outside: the values reach the sandbox only through `ccred`, reviewed per `exec`.

A command that needs a credential in a file writes it itself (`ccred get <vault_path> -o <file>`) and removes it when done.

## On-demand use with `ccred`

Sandbox images include the `ccred` helper:

```bash
ccred list
ccred search gmail
ccred get <backend>/<id>
ccred get <backend>/<id> --login
ccred get <backend>/<id> --json
ccred get <backend>/<id> --access-token
ccred get <backend>/<id> -o ~/.ssh/id_ed25519
```

- `list`/`search` return metadata only (name, vault path, optional description). They still enumerate the vault, so the sentinel reviews them like `get`.
- `get` returns the raw password/value by default (or writes it to `-o` with mode `0400`).
- `--login` returns the provider login name when supported. Bitwarden supports it; unsupported providers fail with a non-zero exit code.
- `--json` returns the complete provider-specific item. Every provider supports this.
- `--access-token` returns a short-lived access token of an OAuth entry, which Carapace refreshes; `--refresh` forces a new one, once per `exec`. The entry itself (it holds the refresh token) is refused in every other form. See [skill-flakes.md](skill-flakes.md#oauth) for its format.
- `--login`, `--json` and `--access-token` are mutually exclusive.
- Every command blocks until the sentinel (or the user, if it escalates) decides. A denial exits with status 1 and prints the reason on stderr, e.g. `error: Sentinel denied this operation. <explanation>`; the calling script decides how to continue.
- An approval holds for the rest of the `exec`, for the representation that was asked for: asking again for the same credential in the same form returns without another review, while `--login` or `--json` after an approved password is reviewed again. The next `exec` asks again.

`ccred` reads `CARAPACE_API_URL` from the sandbox environment to reach the sandbox API with session auth.

A command that knows its credentials in advance can declare them with `cgate request --credential <backend>/<id>` before it starts (see [sandbox.md](sandbox.md#declaring-needs-up-front-cgate)). One review covers the declaration, and the following `ccred get` calls for those credentials return without another one for the rest of the `exec`.

## API surface (sandbox-only)

- `GET /credentials?q=<query>`: list/search metadata (approval-gated per exec)
- `GET /oauth-token/{vault_path}[?refresh=true]`: access token of an OAuth entry (approval-gated per exec)
- `GET /credentials/{vault_path}?kind=password|login|json`: fetch the selected representation (approval-gated per exec)

A denial is a `403` with the explanation as a plain-text body.

These endpoints are served on the sandbox API port (`8322`) and require Basic auth (`session_id:token`).

## Approval and audit behavior

- Credential requests are boundary requests: the sentinel decides them on their own, with the `exec` calls since its last decision in view, not as a check behind an already reviewed `exec` (see [security.md](security.md#boundary-requests)).
- **Per-exec approval**: an approved credential (per vault path and representation) or listing needs no further review until the `exec` ends. There is no session-wide short-circuit.
- Every first request in an `exec` goes to the sentinel, which may allow, deny, or escalate to the user.
- **No running exec**: a request from a process an earlier `exec` left behind is refused without a review. A decision that comes back after its `exec` ended is not granted either.
- The first request per credential and `exec` is reviewed and recorded: visible in the UI (sentinel-allowed green, user-approved purple, denied red), appended to the session action log as `credential_access` and to the audit log. Repeats of an approved request within the same `exec` are not recorded again.

## Security notes

- Credential values are intended to stay out of model-visible responses by workflow and policy.
- This is defense-in-depth, not a hard protocol boundary: avoid commands that echo secrets.
- Never print, log, or commit credential values.
