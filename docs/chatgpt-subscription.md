# ChatGPT Subscription Models

carapace can run models on a user's own ChatGPT subscription instead of a platform API key. It uses Pydantic AI's [`openai-codex` provider](https://pydantic.dev/docs/ai/models/openai-codex/), which talks to the Codex backend with the OAuth credentials of a ChatGPT login. Every user connects their own subscription; requests in a session always use the credentials of the session owner.

## Admin setup

Register Codex models in the catalog under **Settings** -> **Admin** -> **Platform** like any other provider, with provider `openai-codex`:

```yaml
agent:
  available_models:
    - "openai-codex:gpt-5.5"
```

`openai-codex` rows take no `api_key` or `base_url`. They may be used as platform defaults (agent, sentinel, title, compaction). Saving the platform settings does not need a connected subscription: building a Codex model loads no credentials, they are read on the first request.

A user who selects a Codex model (or inherits it as a default) without having connected a subscription gets an error on the first request telling them to connect ChatGPT in Settings.

## Connecting a subscription

Each user connects under **Settings** -> **Account** -> **ChatGPT subscription**:

1. **Connect ChatGPT** starts a login and shows a link to OpenAI's authorize page.
2. The user opens it and signs in to ChatGPT.
3. OpenAI redirects the browser to `http://localhost:1455/auth/callback?code=...&state=...`. That page fails to load, which is expected.
4. The user copies the full URL from the address bar, pastes it into the settings field and clicks **Complete login**. The server exchanges the code for tokens and stores them.

The section then shows the connected account email. **Reconnect** runs the login again (for example after the grant was revoked), **Disconnect** deletes the stored tokens.

### Why the paste step

The public Codex OAuth client only accepts the redirect URI `http://localhost:1455/auth/callback`, and OpenAI offers no device flow. On a laptop the Codex CLI listens on that port; a carapace server running in Kubernetes (or anywhere other than the user's machine) cannot receive the callback. The authorization code still ends up in the URL of the failed localhost page, so pasting that URL back hands the server everything it needs. The login is protected by PKCE and a `state` value that is bound to the user who started it; a pasted URL from another user's or an older login attempt is rejected. A started login expires after 10 minutes and lives in server memory, which is fine for the single-replica server deployment.

### Do not import `~/.codex/auth.json`

Connect through the settings flow instead of copying the Codex CLI's `~/.codex/auth.json` from a laptop. Refresh tokens are single-use and rotate on every refresh. If the laptop's Codex CLI and carapace share one grant, whichever refreshes first invalidates the other's refresh token and logs it out. A separate login gives carapace its own grant.

## Storage and token refresh

Credentials live in the database table `user_codex_credentials` (one row per user, deleted together with the user): access token, refresh token, ChatGPT account id, the account email for display, and the last update time. Like model API keys configured on catalog rows, the tokens are stored unencrypted, so protect database access and backups accordingly.

The table is separate from the user settings on purpose: settings saves rewrite the whole user config, which could overwrite a refresh token that rotated in the meantime.

The provider refreshes the access token when it expires and writes the rotated tokens back to the row. All Codex models of a user share one provider instance in the server, so refreshes for a user never run concurrently and cannot spend the same refresh token twice. A refresh never recreates a row that a disconnect removed.

The server needs outbound HTTPS access to `auth.openai.com` and `chatgpt.com`.

## Usage and cost

Codex requests count against the user's ChatGPT subscription limits, not an API bill. carapace still shows the equivalent OpenAI API price in usage and cost figures (Codex models are priced like the same model on the `openai` provider), and session cost budgets apply to that equivalent price.

## API

All routes require the `preferences` scope (`read` for the status, `write` otherwise) and act on the authenticated user.

| Route                            | Method   | Purpose                                                                |
| -------------------------------- | -------- | ---------------------------------------------------------------------- |
| `/api/user/codex`                | `GET`    | Connection status: `connected`, `email`, `updated_at`                  |
| `/api/user/codex/login`          | `POST`   | Start a login; returns `authorize_url`                                 |
| `/api/user/codex/login/complete` | `POST`   | Body `{"redirect_url": "..."}`; exchanges the code, returns the status |
| `/api/user/codex`                | `DELETE` | Disconnect (404 when nothing is connected)                             |
