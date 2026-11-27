# Authentication

carapace uses database-backed users and HttpOnly session cookies for the web UI, CLI, REST, WebSocket API, and admin API. Scripts and integrations can use [API keys](#api-keys) instead. `CARAPACE_TOKEN` is only used as the initial password for the bootstrap `admin` user when no enabled admin user exists yet.

## Storage

Auth state lives in the database (`CARAPACE_DATABASE_URL`) and one file:

| Location                                 | Purpose                                                           |
| ---------------------------------------- | ----------------------------------------------------------------- |
| `users` table                            | Stable local users, password hashes, roles, and per-user `config` |
| `auth_sessions` table                    | Server-side session records used for logout and revocation        |
| `$CARAPACE_DATA_DIR/auth/session_secret` | HMAC signing secret for browser/CLI session JWT cookies           |

One user row looks like this (shown as YAML):

```yaml
alice:
  password_hash: "$argon2id$v=19$..."
  enabled: true
  token_version: 1
  display_name: Alice
  email: alice@example.com
  roles: []
  created_at: "2026-05-24T12:00:00Z"
  updated_at: "2026-05-24T12:00:00Z"
  password_changed_at: "2026-05-24T12:00:00Z"
  last_login_at: null
  config:
    credentials:
      backends:
        vault:
          type: bitwarden
          url: http://carapace-bitwarden:8087
          basic_auth:
            username: alice
            password: user-specific-random-proxy-password
    channels:
      matrix:
        enabled: false
    git: {}
    default_models:
      agent: anthropic:claude-sonnet-4-6
      sentinel: anthropic:claude-haiku-5-5
      title: anthropic:claude-haiku-5-5
    budgets: {}
```

Usernames are normalized to lowercase and should be stable, hand-picked names for the self-hosted users of an instance.
Per-user credential backend secrets are stored in the user's `config` column; API responses redact backend proxy passwords, and updates
that omit an existing proxy password keep the stored value.

## Creating Users

Set `CARAPACE_TOKEN` to a random bootstrap password in the server environment, then start the server. If the database does not contain any enabled user with the `admin` role, carapace creates an `admin` user with this password. The password must be at least 16 characters long. If it is missing or too short while the bootstrap user is needed, the server exits and prints a suggested 24-character replacement.

Log in as `admin` with that bootstrap password. In **Settings**, admin users see an **Admin** group with a **Users** tab. There is no standalone admin portal; user management lives inside Settings. The users panel can create users, edit passwords, profile fields, and roles, enable or disable users, and delete users.

You can also create users through the admin API after logging in and storing the session cookie:

```bash
curl -c carapace.cookies -X POST http://localhost:8321/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"'"$CARAPACE_TOKEN"'"}'

curl -X POST http://localhost:8321/api/admin/users \
  -b carapace.cookies \
  -H "Content-Type: application/json" \
  -d '{"username":"alice","password":"change-me","display_name":"Alice"}'
```

The web UI logs in with username and password. The CLI does the same:

```bash
uv run carapace --user alice --password change-me
```

You can also set `CARAPACE_USER` and `CARAPACE_PASSWORD` for the CLI.

## Session Cookies

`POST /api/auth/login` verifies the password, creates a server-side session in the `auth_sessions` table, and sets the `carapace_session` HttpOnly cookie. The cookie contains a signed JWT with the username, session id, expiry, and token version. The server still checks the session record and user record on every request, so logout and disabled users take effect without waiting for cookie expiry.

`POST /api/auth/logout` revokes the server-side session and deletes the cookie.

Changing a password increments `token_version`, which invalidates older cookies for that user.

## API Keys

Each user can create API keys under **Settings** -> **API Keys** (or `POST /api/keys`). The secret is shown once. Clients send it as `Authorization: Bearer <key>`, the CLI takes it with `--api-key` or `CARAPACE_API_KEY`, and the WebSocket accepts it as the `api_key` query parameter. Keys live in the `api_keys` table as hashes and are deleted together with their user.

A key carries scopes of the form `<scope>:<access>` (`sessions`, `jobs`, `preferences`, `notifications`, `history`, `knowledge`, `admin`; `read` or `write`, where `write` includes `read`) and an optional expiry. Cookie sessions are not scope-limited. The `admin` scope additionally requires the owner's `admin` role.

## Owned Data

User ownership is a `user` column on the owned database records:

- `sessions` rows contain `user: <username>`.
- `jobs` rows contain `user: <username>`.
- `notification_subscriptions` rows contain `user: <username>`.

Records without an owner are invalid in the current data model.
