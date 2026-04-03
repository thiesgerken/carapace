# Plan: Credential Management

> Status: planned. Currently only a `MockCredentialBroker` stub exists (unused). The credential system described below is the target design.

Carapace does not store credentials itself. It uses an external password manager as the single source of truth and exposes credentials to the sandbox via a REST endpoint that skill scripts pull from on demand.

## Design principle: pull, don't push

Instead of a complex broker that pushes credentials into containers, the backend exposes a simple HTTP endpoint on the same internal URL the sandbox already talks to for git operations. Skills fetch credentials themselves — the agent never sees raw values, and skill authors decide how to consume them (env var, file, pipe, etc.).

A built-in **credentials skill** documents this mechanism for the agent so it knows how to access and inject credentials when following a skill's instructions. It also provides a cli that does the relevant curl requests.

## Backend endpoints

New REST endpoints on the Carapace server (on the api that already hosts the git repo for the sandboxes), authenticated by the existing sandbox token:

### List / search credentials

```
GET /credentials
GET /credentials?q=gmail
Authorization: Bearer <SANDBOX_TOKEN>
```

Returns a JSON array of available credential metadata (vault path, name, optional description) matching the query. **Does not return values** — only metadata. This lets the agent discover what credentials exist in the vault without exposing secrets.

Each list or search call is gated at the **tool call level** — the sentinel evaluates the `exec` call that runs `ccred list` or `ccred search`, not the HTTP request itself. No persistent approval state is tracked for listing. The sentinel should allow searches that make sense for the task at hand and deny fishing expeditions. The worst-case leak from a list call is credential keys (vault paths and names), not values.

### Fetch a credential

```
GET /credentials/{vault_path}
Authorization: Bearer <SANDBOX_TOKEN>
```

The server:

1. Identifies the session from the sandbox token
2. Checks whether this credential is already approved
3. If not yet approved, the request **blocks** — the server sends a `CredentialApprovalRequest` to the user via WebSocket and holds the HTTP connection open until a decision arrives
4. If the user **approves**, the server fetches the credential from the configured vault backend and returns it
5. If the user **denies**, the server returns `403`
6. Logs a `CredentialAccessEntry` to the session's action log
7. Returns the raw value in the response body (plain text, not JSON — easy to capture with `curl`)

From the caller's perspective the request either succeeds (with a possible delay while the user decides) or fails with `403` if denied. No retry loop needed.

The credential value passes through the server's memory but is **never written to disk or logged**.

## Skill credential declarations

Skills declare their credential needs in `carapace.yaml`:

```yaml
credentials:
  - vault_path: "personal/9742101e-68b8-4a07-b5b1-9578b5f88e6f"
    description: "Gmail app password for sending emails"
    env_var: GMAIL_APP_PASSWORD
  - vault_path: "personal/a1b2c3d4-e5f6-7890-abcd-ef1234567890"
    description: "SSH deploy key for the production server"
    file: /home/sandbox/.ssh/id_ed25519
```

Each credential entry has:

| Field         | Description                                                                                                                                                    |
| ------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `vault_path`  | `<backend>/<id>` — the configured backend name as prefix, followed by the credential identifier (UUID for Bitwarden backends, arbitrary key for file backends) |
| `description` | Human-readable explanation of what this credential is and what it's used for                                                                                   |
| `env_var`     | Inject as this environment variable on skill activation (optional)                                                                                             |
| `file`        | Write to this file path inside the sandbox on skill activation (optional)                                                                                      |

`vault_path` is the canonical identifier — it is what gets shown to the user in approval prompts and stored in `approved_credentials`. The prefix is the **name of the backend as configured in `config.yaml`** — not a hardcoded protocol name. This means you can have multiple Bitwarden accounts (`personal/...`, `work/...`), mix backends of different types, or point two backends at different Bitwarden-compatible instances, and vault paths remain unambiguous. For Bitwarden backends, UUIDs are used as the identifier part — guaranteed globally unique. For file backends, the identifier is whatever key you used in the secrets file. The `description` is what the agent sees and what gets shown in approval prompts alongside the vault path — without it the agent would have no idea what a credential is for and might try to discover it by searching the vault on its own.

### Auto-injection on skill activation

When `use_skill` activates a skill whose `carapace.yaml` declares credentials with `env_var` or `file`:

1. The server collects all declared vault paths from `carapace.yaml`
2. Any already-approved credentials are skipped
3. The remaining ones are sent to the sentinel as a **single evaluation** — all vault paths are included in the gate args together
4. If the sentinel escalates, the user sees **one approval prompt** listing all requested credentials (not one per credential)
5. On approval, the backend fetches all credentials from the vault in one pass
6. For `env_var` entries: values are injected as environment variables into the sandbox container for subsequent `exec()` calls
7. For `file` entries: values are written to the specified path inside the sandbox container with mode `0400` (read-only by owner — the agent can `chmod` if needed)
8. The agent and LLM never see the credential values — they are passed directly into the container runtime

This covers the common cases (API keys as env vars, SSH keys as files). For anything more dynamic, the skill's instructions can tell the agent to use the REST endpoint or `ccred` CLI directly.

The on-demand `ccred get` flow from inside the sandbox is always single-credential — `ccred` retries in a loop internally until the credential is approved or the command times out. The agent does not need to coordinate with approval; it should only request credentials that are needed and never echo secret values.

## Credential flow

### Auto-injection (via `carapace.yaml`)

```mermaid
sequenceDiagram
    participant Agent
    participant Backend
    participant Sentinel
    participant User
    participant Vault as Password Manager
    participant Sandbox

    Agent->>Backend: use_skill("email-sender")
    Backend->>Backend: parse carapace.yaml → needs Gmail app password + SMTP host credential
    Backend->>Sentinel: evaluate use_skill (all vault paths in one call)
    Sentinel->>User: "Skill email-sender needs: Gmail app password, SMTP host credential. Approve?"
    User->>Backend: /approve

    Backend->>Vault: fetch <backend>/<id> (multiple vault paths)
    Vault-->>Backend: credential values
    Backend->>Sandbox: inject as env vars / write to files
    Backend-->>Agent: "Skill activated. 2 credentials injected."
```

### On-demand fetch (via REST endpoint)

```mermaid
sequenceDiagram
    participant Agent
    participant Sandbox
    participant Backend
    participant User
    participant Vault as Password Manager

    Agent->>Sandbox: run: ccred get <backend>/<id>
    Sandbox->>Backend: GET /credentials/personal/7063feab-... (with sandbox token)
    Backend->>Backend: check approved_credentials

    alt Not yet approved
        Backend->>User: CredentialApprovalRequest (via WebSocket)
        Note over Sandbox: request blocks, waiting for decision
        User->>Backend: approves credential
    end

    Backend->>Vault: fetch credential
    Vault-->>Backend: credential value
    Backend-->>Sandbox: raw value (plain text)
    Note over Sandbox: Script uses value (env, file, pipe, etc.)
    Note over Backend: Value never returned to agent
```

## Built-in credentials skill

A built-in skill (`credentials`) teaches the agent how the credential system works. Its `SKILL.md` documents:

- How to read a skill's `carapace.yaml` to discover required credentials
- That credentials declared with `env_var` or `file` are auto-injected when the skill is activated
- How to list available credentials: `ccred list` (evaluated by the sentinel on each call)
- How to search: `ccred search gmail` — same gating as list, filtered by name/description
- How to fetch a credential: `ccred get <backend>/<id>` (blocks until approved, then prints to stdout)
- How to write a credential to a file: `ccred get <backend>/<id> -o ~/.ssh/id_ed25519` with mode `0400` — `-o` is subject to approval like stdout fetch; preferred for SSH keys and certificates
- How to use a credential inline in a command: `PASSWORD=$(ccred get <backend>/<id>) my-command` — the value is scoped to that single command
- How to use a credential as a persistent env var across commands: declare `env_var` in `carapace.yaml` — Carapace injects it into every sandbox exec call for the session so it is available without re-fetching. Alternatively, with the persistent shell, `export TOKEN=$(ccred get <backend>/<id>)` works for the duration of the shell session.
- That credential values must **never** be echoed, printed, logged, or returned as command output — not even partially
- That only credentials that are needed should be requested, and secrets must never be echoed directly — the agent does not need to manage the approval UI flow

This way the agent learns the credential workflow from the skill's instructions — no special tool needed.

## Security properties

- **Credentials stay out of LLM context (by convention, not code enforcement)**: The backend never returns credential values to the agent — it fetches them and injects them directly into the sandbox. However, this guarantee relies on the agent following instructions (the `credentials` skill explicitly prohibits printing or returning secrets) and the sentinel detecting and blocking any command that would echo a credential. It is **not** enforced at the protocol level — if the agent were compelled by a malicious prompt to print a secret it had already written to a file, the sentinel would be the last line of defence. Treat it as defense-in-depth rather than a hard boundary.
- **No credential persistence**: The server never writes credentials to disk. They exist only in memory for the duration of a request.
- **Per-session approval**: Each credential must be approved the first time it is requested in a session. Approval is all-or-nothing for bundled requests (skill activation) — the user cannot partially approve a bundle. After `/reset`, all approvals are revoked. There is no mid-session revocation: once a credential has been injected into the sandbox, the value may have been copied elsewhere inside the container, so revoking access would be cosmetic.
- **Sentinel evaluation**: All credential access is gated at the tool-call level — the sentinel evaluates the `exec` call containing the `ccred` command or the `use_skill` call that triggers auto-injection. The backend API is on the same host as the git remote and is excluded from the HTTP proxy, so the sentinel never sees the HTTP requests themselves; the `exec` tool call is the only gate. For list/search the sentinel sees the command string and can deny it if it doesn't fit the task. For fetch, it sees the vault path in the command args.
- **Audit trail**: Every credential access is logged as a `CredentialAccessEntry` in the session action log and visible in Logfire traces.
- **Sandbox-scoped**: The REST endpoint is only reachable from inside the sandbox (authenticated by sandbox token). The credential is delivered to the container, not to the agent.

## UI: session credential visibility

The frontend displays credential state for the active session:

- **Session info panel**: Shows the list of approved credentials alongside existing fields (activated skills, allowed domains). Each credential shows its name and approval status.
- **Approval cards**: When credential approval is needed, a `CredentialApprovalCard` component renders — same pattern as domain-access and git-push approval cards. The card displays a **list of vault paths** being requested (not just one), so the user can review the full bundle before approving. For single on-demand fetches the list has one entry; for skill activation it may have several. The user approves or denies the entire bundle.
- **`/session` command**: Already returns `approved_credentials` — the frontend `CommandResultView` renders them in the session info display.

### WebSocket messages

- New `CredentialApprovalRequest` server message:

  ```typescript
  {
    type: "credential_approval_request",
    vault_paths: string[],       // one or more credentials being requested
    names: string[],             // human-readable names (parallel to vault_paths)
    descriptions: string[],      // optional descriptions (empty string if unavailable)
    skill_name?: string,         // set when triggered by skill activation
    explanation: string
  }
  ```

- Response from the frontend:

  ```typescript
  {
    type: "credential_approval_response",
    vault_paths: string[],       // echoes the requested paths
    decision: "approved" | "denied"
  }
  ```

- The existing `StatusUpdate` or a new `SessionStateUpdate` message can push credential approvals to the UI in real-time so the session info panel stays current.

## Password manager backends

Supported backends:

| Backend   | Integration        |
| --------- | ------------------ |
| Bitwarden | Via `bw serve` CLI |
| File      | `.env`-format file |

Start with a single backend. Multiple backends (prefix-based routing, per-backend exposure rules) can be added later without rearchitecting — the vault interface stays the same, the server just dispatches to different instances based on vault path prefix.

### File backend

The simplest backend: a single file in `.env` format where each line is `vault_path=secret_value`. Default location is `<data_dir>/secrets.env`, overridable in config.

```env
gmail=myapppassword123
github-token=ghp_xxxxxxxxxxxx
ssh/deploy-key=-----BEGIN OPENSSH PRIVATE KEY-----...
```

The file is read once at startup and cached in memory. Listing returns all keys; searching filters by substring match against the key. The vault path for a key is `<backend-name>/<key>` — e.g. if the backend is configured as `dev`, then `dev/gmail` maps to the `gmail` entry. This backend is useful for simple setups, development, and testing.

Configuration in `config.yaml`:

```yaml
credentials:
  backends:
    dev: # becomes the vault_path prefix: dev/<key>
      type: file
      path: ./data/secrets.env # default: <data_dir>/secrets.env
```

### Bitwarden backend

Carapace is a personal assistant — it needs access to your personal password store, not a separate secrets system. Sharing credentials from your existing Bitwarden-compatible vault is much more natural than copying them to another tool.

Bitwarden encrypts all vault data client-side — there is no server API that returns plaintext secrets. Decryption always happens locally, which means Carapace uses the **`bw serve`** command to run a local REST API that handles decryption transparently.

#### Why `bw serve` instead of the `bw` CLI

Shelling out to `bw get` for every credential request has drawbacks: process startup overhead, session key management, and error-prone argument passing. The `bw serve` command starts a persistent local HTTP server (Express.js) that exposes the full Vault Management API. Carapace talks to it via `httpx` — no subprocess spawning per request.

#### `vault_path` identifier

Every Bitwarden item has a stable UUID. Credential references in `carapace.yaml` use the format `<backend-name>/<uuid>`, where `<backend-name>` is whatever name you gave this backend in `config.yaml`. For example, if the backend is named `personal`, vault paths look like `personal/9742101e-68b8-4a07-b5b1-9578b5f88e6f`. This means you can configure a second Bitwarden account as backend `work` and its items appear as `work/<uuid>` — no collision with `personal/...`. Skill authors look up the UUID in the Bitwarden web UI (or via `bw list items`) and paste it into their `carapace.yaml`.

The `description` field in `carapace.yaml` provides the human- and agent-readable context for what the credential is. Without it, the agent would only see an opaque UUID and might try searching the vault on its own.

#### Authentication

Authentication requires two things:

- **API key** (`BW_CLIENTID` + `BW_CLIENTSECRET`) — for non-interactive login. Generated in the Bitwarden web UI under account settings.
- **Master password** (`CARAPACE_VAULT_PASSWORD`) — for vault decryption.

#### Startup sequence

The Carapace server authenticates and starts `bw serve` at startup:

```bash
bw config server https://vault.example.com       # point to self-hosted instance
bw login --apikey                                  # uses BW_CLIENTID + BW_CLIENTSECRET
bw unlock --passwordenv CARAPACE_VAULT_PASSWORD    # decrypts the vault
bw serve --port 8087 --hostname 127.0.0.1          # starts local REST API
```

The `bw serve` process is managed as a child process of the Carapace server. It listens only on `127.0.0.1` and is never exposed externally.

#### API usage

Once `bw serve` is running, Carapace uses the [Vault Management API](https://bitwarden.com/help/vault-management-api/):

```
GET http://127.0.0.1:8087/object/item/{uuid}         # full item (all fields, decrypted)
GET http://127.0.0.1:8087/object/password/{uuid}      # just the password
GET http://127.0.0.1:8087/object/username/{uuid}      # just the username
GET http://127.0.0.1:8087/list/object/items            # list all items (metadata)
GET http://127.0.0.1:8087/list/object/items?search=gmail  # search by name
POST http://127.0.0.1:8087/sync                        # refresh vault from server
```

When Carapace receives a request for `<backend-name>/<uuid>`, the backend strips the `<backend-name>/` prefix and calls `GET /object/password/<uuid>` (or `/object/item/<uuid>` for full access including username, notes, custom fields, etc.).

For the `GET /credentials` list/search endpoint, the backend calls `GET /list/object/items` on `bw serve`, maps the results to return only metadata (item name, UUID, folder), and applies exposure filters before returning.

#### Optional: dedicated Carapace user

For tighter isolation, create a separate Bitwarden user account for Carapace and share items via an organization collection. This way the `bw serve` instance only sees explicitly shared items. This is optional — using your personal account with exposure-control patterns works fine too.

#### Lifecycle

Carapace does **not** manage the `bw serve` process — it expects the process to be running externally before startup. In Docker Compose this is a companion service with `network_mode: service:carapace` (shared network namespace); in Kubernetes it runs as a sidecar container in the same Pod. Either way, `bw serve` is reachable at `127.0.0.1:<port>` from the Carapace container without any network policy.

The `bw` CLI binary is **not** installed in the Carapace image. Vault credentials (`BW_CLIENTID`, `BW_CLIENTSECRET`, master password) are only present in the `bw serve` container's environment, never in the Carapace container. A periodic `POST /sync` call (managed by the sidecar's own entrypoint or Carapace's backend) keeps the local vault in sync with the Bitwarden server.

#### Credential metadata returned by `bw serve`

The backend interface returns a `CredentialMetadata` object alongside the value for every listed item:

```python
class CredentialMetadata(BaseModel):
    vault_path: str       # full path including backend prefix
    name: str             # human-readable name (Bitwarden item name)
    description: str = "" # optional extra context
```

For the Bitwarden backend, `name` is the item's name in Bitwarden and `description` is empty (it is only set when a `carapace.yaml` entry provides one). For the file backend, `name` is the key itself and `description` is always empty. The `CredentialMetadata` objects are stored in `approved_credentials` so the session info panel and approval prompts have the right data at hand without querying the vault again.

#### Deployment

In both Docker Compose and Kubernetes, `bw serve` runs as a **separate container sharing the Carapace network namespace** — not as a child process. Carapace never spawns or manages `bw serve`; it just connects to `127.0.0.1:<port>`.

**Docker Compose**: The `bw` service uses `network_mode: service:carapace` so it shares `127.0.0.1` with the Carapace container. Vault secrets are only in the `bw` service's environment.

**Kubernetes**: `bw serve` runs as a sidecar container in the same Pod. Containers in a Pod share a network namespace, so `127.0.0.1:8087` still works. Vault secrets are mounted from a K8s Secret into the sidecar only. See the Helm chart's `bitwarden.instances` value for configuration.

Configuration in `config.yaml`:

```yaml
credentials:
  backends:
    personal: # becomes the vault_path prefix: personal/<uuid>
      type: bitwarden
      url: https://vault.example.com
      # Auth via env vars:
      #   BW_CLIENTID              — API key client ID
      #   BW_CLIENTSECRET          — API key client secret
      #   CARAPACE_VAULT_PASSWORD  — master password for vault unlock
```

### Exposure control

The vault config includes an allowlist or blocklist of Bitwarden item UUIDs (or glob patterns on vault paths) that Carapace is permitted to access. This is a hard boundary enforced **before** the sentinel — if a credential doesn't match the exposure rules, the server rejects the request immediately without consulting the sentinel or prompting the user.

When using your personal Bitwarden account, exposure control is the primary mechanism for limiting what Carapace can see. Without it, the agent could potentially request any item in your vault (though it would still need sentinel + user approval for each one).

Rules match the identifier part of the vault path (everything after the backend prefix). Exposure is configured per-backend:

- **`expose`** (allowlist mode): only listed IDs are accessible. Default if specified.
- **`hide`** (blocklist mode): listed IDs are excluded, everything else is accessible.

If neither is specified, all credentials in that backend are accessible (sentinel-only gating).

Configuration in `config.yaml`:

```yaml
credentials:
  backends:
    personal:
      type: bitwarden
      url: https://vault.example.com
      expose:
        - "9742101e-68b8-4a07-b5b1-9578b5f88e6f" # Gmail app password
        - "a1b2c3d4-e5f6-7890-abcd-ef1234567890" # GitHub token
        - "7063feab-4b10-472e-b64c-785e2b870b92" # SSH deploy key
      # OR alternatively:
      # hide:
      #   - "deadbeef-..."  # banking credentials
      # Auth via env vars: BW_CLIENTID, BW_CLIENTSECRET, CARAPACE_VAULT_PASSWORD
    dev:
      type: file
      path: ./data/secrets.env
```

The `GET /credentials` list endpoint only returns credentials that pass the exposure filter. The `GET /credentials/{vault_path}` fetch endpoint returns `404` (not `403`) for hidden credentials — they are invisible, not just denied.

## Implementation notes

### What already exists

- `SessionState.approved_credentials` — list field; needs to change from `list[str]` to `list[CredentialMetadata]` to carry name + description
- `SkillCarapaceConfig.credentials` — `carapace.yaml` parsing works (currently `list[dict[str, str]]` — should become a typed model)
- Sandbox token auth — the sandbox already authenticates to the backend for git
- Container env injection — `docker.py` `exec()` accepts `env: dict[str, str]` (per-exec only; session-wide env needs the new `session_env` field)
- Domain approval pattern in `use_skill` — can be mirrored for credential gating
- `_build_proxy_env()` in `manager.py` — already injects `GIT_REPO_URL`, `HTTP_PROXY`, etc.; `CARAPACE_API_URL` goes here too

### What needs to be built

1. **`CredentialMetadata` model** in `models.py` — `vault_path`, `name`, `description` — returned by both backend list and fetch, stored in session state and approval prompts
2. **`SkillCredentialDecl` model** replacing `list[dict[str, str]]` in `SkillCarapaceConfig` (fields: `vault_path`, `description`, `env_var`, `file`)
3. **`SessionContainer.session_env: dict[str, str]`** field on `SessionContainer` — merged into every `_exec()` call so approved `env_var` credentials persist for the lifetime of the container. On container recreation, the engine must re-fetch and re-inject all currently-approved `env_var` credentials before the agent resumes — the agent should never observe that the container restarted.
4. **`CARAPACE_API_URL` env var** injected by `_build_proxy_env()` — the same host:port the git remote already uses, just exposed as a named variable. `ccred` uses this as its base URL.
5. **`GET /credentials/{vault_path}` endpoint** in `server.py` — blocking approval flow, vault fetch, logging
6. **`GET /credentials` list/search endpoint** in `server.py` — metadata only, gated, no values
7. **Vault backend protocol** (`credentials.py`) — abstract interface with `fetch(id) -> str`, `list(query) -> list[CredentialMetadata]`, `fetch_metadata(id) -> CredentialMetadata`
8. **File backend** implementation of the vault protocol
9. **Bitwarden/`bw serve` backend** implementation — HTTP client pointing at an externally managed `bw serve`
10. **Credential gating in `use_skill`** — extend the `_gate()` call to include vault paths + metadata, inject approved values into `session_env` (env vars) or write to files in sandbox on approval
11. **`approved_credentials`** updated from `list[str]` to `list[CredentialMetadata]` in `SessionState` and all callers
12. **`CredentialAccessEntry`** in `security/context.py` action log (covers both fetch and list/search)
13. **`CredentialApprovalRequest` / `CredentialApprovalResponse`** WebSocket messages (`ws_models.py`) — carry `vault_paths`, `names`, `descriptions`, and optional `skill_name`; follow the same escalation queue pattern as domain/git-push approvals
14. **Matrix channel support** — `on_credential_approval_request` in `MatrixSubscriber`, resolve via reaction/command (same pattern as domain approval); `PendingCredentialApproval` class in `approval.py`
15. **Frontend `CredentialApprovalCard`** component — renders name + description for each credential with approve/deny for the bundle
16. **Session info panel** frontend update — show `approved_credentials` (with names) alongside skills and domains
17. **Built-in `credentials` skill** with `SKILL.md` documenting the pull mechanism (including list/search and the `CARAPACE_API_URL` env var)
18. **`ccred` CLI helper** baked into the sandbox image — subcommands: `list`, `search <query>`, `get <vault_path> [-o file]`

### Cleanup

- Remove `MockCredentialBroker` from `credentials.py` — it is unused and the pull-based design replaces it entirely

### Docs & testing

- **`AGENTS.md`** (repo root): add `credentials.py` to the project structure map with a one-line description of the new vault backend interface
- **`docs/sandbox.md`**: add `CARAPACE_API_URL` to the list of env vars injected into containers
- **`docs/architecture.md`**: add credential endpoints to the server API section and mention the vault backend abstraction
- **`docs/security.md`**: add a note that credential access (fetch + list) goes through the sentinel and that the LLM-context guarantee is convention-based, not protocol-enforced
- **Tests** (`tests/test_credentials.py` — new file): file backend unit tests (fetch, list, exposure filter); mock vault backend tests for the REST endpoints (approval flow, blocking, `403` vs `404`)
- **Tests** (`tests/test_server.py`): add credential endpoint tests alongside the existing server tests
- **Tests** (`tests/test_session.py`): cover `session_env` re-injection on container recreation
