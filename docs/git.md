# Git Integration

Carapace manages a **knowledge repository** — a Git repo containing the security policy, memory files, skills, and any other files the agent works with. The repo lives on the server at `$CARAPACE_DATA_DIR/knowledge/` and is cloned into every sandbox container at `/workspace`.

Optionally, you can connect an **upstream remote** so the knowledge repo is synchronised with an external Git server (GitHub, Gitea, GitLab, etc.).

## Configuration

Add a `git` section to your `config.yaml`:

```yaml
git:
  remote: https://gitea.example.com/team/knowledge.git
  branch: main
  token:
    env: CARAPACE_GIT_TOKEN
```

| Field    | Default                                     | Description                                                                                                                            |
| -------- | ------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| `remote` | `""` (none)                                 | URL of the upstream Git remote. Leave empty for local-only mode.                                                                       |
| `branch` | `"main"`                                    | Remote branch to fetch from and push to. **Must already exist on the remote.** The local knowledge repo always uses `main` internally. |
| `author` | `"Carapace Session %s <%s@carapace.local>"` | Commit author template. `%s` is replaced with the session ID.                                                                          |
| `token`  | `null`                                      | Authentication token for the remote (see below).                                                                                       |

### Authentication

The `token` field accepts three forms via the `Secret` model:

```yaml
# Read from an environment variable (recommended)
token:
  env: CARAPACE_GIT_TOKEN

# Read from a file
token:
  file: /run/secrets/git-token

# Inline value (not recommended for production)
token:
  raw: ghp_xxxxxxxxxxxx
```

The token is embedded as `x-access-token:<token>` in the remote URL for HTTPS authentication. If no token is configured, the remote is added without credentials (suitable for public repos or SSH URLs).

## Remote branch

The `branch` setting in the git config refers exclusively to the **remote** branch. The `branch` setting controls which **remote** branch Carapace fetches from and pushes to. It does **not** affect the local knowledge repo, which always uses a `main` branch internally. This means you can point Carapace at any branch on the remote (e.g. `dev`, `production`) without changing how sandboxes or the agent interact with the repo locally.

The configured branch **must already exist** on the upstream remote before Carapace connects to it. Carapace does not create remote branches — it performs `git fetch origin <branch>` and `git merge --ff-only origin/<branch>`, both of which fail if the branch doesn't exist.

If you're starting from scratch:

1. Create the remote repository and its default branch (most hosting providers do this automatically).
2. Set `branch` in `config.yaml` to match the remote branch you want to use (e.g. `main`, `dev`).
3. Start Carapace — it will push the initial bootstrap commit to that branch.

## What happens on first start

When the server starts with a remote configured:

1. **Initialise local repo.** If `$CARAPACE_DATA_DIR/knowledge/` has no `.git` directory, `git init -b main` creates one. The local branch is always `main`, regardless of the `branch` setting.
2. **Add remote.** The upstream URL is registered as `origin` (or updated if it already exists).
3. **Pull.** Carapace fetches from the remote and syncs the local branch. If the local repo is empty (fresh init) and the remote has content, it adopts the remote branch directly (`git reset --hard`). If the local repo already has commits, it does a fast-forward merge. If the remote branch is also empty, this step is a no-op.
4. **Bootstrap.** Default knowledge files (`SECURITY.md`, `SOUL.md`, `USER.md`, `memory/CORE.md`, example skills) are seeded **only if they don't already exist** — files pulled from the remote are not overwritten.
5. **Commit & push.** If the bootstrap created any new files, they are committed and pushed to the remote.

On subsequent server restarts the same sequence runs, but typically only step 3 (pull) has any effect, keeping the server in sync with upstream changes.

If the pull encounters a merge conflict (i.e. local and remote have diverged and a fast-forward is not possible), the server **exits with an error**. You'll need to resolve the conflict manually inside the `knowledge/` directory and restart.

## Adding a remote to an existing instance

If you've been running Carapace without a remote and later add `git.remote` to the config:

1. **Restart the server.** On startup it registers the remote, pulls (fast-forward only), and pushes any local-only commits upstream.
2. **Running sessions are unaffected.** Their sandboxes already have a `/workspace` clone from before the remote was added. They continue working normally — agent pushes go to the server's local knowledge repo.
3. **New sessions** will clone a workspace that includes the remote content.
4. To explicitly sync a running session, use the `/pull` slash command.

## Sandbox Git workflow

Every session gets its own **sandbox container** with a clone of the knowledge repo at `/workspace`. The clone uses the server's built-in Git HTTP backend — sandboxes never talk to the upstream remote directly.

```
┌───────────────────┐     git push/pull      ┌────────────────┐    git push     ┌──────────────┐
│  Sandbox          │ ◄──────────────────────►│  Carapace      │ ──────────────► │  Upstream     │
│  /workspace       │    (HTTP Smart Proto)   │  knowledge/    │   (on success)  │  Remote       │
└───────────────────┘                         └────────────────┘                 └──────────────┘
```

1. **Clone on creation.** When a sandbox starts, `git clone $GIT_REPO_URL /workspace` pulls the latest state from the server. If the workspace already exists (e.g. Kubernetes PVC from a previous run), the clone is skipped.
2. **Agent commits & pushes.** The agent can run `git add`, `git commit`, and `git push` inside the sandbox. Pushes go to the server's Git HTTP backend.
3. **Security gate.** Every push triggers a **pre-receive hook** that sends the full diff to the sentinel agent for evaluation. The sentinel can allow or deny the push based on the security policy.
4. **Upstream propagation.** If the push is accepted _and_ an upstream remote is configured, the server automatically pushes to the external remote.

### Git identity

Commits made inside a sandbox use a per-session identity derived from the `author` template:

```
Carapace Session <session-id> <session-id@carapace.local>
```

This makes it easy to trace which session produced which commit in the upstream history.

## Slash commands

| Command   | Description                                                                                                                                                                          |
| --------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `/pull`   | Fetch and fast-forward merge from the upstream remote into the server's knowledge repo. Re-scans skills afterwards. Fails if no remote is configured or if there's a merge conflict. |
| `/push`   | Push the server's knowledge repo to the upstream remote. Fails if no remote is configured.                                                                                           |
| `/reload` | Destroy the session's sandbox and re-create it on the next command. The new sandbox gets a fresh clone, picking up any changes that were pulled or pushed since the session started. |

## Local-only mode

If `git.remote` is not set (or is an empty string), Carapace runs in local-only mode:

- The knowledge repo is still Git-backed (for the sandbox clone workflow and security-gated pushes).
- `/pull` and `/push` return "No external remote configured."
- No upstream synchronisation occurs.
