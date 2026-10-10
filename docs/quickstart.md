# Quickstart

This guide walks you through deploying carapace with Docker Compose. For Kubernetes, see the [Helm chart README](../charts/carapace/README.md).

## Prerequisites

- **Docker** with the Compose plugin
- An **Anthropic API key** (or Google API key if using Gemini models)

## 1. Create your `.env`

```bash
cp .env.example .env
```

Fill in the required values:

```env
# Required
ANTHROPIC_API_KEY=sk-ant-...
CARAPACE_TOKEN=pick-a-bootstrap-admin-password

# Optional — uncomment if needed
# GOOGLE_API_KEY=...
```

If no enabled admin user exists yet, `CARAPACE_TOKEN` becomes the bootstrap `admin` user's initial password and must be at least 16 characters long. After startup, normal web UI, CLI, REST, WebSocket, and admin access uses username/password login and an HttpOnly session cookie.

## 2. Build and start

```bash
docker compose build
docker compose up -d
```

This starts:

- **Proxy** at `http://localhost:3001`, serving the frontend and routing `/api` to the backend container internally
- **Redis** for mandatory session-list caching
- **Sandbox image** is built automatically

Log in to the web UI as `admin` with the `CARAPACE_TOKEN` value, then open **Settings** -> **Admin** -> **Users** to create your normal user. carapace is multi-user by default: sessions, jobs, notification subscriptions, Matrix channels, Git remotes, model defaults, and credential backends are owned by the authenticated user. You can also use the admin API after logging in and storing the session cookie:

```bash
curl -c carapace.cookies -X POST http://localhost:3001/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"'"$CARAPACE_TOKEN"'"}'

curl -X POST http://localhost:3001/api/admin/users \
  -b carapace.cookies \
  -H "Content-Type: application/json" \
  -d '{"username":"alice","password":"change-me","display_name":"Alice"}'
```

The web UI uses the same origin for frontend and API requests, so it only prompts for username and password on first connect.

See [auth.md](auth.md) for the full user-file format, admin API, and session-cookie behavior.

## 3. Connect via CLI (optional)

```bash
uv run carapace --user alice --password change-me
```

You can also set `CARAPACE_USER` and `CARAPACE_PASSWORD` for the CLI.

## 4. Configure from Settings

Most first-run configuration now lives in the web UI:

- **Settings** -> **Admin** -> **Platform** manages the model catalog, platform default agent/sentinel/title models, OpenAI-compatible base URLs, OpenRouter API keys, reasoning options, and default session budget.
- **Settings** -> **Admin** -> **Users** manages local users, roles, passwords, profile fields, enabled/disabled state, and assignment of existing single-user data.
- **Settings** -> **Account** manages each user's default models and budget, ChatGPT subscription for `openai-codex` models ([details](chatgpt-subscription.md)), Matrix channel, Git remote, and credential backends.
- **Settings** -> **Jobs** manages saved jobs and schedules.

The old mental model was “edit `data/config.yaml`, then restart”. There is no `config.yaml` anymore: operator/bootstrap config comes from environment variables (`CARAPACE_DATA_DIR`, `CARAPACE_DATABASE_URL`, `CARAPACE_AUTH_COOKIE__SECURE`, …) and platform settings live in the database, edited through Settings. The UI keeps write-only secrets out of API responses.

On first start, carapace seeds runtime files under `data/` and bootstraps one Git-backed knowledge repo per enabled user under `data/knowledges/<normalized-user>/`. The equivalent backing-file shape for platform defaults is:

```yaml
agent:
  model: anthropic:claude-sonnet-4-6
  sentinel_model: anthropic:claude-haiku-4-5
  # Optional defaults for every new session.
  # Omit a field, or set it to 0, to keep that budget unlimited.
  # default_session_budget:
  #   input_tokens: 100000
  #   output_tokens: 50000
  #   cost_usd: 5.00

sessions:
  commit:
    enabled: true
    # Histories are written to data/knowledges/<user>/sessions/YYYY/MM/<session_id>/conversation.json
    path_prefix: sessions
    autosave_enabled: true
    autosave_inactivity_hours: 4
    # When true, deleting a session also removes its current committed snapshot from the knowledge repo.
    delete_from_knowledge_on_session_delete: true

cache:
  # Override this only if Redis is not reachable at the default URL.
  redis_url: redis://redis:6379/0
```

Session histories always live primarily under `data/sessions/<session_id>/`. The `sessions.commit.*` settings control a secondary commit flow into the owning user's knowledge repo so the agent can refer back to past conversations later.

By default the knowledge root is `data/knowledges/`. Each enabled user gets a repo at `data/knowledges/<normalized-user>/`, initialized independently on startup. If a user has a Git remote configured, carapace adds that remote and pulls its configured branch before seeding any missing bootstrap files into that user's repo.

In the web UI, public sessions expose a "Commit to knowledge" action. Private sessions do not. Autosave uses the same privacy rule: only public, inactive sessions are eligible.

### Optional: enable notification delivery backend

Full backend behavior and API details live in [notifications.md](notifications.md).

carapace can auto-generate a VAPID keypair on startup and reuse it from `data/notifications/vapid_private_key.pem` if you do not configure one explicitly.

```yaml
notifications:
  enabled: true
  presence_ttl_seconds: 60
  subscription_ttl_days: 30
  # Optional. If omitted, carapace generates and persists a private key automatically.
  # vapid_private_key: "<private-key-pem>"
  # Optional. Defaults to "mailto:carapace@localhost".
  # vapid_subject: "mailto:you@example.com"
  send_timeout_seconds: 10
  retry_attempts: 2
  retry_backoff_seconds: 1.0
  max_payload_bytes: 4096
  delivery_ttl_seconds: 600
  default_preferences:
    escalation_pending: true
    attended_turn_completed: true
    unattended_turn_completed: false
    unattended_turn_failed: true
```

Notes:

- If `vapid_private_key` is omitted, carapace generates one on startup and reuses it from `data/notifications/vapid_private_key.pem` on later restarts.
- If `vapid_subject` is omitted, carapace uses `mailto:carapace@localhost`.
- The public key is derived from the private key and exposed through `/api/config/vapid-public-key`.
- Delivery also requires at least one client subscription registered through the `/api/notifications/*` endpoints.
- Notification subscriptions are grouped by the authenticated username.

## 5. Connect Matrix (optional)

Create a Matrix account for carapace on your homeserver, then open **Settings** -> **Account** -> **Matrix** for the owning carapace user. Enable Matrix and fill in homeserver, user id, password, allowed rooms, and allowed users. The backing user config looks like this:

```yaml
channels:
  matrix:
    enabled: true
    homeserver: https://matrix.example.com
    user_id: "@carapace:example.com"
    password: "change-me"
    allowed_rooms:
      - "!roomid:example.com"
    allowed_users:
      - "@you:example.com"
```

carapace starts one Matrix channel per enabled user config, joins the allowed rooms, and responds to messages from allowed users. Sessions are created per-room and owned by that user.

`allowed_rooms` and `allowed_users` are mandatory — without them the bot ignores all messages. This prevents accidental exposure if someone invites the bot to a public room.

## 6. Set up credentials

carapace can fetch credentials from a password manager on demand. The agent does not have blanket access — every credential request is evaluated by the sentinel agent and requires explicit user approval the first time it is used in a session. Credentials are intended to be consumed inside the sandbox (auto-injected via skill config or fetched with `ccred`) and must never be echoed or logged. Two backends are available.

### File backend (local trusted users only)

The file backend is disabled by default because its configured path is read by the server process. Only enable it with
`CARAPACE_ALLOW_FILE_CREDENTIAL_BACKEND=true` when the users who can influence credential backend config are
trustworthy.

Create a `.env`-format secrets file:

```bash
echo "github-token=ghp_xxxxxxxxxxxx" > data/secrets.env
echo "smtp-password=myapppassword" >> data/secrets.env
```

Add the backend in **Settings** -> **Account** -> **Credentials**. The equivalent backing user config is:

```yaml
users:
  alice:
    config:
      credentials:
        backends:
          dev:
            type: file
            # path defaults to <data_dir>/secrets.env
```

Credentials are accessible as `dev/github-token`, `dev/smtp-password`, etc.

### Bitwarden / Vaultwarden backend (optional)

This uses a `bw serve` sidecar container that shares the server's network namespace. carapace never sees your vault credentials — they stay in the sidecar.

1. Add your Bitwarden credentials to `.env`:

```env
# Optional. Empty means US cloud; the sidecar applies that once via `bw config server bitwarden.com`,
# records it under $BW_DATA_DIR/carapace-state/ (Compose mounts a named volume on /var/lib/bitwarden-cli), and only
# runs logout + `bw config server` again if you change this value. EU / self-hosted: set explicitly.
# BW_SERVER_URL=

BW_EMAIL=you@example.com
BW_CLIENTID=user.xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
BW_CLIENTSECRET=xxxxxxxxxxxxxxxxxxxx
BW_MASTER_PASSWORD=your-master-password
```

`BW_EMAIL` is required when using password login (no API key). `BW_CLIENTID` and `BW_CLIENTSECRET` are API keys generated in the Bitwarden web UI (Account Settings → Keys). Use them if your account has 2FA — password-only login would prompt for a TOTP code, which cannot work non-interactively in the sidecar.

If the logs show password login but you intended API key login, both `BW_CLIENTID` and `BW_CLIENTSECRET` must be non-empty in the environment Compose sees (check `.env` spelling and that variables are not commented out).

Self-hosted **Vaultwarden** must be new enough for your **Bitwarden CLI** version. If `bw login` throws `TypeError: ... toWrappedAccountCryptographicState`, upgrade Vaultwarden (see [vaultwarden#6912](https://github.com/dani-garcia/vaultwarden/issues/6912)) or pin an older `@bitwarden/cli` in `bitwarden-cli/Dockerfile`.

2. Start the sidecar:

```bash
docker compose up -d --scale bw=1
```

Startup messages from the entrypoint go to the **`bw` container** — use `docker compose logs -f bw` (not only `carapace`). Without a TTY, stdout is often block-buffered and lines can appear late or only after exit; this stack allocates a TTY for `bw` and logs progress to stderr so `docker compose logs` shows them as they run. The `bitwarden-cli-data` volume keeps Bitwarden CLI login/device state and the cached server URL across container recreation; removing that volume applies `BW_SERVER_URL` from scratch on the next start.

3. Add the backend in **Settings** -> **Account** -> **Credentials**. The equivalent backing user config is:

```yaml
users:
  alice:
    config:
      credentials:
        backends:
          personal:
            type: bitwarden
            # url defaults to http://127.0.0.1:8087
            basic_auth:
              username: alice
              password: user-specific-random-proxy-password
```

Credentials are accessible by their Bitwarden UUID: `personal/9742101e-68b8-4a07-b5b1-...`. Look up UUIDs in the Bitwarden web UI or via `bw list items`.

### Exposure control

By default, all credentials in a backend are accessible (subject to sentinel + user approval). To restrict which credentials carapace can see, set expose/hide rules in **Settings** -> **Account** -> **Credentials**. The equivalent backing user config is:

```yaml
users:
  alice:
    config:
      credentials:
        backends:
          personal:
            type: bitwarden
            basic_auth:
              username: alice
              password: user-specific-random-proxy-password
            expose: # allowlist — only these UUIDs are accessible
              - "9742101e-68b8-4a07-b5b1-9578b5f88e6f"
              - "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
            # OR:
            # hide:  # blocklist — these UUIDs are excluded
            #   - "deadbeef-..."
```

## 7. Test the bundled web skill (optional)

This is a good smoke test for the credential flow you just set up.

The bundled `web` skill uses Brave Search by default and expects a credential at `vault/brave-api-key`, which carapace injects as `BRAVE_API_KEY` when the skill runs.

If you use the file backend, add the key to your secrets file:

```bash
echo "brave-api-key=your-brave-search-api-key" >> data/secrets.env
```

Then make sure the credential is reachable as `vault/brave-api-key`. The simplest option is a file credential backend named `vault` that points at `data/secrets.env`. If you use a different backend name or path shape, update the bundled web skill metadata to match.

You can get a Brave Search API key at <https://brave.com/search/api/>.

Once that is in place, activate the `web` skill and run a simple `web_search` call. If the command succeeds, you have verified both the credential lookup and the per-exec skill injection path.

## 8. Personalise

Edit the workspace files in your own knowledge repo to shape carapace's behaviour. With the default config, user `alice` would edit files under `data/knowledges/alice/`:

| File          | Purpose                                                   |
| ------------- | --------------------------------------------------------- |
| `SOUL.md`     | Agent personality and communication style                 |
| `USER.md`     | Information about you (name, preferences, context)        |
| `SECURITY.md` | Natural-language security policy (sentinel system prompt) |
| `AGENTS.md`   | Agent behavioural guide                                   |

## Next steps

- Install skills into `data/knowledges/<your-user>/skills/` by default — see [docs/skills.md](skills.md)
- Explore the [architecture](architecture.md) and [security model](security.md)
- Explore [jobs.md](jobs.md) for scheduled and on-demand job runs
- Deploy to Kubernetes with the [Helm chart](../charts/carapace/README.md)
