# Git Integration

carapace manages one Git-backed knowledge repo per user. Each repo contains that user's `SECURITY.md`, workspace files, skills, archived session snapshots, and other durable files the agent works with. With the default layout, the repo for user `alice` lives at `$CARAPACE_DATA_DIR/knowledges/alice/`. Sandboxes clone the repo that matches the session owner into `/workspace`.

Each user can optionally connect an upstream remote so their knowledge repo is synchronized with an external Git server such as GitHub, Gitea, or GitLab. Remote settings are isolated per owner: one user's remote, branch, token, and author template do not affect any other user's repo.

## Configuration

Add a `git` section to the owning user record in `$CARAPACE_DATA_DIR/auth/users.yaml`:

```yaml
users:
  alice:
    config:
      git:
        remote: https://gitea.example.com/team/alice-knowledge.git
        branch: main
        token: ghp_xxxxxxxxxxxx
```

The owning user can also manage these fields from the web UI under Settings -> Account. The token field is write-only: responses report `token_set`, but never return the token value.

| Field    | Default                    | Description                                                                                                                 |
| -------- | -------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| `remote` | `""` (none)                | URL of the upstream remote for this user's repo. Leave empty for local-only mode.                                           |
| `branch` | `"main"`                   | Remote branch to fetch from and push to. **Must already exist on the remote.** The local repo still uses `main` internally. |
| `author` | `"carapace <carapace@%h>"` | Commit author template for this user's repo. `%s` is replaced with the session ID, `%h` with the hostname.                  |
| `token`  | `null`                     | Authentication token for the remote (see below).                                                                            |

### Authentication

The `token` field accepts a literal token string:

```yaml
token: ghp_xxxxxxxxxxxx
```

It does not support `env` or `file` indirection. Git remote credentials belong to the configured user and must not let user-owned config read arbitrary server environment variables or files.

The token is embedded as `x-access-token:<token>` in the remote URL for HTTPS authentication. If no token is configured, the remote is added without credentials, which is suitable for public repos or SSH URLs.

## Remote branch

The `branch` setting refers exclusively to the remote branch for that user's repo. It controls which remote branch carapace fetches from and pushes to. It does not change the local branch name, which remains `main` internally. This means a user can point carapace at any existing remote branch such as `main`, `dev`, or `production` without changing how sandboxes or the agent interact with the repo locally.

The configured branch must already exist on the upstream remote before carapace connects to it. carapace does not create remote branches. It performs `git fetch origin <branch>` and then fast-forwards local state to `origin/<branch>`.

## What happens on startup

For every enabled user, startup runs the same sequence against that user's repo:

1. Initialize or open the local repo at `$CARAPACE_DATA_DIR/knowledges/<normalized-user>/`.
2. If `config.git.remote` is set, add or update the `origin` remote for that repo.
3. Pull the configured remote branch before any bootstrap seeding.
4. Seed default files such as `SECURITY.md`, `SOUL.md`, `USER.md`, and bundled example skills only if they are still missing.
5. If bootstrap created new files, commit them and push them to that user's remote.

Users without a remote still get a local Git-backed repo. They skip the remote add, pull, and upstream push steps.

If a pull would require a non-fast-forward merge, startup fails loudly instead of guessing how to reconcile local and remote state.

## Adding or changing a remote on an existing instance

If you add or change `config.git.remote` for a user after the server is already running:

1. Restart the server. Startup reinitializes only that user's repo runtime, registers the new remote, pulls, and pushes any new bootstrap files if needed.
2. Running sandboxes are not hot-migrated. They keep the clone they already have.
3. New sessions for that user clone the refreshed repo.
4. To explicitly sync an existing sandbox, use the `/pull` slash command inside one of that user's sessions.

## Sandbox Git workflow

Every session gets its own sandbox container with a clone of the owning user's repo at `/workspace`. The clone uses the server's built-in Git HTTP backend. Sandboxes never talk to the upstream remote directly.

```text
Sandbox /workspace  <->  carapace /git/<owner>  <->  owner's upstream remote
```

1. Clone on creation. When a sandbox starts, `git clone $GIT_REPO_URL /workspace` pulls the latest state for the session owner from the server.
2. Agent commits and pushes. The agent can run `git add`, `git commit`, and `git push` inside the sandbox. Pushes go to the server's Git HTTP backend.
3. Owner validation. The Git HTTP backend validates that the session token may only access the repo for that session's owner and rejects cross-user paths.
4. Security gate. Every push triggers a pre-receive hook that sends the full diff to the sentinel agent for evaluation.
5. Upstream propagation. If the push is accepted and that user has an upstream remote configured, the server pushes only that user's repo upstream.

The pre-receive hook uses the server's Python interpreter and standard library, plus Git. It does not require a shell, `jq`, or `curl`. Startup rewrites the hook with the current interpreter path so image updates cannot leave a stale shebang. Sentinel connections have a 10-second connect timeout and no read timeout, since user approval can take arbitrarily long. An unreachable sentinel or a hook invocation with no refs rejects the push.

The standalone source lives in `src/carapace/git/pre_receive.py` and must not import the carapace package. It connects directly to the loopback sentinel API without proxy lookup or redirects and requires an HTTP 200 response before inspecting the verdict.

### Git identity

Commits made inside a sandbox use a per-session identity derived from the owning user's `author` template:

```text
carapace Session <session-id> <session-id@carapace.local>
```

This makes it easy to trace which session produced which commit in the repo history.

## Slash commands

| Command   | Description                                                                                                                                                   |
| --------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `/pull`   | Fetch and fast-forward merge from the session owner's upstream remote into that user's server repo. Re-scans that user's skills afterwards.                   |
| `/push`   | Push the session owner's server repo to that user's upstream remote. Fails if no remote is configured.                                                        |
| `/reload` | Destroy the session's sandbox and re-create it on the next command. The new sandbox reclones the same owner's repo and picks up any changes pulled or pushed. |

## Local-only mode

If a user has no `config.git.remote` set, that user still gets a local Git-backed repo for sandbox clones and security-gated pushes.

- `/pull` and `/push` in that user's sessions report that no external remote is configured.
- Another user's remote does not change this user's behavior.
- Users with a remote and users without one can coexist on the same server without conflict.
