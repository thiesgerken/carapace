# Quickstart

This guide walks you through deploying Carapace with Docker Compose. For Kubernetes, see the [Helm chart README](../charts/carapace/README.md).

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
CARAPACE_TOKEN=pick-a-secret-bearer-token

# Optional — uncomment if needed
# GOOGLE_API_KEY=...
# CARAPACE_MATRIX_PASSWORD=...
# CARAPACE_GIT_TOKEN=...
```

`CARAPACE_TOKEN` is the bearer token that authenticates CLI, web UI, and Matrix connections to the server. Pick any random string.

## 2. Build and start

```bash
docker compose build
docker compose up -d
```

This starts:

- **Server** at `http://localhost:8321`
- **Frontend** at `http://localhost:3001`
- **Sandbox image** is built automatically

The web UI prompts for the server URL and token on first connect.

## 3. Connect via CLI (optional)

```bash
uv run carapace --token "$CARAPACE_TOKEN"
```

## 4. Configure `data/config.yaml`

The server reads its configuration from `data/config.yaml`. On first start, default files are seeded into `data/`. You can customise the config at any time — restart the server to pick up changes.

A minimal config:

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
  # New sessions start public by default. Set to true if you want explicit
  # opt-in before histories can be committed into the knowledge repo.
  default_private: false
  commit:
    enabled: true
    # Histories are written to data/knowledge/sessions/YYYY/MM/<session_id>/conversation.json
    path_prefix: sessions
    autosave_enabled: true
    autosave_inactivity_hours: 4
    # When true, deleting a session also removes its current committed snapshot from the knowledge repo.
    delete_from_knowledge_on_session_delete: true
```

Session histories always live primarily under `data/sessions/<session_id>/`. The `sessions.commit.*` settings control a secondary commit flow into the Git-backed knowledge repo so the agent can refer back to past conversations later.

In the web UI, public sessions expose a "Commit to knowledge" action. Private sessions do not. Autosave uses the same privacy rule: only public, inactive sessions are eligible.

## 5. Connect Matrix (optional)

Create a Matrix account for Carapace on your homeserver, then add to `data/config.yaml`:

```yaml
channels:
  matrix:
    enabled: true
    homeserver: https://matrix.example.com
    user_id: "@carapace:example.com"
    password:
      env: CARAPACE_MATRIX_PASSWORD
    allowed_rooms:
      - "!roomid:example.com"
    allowed_users:
      - "@you:example.com"
```

Set `CARAPACE_MATRIX_PASSWORD` in your `.env` and restart. Carapace will join the allowed rooms and respond to messages from allowed users. Sessions are created per-room.

`allowed_rooms` and `allowed_users` are mandatory — without them the bot ignores all messages. This prevents accidental exposure if someone invites the bot to a public room.

## 6. Set up credentials

Carapace can fetch credentials from a password manager on demand. The agent does not have blanket access — every credential request is evaluated by the sentinel agent and requires explicit user approval the first time it is used in a session. Credentials are intended to be consumed inside the sandbox (auto-injected via skill config or fetched with `ccred`) and must never be echoed or logged. Two backends are available.

### File backend (simple)

Create a `.env`-format secrets file:

```bash
echo "github-token=ghp_xxxxxxxxxxxx" > data/secrets.env
echo "smtp-password=myapppassword" >> data/secrets.env
```

Add to `data/config.yaml`:

```yaml
credentials:
  backends:
    dev:
      type: file
      # path defaults to <data_dir>/secrets.env
```

Credentials are accessible as `dev/github-token`, `dev/smtp-password`, etc.

### Bitwarden / Vaultwarden backend (optional)

This uses a `bw serve` sidecar container that shares the server's network namespace. Carapace never sees your vault credentials — they stay in the sidecar.

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

3. Add to `data/config.yaml`:

```yaml
credentials:
  backends:
    personal:
      type: bitwarden
      # url defaults to http://127.0.0.1:8087
```

Credentials are accessible by their Bitwarden UUID: `personal/9742101e-68b8-4a07-b5b1-...`. Look up UUIDs in the Bitwarden web UI or via `bw list items`.

### Exposure control

By default, all credentials in a backend are accessible (subject to sentinel + user approval). To restrict which credentials Carapace can see:

```yaml
credentials:
  backends:
    personal:
      type: bitwarden
      expose: # allowlist — only these UUIDs are accessible
        - "9742101e-68b8-4a07-b5b1-9578b5f88e6f"
        - "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
      # OR:
      # hide:  # blocklist — these UUIDs are excluded
      #   - "deadbeef-..."
```

## 7. Personalise

Edit the files in `data/` to shape Carapace's behaviour:

| File          | Purpose                                                   |
| ------------- | --------------------------------------------------------- |
| `SOUL.md`     | Agent personality and communication style                 |
| `USER.md`     | Information about you (name, preferences, context)        |
| `SECURITY.md` | Natural-language security policy (sentinel system prompt) |
| `AGENTS.md`   | Agent behavioural guide                                   |

## Next steps

- Install skills into `data/skills/` — see [docs/skills.md](skills.md)
- Explore the [architecture](architecture.md) and [security model](security.md)
- Deploy to Kubernetes with the [Helm chart](../charts/carapace/README.md)
