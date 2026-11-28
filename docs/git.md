# Git Integration

carapace manages one Git-backed knowledge repo per user. Each repo contains that user's `SECURITY.md`, workspace files, skills, archived session snapshots, and other durable files the agent works with. With the default layout, the repo for user `alice` lives at `$CARAPACE_DATA_DIR/knowledges/alice/`. Sandboxes clone the repo that matches the session owner into `/workspace`.

Each user can optionally connect an upstream remote so their knowledge repo is synchronized with an external Git server such as GitHub, Gitea, or GitLab. Remote settings are isolated per owner: one user's remote, branch, token, and author template do not affect any other user's repo.

## Configuration

Each user's remote settings are a `git` object in their user config (shown as YAML):

```yaml
git:
  remote: https://gitea.example.com/team/alice-knowledge.git
  branch: main
  token: ghp_xxxxxxxxxxxx
```

The owning user edits them under Settings -> Account, which saves through `PATCH /api/user/settings` (body `{"git": {...}}`). An admin can set them for any user with `PATCH /api/admin/users/{username}` (body `{"config": {"git": {...}}}`). The token field is write-only: responses report `token_set`, but never return the token value.

| Field    | Default                    | Description                                                                                                                                                                             |
| -------- | -------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `remote` | `""` (none)                | URL of the upstream remote for this user's repo. Leave empty for local-only mode.                                                                                                       |
| `branch` | `"main"`                   | Remote branch to fetch from and push to. **Must already exist on the remote.** The local repo still uses `main` internally.                                                             |
| `author` | `"carapace <carapace@%h>"` | Commit author template for this user's repo. `%s` is replaced with the session ID, `%h` with the name of the host that commits: the server, or the session's sandbox for agent commits. |
| `token`  | `null`                     | Authentication token for the remote (see below).                                                                                                                                        |

### Authentication

The `token` field accepts a literal token string:

```yaml
token: ghp_xxxxxxxxxxxx
```

It does not support `env` or `file` indirection. Git remote credentials belong to the configured user and must not let user-owned config read arbitrary server environment variables or files.

The token is embedded as `x-access-token:<token>` in the remote URL for HTTPS authentication. If no token is configured, the remote is added without credentials, which is suitable for public repos or SSH URLs.

The [skill builder](builder.md#fetch-credentials) fetches the user's skill inputs with the same token, for the remote's host only, so skills can come from private repositories on that forge ([sharing skills](sharing-skills.md#private-repositories)). That needs an HTTPS remote.

## Remote branch

The `branch` setting refers exclusively to the remote branch for that user's repo. It controls which remote branch carapace fetches from and pushes to. It does not change the local branch name, which remains `main` internally. This means a user can point carapace at any existing remote branch such as `main`, `dev`, or `production` without changing how sandboxes or the agent interact with the repo locally.

The configured branch must already exist on the upstream remote before carapace connects to it. carapace does not create remote branches. It performs `git fetch origin <branch>` and then fast-forwards local state to `origin/<branch>`.

## What happens on startup

For every enabled user, startup runs the same sequence against that user's repo:

1. Initialize or open the local repo at `$CARAPACE_DATA_DIR/knowledges/<normalized-user>/`.
2. If `config.git.remote` is set, add or update the `origin` remote for that repo.
3. Pull the configured remote branch before any bootstrap seeding.
4. Seed default files such as `SECURITY.md`, `SOUL.md`, `USER.md`, and bundled skills only if they are still missing.
5. If bootstrap created new files, commit them and push them to that user's remote.

Users without a remote still get a local Git-backed repo. They skip the remote add, pull, and upstream push steps.

If the pull fails (unreachable remote, bad credentials, or a pull that would need a non-fast-forward merge), carapace logs the error and keeps serving that user's local repo as it is, skipping steps 4 and 5. It never guesses how to reconcile local and remote state, and one user's broken remote does not keep the server from starting. Seeding is skipped because a seed commit on a repo that never adopted the remote branch would fork its history. Once the remote is fixed, sync with **Pull** in the knowledge remote panel (`POST /api/git/pull`); a restart also seeds anything still missing.

## Adding or changing a remote on an existing instance

If you add or change a user's `git` settings while the server is running (Settings -> Account through `PATCH /api/user/settings`, or an admin through `PATCH /api/admin/users/{username}`):

1. Saving applies them right away to that user's repo only: carapace registers the new remote (or removes it), pulls the configured branch, and reapplies the Git identity in that user's running sandboxes. If this fails, the save is rejected and the previous settings stay in place. A save through the admin API also seeds missing bootstrap files and pushes them.
2. Running sandboxes are not hot-migrated. They keep the clone they already have.
3. New sessions for that user clone the refreshed repo.
4. To sync an existing sandbox with the server repo, use **Pull** in the session's workspace sync controls, or `/reload` for a fresh clone.

## Sandbox Git workflow

Every session gets its own sandbox container with a clone of the owning user's repo at `/workspace`. The clone uses the server's built-in Git HTTP backend. Sandboxes never talk to the upstream remote directly.

```text
Sandbox /workspace  <->  carapace /git/<owner>  <->  owner's upstream remote
```

1. Clone on creation. When a sandbox starts, `git clone $GIT_REPO_URL /workspace` pulls the latest state for the session owner from the server.
2. Agent commits and pushes. The agent can run `git add`, `git commit`, and `git push` inside the sandbox. Pushes go to the server's Git HTTP backend.
3. Owner validation. The Git HTTP backend validates that the session token may only access the repo for that session's owner and rejects cross-user paths.
4. Security gate. Every push from a sandbox triggers a pre-receive hook that sends the full diff to the sentinel agent for evaluation, together with both sides of every `flake.lock` it changes. The server renders those as one line per changed flake input for the sentinel (see [security.md](security.md#git-push-evaluation)). The hook has to send the contents itself: the incoming objects are only visible inside the hook until the push is accepted.
   Commits the server makes in the repo directly are not pushes and skip it: session archives, the memory mirror, and what a user does in the UI, such as [applying a skill update](skills.md#updates). They do not come from the agent.
5. Upstream propagation. If the push is accepted and that user has an upstream remote configured, the server pushes only that user's repo upstream.

The pre-receive hook uses the server's Python interpreter and standard library, plus Git. It does not require a shell, `jq`, or `curl`. Startup rewrites the hook with the current interpreter path so image updates cannot leave a stale shebang. Sentinel connections have a 10-second connect timeout and no read timeout, since user approval can take arbitrarily long. An unreachable sentinel or a hook invocation with no refs rejects the push.

The standalone source lives in `src/carapace/git/pre_receive.py` and must not import the carapace package. It connects directly to the loopback sentinel API without proxy lookup or redirects and requires an HTTP 200 response before inspecting the verdict.

### Git identity

Commits made inside a sandbox use an identity filled from the owning user's `author` template, with `%h` set to the sandbox's hostname (the short container id on Docker, the pod name on Kubernetes) and `%s` to the session ID. With the default template that is:

```text
carapace <carapace@<sandbox-hostname>>
```

A `commit-msg` hook in `/workspace` also appends a `carapace-session: <session-id>` trailer to every commit, so the repo history shows which session produced which commit.

The identity is set as global git config in the sandbox, so it also applies to other repos the agent clones. It is reapplied whenever the sandbox runtime may be fresh (create, warm-pool claim, resume, or recovery after the container restarted), because `~/.gitconfig` does not survive a container restart.

## Syncing from the UI and API

The web UI has two Git sync panels with refresh, pull, and push buttons: **Workspace sync** in the chat view and **Knowledge remote** on the knowledge page. They call these endpoints:

| Endpoint                                      | Method | Description                                                                               |
| --------------------------------------------- | ------ | ----------------------------------------------------------------------------------------- |
| `/api/sessions/{session_id}/sandbox/git`      | `GET`  | Ahead/behind status of the sandbox `/workspace` clone against the owner's server repo.    |
| `/api/sessions/{session_id}/sandbox/git/pull` | `POST` | Fast-forward pull from the server repo into the sandbox clone.                            |
| `/api/sessions/{session_id}/sandbox/git/push` | `POST` | Push the sandbox clone to the server repo. Goes through the sentinel like any agent push. |
| `/api/git/status`                             | `GET`  | Ahead/behind status of the user's server repo against their upstream remote.              |
| `/api/git/pull`                               | `POST` | Fetch and fast-forward merge from the user's upstream remote into their server repo.      |
| `/api/git/push`                               | `POST` | Push the user's server repo to their upstream remote. Fails if no remote is configured.   |

The `/reload` slash command destroys the session's sandbox and re-creates it on the next command. The new sandbox reclones the same owner's repo and picks up any changes pulled or pushed.

## Local-only mode

If a user has no `config.git.remote` set, that user still gets a local Git-backed repo for sandbox clones and security-gated pushes.

- Pulling from or pushing to the upstream remote (`/api/git/pull`, `/api/git/push`) reports that no external remote is configured.
- Another user's remote does not change this user's behavior.
- Users with a remote and users without one can coexist on the same server without conflict.
