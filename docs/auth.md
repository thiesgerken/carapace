# Authentication

carapace uses file-backed users and HttpOnly session cookies for the web UI, CLI, REST, WebSocket API, and admin API. `CARAPACE_TOKEN` is only used as the initial password for the bootstrap `admin` user when no enabled admin user exists yet.

## Files

Auth state lives under `$CARAPACE_DATA_DIR/auth/`:

| File             | Purpose                                                                |
| ---------------- | ---------------------------------------------------------------------- |
| `users.yaml`     | Stable local users, password hashes, roles, and user config references |
| `sessions.yaml`  | Server-side session records used for logout and revocation             |
| `session_secret` | HMAC signing secret for browser/CLI session JWT cookies                |

One `users.yaml` entry looks like this:

```yaml
version: 1
users:
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
Per-user credential backend secrets are stored in `users.yaml`; API responses redact backend proxy passwords, and updates
that omit an existing proxy password keep the stored value.

## Creating Users

Set `CARAPACE_TOKEN` to a random bootstrap password in the server environment, then start the server. If `auth/users.yaml` does not contain any enabled user with the `admin` role, carapace creates an `admin` user with this password. The password must be at least 16 characters long. If it is missing or too short while the bootstrap user is needed, the server exits and prints a suggested 24-character replacement.

Log in as `admin` with that bootstrap password. In **Settings**, admin users see an **Admin** group with a **Users** tab. There is no standalone admin portal; user management lives inside Settings. The users panel can create users, edit passwords and profile fields, enable or disable users, and assign existing single-user data to a selected user.

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

`POST /api/auth/login` verifies the password, creates a server-side session in `auth/sessions.yaml`, and sets the `carapace_session` HttpOnly cookie. The cookie contains a signed JWT with the username, session id, expiry, and token version. The server still checks the session file and user record on every request, so logout and disabled users take effect without waiting for cookie expiry.

`POST /api/auth/logout` revokes the server-side session and deletes the cookie.

Changing a password increments `token_version`, which invalidates older cookies for that user.

## Owned Data

User ownership is stored close to existing runtime files instead of changing the main directory structure:

- `sessions/<session_id>/meta.yaml` contains `user: <username>`.
- `jobs.yaml` job entries contain `user: <username>`.
- notification subscription YAML files contain `user: <username>`.

Records without an owner are invalid in the current data model.
