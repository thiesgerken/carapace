# CHANGELOG


## v0.42.6 (2026-03-28)


### 🐛 Bug Fixes


- 🐛 add revisionHistoryLimit to frontend and server deployments
  ([`1c73b40`](https://github.com/thiesgerken/carapace/commit/1c73b40b532f149a608596b86e710674fd60fdd7))

## v0.42.5 (2026-03-28)


### 🐛 Bug Fixes


- 🐛 fix: add safe.directory for /workspace in sandbox image
  ([`299e504`](https://github.com/thiesgerken/carapace/commit/299e504ad2a5d6fbbeca0c985275f231e7717acc))

  Git 2.35.2+ rejects operations when the repo owner differs from the current user.  The sandbox runs as root while the PVC workspace dir is owned by UID 999 (server fsGroup), triggering the dubious-ownership error on every git command.

## v0.42.4 (2026-03-27)


### 🐛 Bug Fixes


- 🐛 fix: run sandbox containers as root for package installs
  ([`b75b837`](https://github.com/thiesgerken/carapace/commit/b75b837d49db87ace67c3a98882921d89bd42381))

  Remove run_as_non_root / run_as_user=1000 from the K8s sandbox pod security context so the container can write to /etc/apt, /etc/pip and run apt-get install.  Privilege escalation and all capabilities remain blocked.  Revert setup-proxy.sh to the simpler root-level config writes.

## v0.42.3 (2026-03-27)


### Other


- Revert "♻️ refactor: defer version commit until after Docker builds succeed"
  ([`5030c00`](https://github.com/thiesgerken/carapace/commit/5030c00d16ff068790af1ee6fbe58186c8ca56ec))

  This reverts commit 2bbc75f069436678dbf3d5d0d34b6ec8f44d8e1c.

- Revert "🐛 fix: disable semantic-release build to avoid dist/ permission error"
  ([`57f2a1e`](https://github.com/thiesgerken/carapace/commit/57f2a1e1654b48e5d11e018fd5287328cad99e31))

  This reverts commit 4cd229b266c73d7e957ee460ab6421a22f07ad48.

- Revert "🐛 fix: stamp version into pyproject.toml before backend Docker build"
  ([`1a7141a`](https://github.com/thiesgerken/carapace/commit/1a7141a17d4d4955fc471e1c89f7e61ddcd1666b))

  This reverts commit 0cc7f973370826938d4f4a7aff003d93d86383e0.

- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`53e6959`](https://github.com/thiesgerken/carapace/commit/53e6959274274b447591a43452870f3e0c349554))

## v0.42.2 (2026-03-26)


### 🐛 Bug Fixes


- 🐛 fix: stamp version into pyproject.toml before backend Docker build
  ([`0cc7f97`](https://github.com/thiesgerken/carapace/commit/0cc7f973370826938d4f4a7aff003d93d86383e0))

- 🐛 fix: disable semantic-release build to avoid dist/ permission error
  ([`4cd229b`](https://github.com/thiesgerken/carapace/commit/4cd229b266c73d7e957ee460ab6421a22f07ad48))

  semantic-release's default build writes to dist/ before uv build, causing a PermissionError on overwrite. Disable it since we build explicitly with uv build.

## v0.42.1 (2026-03-26)


### 🐛 Bug Fixes


- 🐛 fix: set fsGroup in server pod for PVC write access
  ([`68244d2`](https://github.com/thiesgerken/carapace/commit/68244d24b230a806b50056eabbfd5a040e2e4851))

  The nonroot user (UID/GID 999) cannot create directories on a freshly mounted PVC owned by root. Adding fsGroup: 999 to the pod security context lets Kubernetes chown mounted volumes to the correct group.

### ♻️ Refactoring


- ♻️ refactor: defer version commit until after Docker builds succeed
  ([`2bbc75f`](https://github.com/thiesgerken/carapace/commit/2bbc75f069436678dbf3d5d0d34b6ec8f44d8e1c))

  Move semantic-release version commit + tag from the first job to the publish step so that if any Docker build fails, no version commit is created. The version job now only computes the next version.

## v0.42.0 (2026-03-26)


### ✨ Features


- ✨Merge pull request #52 from thiesgerken/feat/git-knowledge-store
  ([`086ba39`](https://github.com/thiesgerken/carapace/commit/086ba39cc4301b87b8fbaf1cb2193b6a56c8b301))

  ✨ feat: git-backed knowledge store

- ✨ feat: dedicated GitPushApprovalRequest with changed files and sentinel explanation
  ([`c8f7d6c`](https://github.com/thiesgerken/carapace/commit/c8f7d6c53233d584b3d3a3295563819aa1dc3343))

  - Split git push escalation out of ProxyApprovalRequest into its own
    GitPushApprovalRequest WS model (ref, explanation, changed_files)
  - New GitPushApprovalCard frontend component with collapsible file list
  - Rename ProxyApprovalResponse → EscalationResponse (shared escalation
    response for both proxy domain and git push)
  - Rename proxy_approval_queue → escalation_queue,
    pending_proxy_approvals → pending_escalations,
    _make_domain_escalation_cb → _make_escalation_cb
  - Extract changed file names from unified diff in evaluate_push_with

- ✨ feat: sentinel push evaluation with UI notifications and escalation
  ([`8062d71`](https://github.com/thiesgerken/carapace/commit/8062d717df3681243d0408170bceb3330e1c1f6b))

  - Add GitPushEntry to action log and 'git_push' kind to audit log.
  - Add evaluate_push_with() security gate (allow/deny/escalate) for
    git pushes, analogous to evaluate_domain_with().
  - Broadcast push decisions to all session subscribers via
    on_git_push_info callback.
  - Add 'kind' field to ProxyApprovalRequest so escalated git pushes
    render as 'Git Push Request' in frontend, CLI, and Matrix.
  - Update docs/security.md and docs/sessions-and-channels.md.

- ✨ feat: auto-push to remote after sandbox push & /push slash command
  ([`060b3b4`](https://github.com/thiesgerken/carapace/commit/060b3b484c1ad5dd84ed96787558caacf0192f3e))

  - Make on_push_success callback async and wire git_store.push_to_remote
    when an external remote is configured.
  - Add /push slash command to manually trigger a push to the remote.

- ✨ feat: set git identity in sandbox containers
  ([`d2cff63`](https://github.com/thiesgerken/carapace/commit/d2cff631f4f03d095de13b74b2383886e9b7edd0))

  Pass GIT_AUTHOR_NAME, GIT_COMMITTER_NAME, GIT_AUTHOR_EMAIL and GIT_COMMITTER_EMAIL env vars so the agent can commit and push without first running git config.  The identity is derived from the configurable git.author template (default: 'Carapace Session %s <%s@carapace.local>').

- ✨ feat: add workdir parameter to ContainerRuntime.exec
  ([`e46d1fc`](https://github.com/thiesgerken/carapace/commit/e46d1fc03154826ba7d9615c663d8abf929d6dcd))

  Docker passes it natively to exec_run(); Kubernetes prepends 'cd <dir> &&' since its exec API has no workdir support.

  exec_command and skill venv sync now use workdir=/workspace/knowledge so the agent's cwd is the knowledge repo clone.

- ✨ feat: log container tail on sandbox recreation for troubleshooting
  ([`fd18303`](https://github.com/thiesgerken/carapace/commit/fd183039f66f8a8fe455a7f445b40d22a4d9dda0))

  When a sandbox container is detected as stopped or gone, fetch and log the last 40 lines of its output before spinning up a replacement. Adds a logs() method to the ContainerRuntime protocol with Docker and Kubernetes implementations.

- ✨ feat: git-backed knowledge store
  ([`f76a1be`](https://github.com/thiesgerken/carapace/commit/f76a1bec837b5023a1ced7449cfe3cc3fd7848b0))

  Split data directory into persistent data/ (config, sessions) and knowledge/ (memory, skills, SOUL.md, USER.md, SECURITY.md) backed by a Git repository.

  New modules:
  - git_store.py: async Git CLI wrapper (init, commit, push, pull)
  - git_http.py: Git HTTP handler via git-http-backend CGI on proxy port

  Key changes:
  - Config: CARAPACE_CONFIG env var, data_dir/knowledge_dir/git fields
  - Bootstrap: split into ensure_data_dir() and ensure_knowledge_dir()
  - Agent: removed write tools (write_memory, save_skill, save_workspace_file),
    sandbox uses git commit/push instead
  - Sentinel: added evaluate_push() for pre-receive hook security gating
  - Sandbox: mount knowledge repo as /workspace, git HTTP on proxy port
  - Server: full lifespan rewrite with GitStore init, remote pull, bootstrap
  - Helm: two PVCs (data RWX, knowledge RWO)
  - Dockerfile: added git, jq, curl

### 🐛 Bug Fixes


- 🐛 fix: display ref instead of '?' for git push approvals in CLI
  ([`541f0cc`](https://github.com/thiesgerken/carapace/commit/541f0cc65a34add020baa603d1645787a813cb39))

  Rename _render_proxy_approval_request → _render_escalation_request and read the 'ref' key for git push escalations instead of 'domain'.

- 🐛 fix: auto-deny stale escalations when a duplicate arrives
  ([`a27b6e2`](https://github.com/thiesgerken/carapace/commit/a27b6e2f4e7010acd9b36e5d8eecb79dd5bf73cd))

  When a new escalation for the same kind+ref/domain is created (e.g. agent retries git push after a timeout), the old pending escalation is automatically denied so its approval card resolves in the frontend.

- 🐛 fix: increase exec timeout to 1h and remove agent control
  ([`4d9dbc7`](https://github.com/thiesgerken/carapace/commit/4d9dbc76d2bddbc357810ccde27ec508c8d6d970))

  git push can block indefinitely when the sentinel escalates for user approval. Raise the default exec timeout to 3600s, support timeout=0 (no limit) in both runtimes, and remove the timeout parameter from the agent-facing exec tool.

- 🐛 fix: remove curl response timeout for user approval flow
  ([`7c83003`](https://github.com/thiesgerken/carapace/commit/7c830037a170c873b3eeefa4faff36e8bbb70993))

  The sentinel may escalate pushes for user approval, which can block indefinitely. Replace --max-time with --connect-timeout to still detect a down server without timing out on long approval waits.

- 🐛 fix: persist git push decisions and clear loading indicator
  ([`004d53b`](https://github.com/thiesgerken/carapace/commit/004d53b06918d3a2702c7d074a6c9c65b3d4e9b0))

- 🐛 fix: handle missing session in evaluate-push endpoint
  ([`0a77af9`](https://github.com/thiesgerken/carapace/commit/0a77af982850d65ab460e804ee6f49e029d97ff4))

- 🐛 fix: purge all tracking state on permanent session deletion
  ([`ad22de3`](https://github.com/thiesgerken/carapace/commit/ad22de309c2865a76dd3f5fe77e85b4139acd1cf))

- 🐛 fix: harden pre-receive hook against missing deps and empty stdin
  ([`8c6c9b8`](https://github.com/thiesgerken/carapace/commit/8c6c9b8554b0ab62c01af2ca09bee403bdf81f44))

- 🐛 fix: promote git auth failure logs from debug to warning
  ([`57dc7a5`](https://github.com/thiesgerken/carapace/commit/57dc7a583338a9583b118caa81e96b6d29e980b3))

- 🐛 fix: persist sandbox session tokens across server restarts
  ([`1ee86e0`](https://github.com/thiesgerken/carapace/commit/1ee86e0efe72a1679579af904e8aa2c031287652))

  Save session_id→token mapping to sandbox_tokens.json in the data dir. Tokens are reloaded on startup so existing sandbox containers (with credentials embedded in the git remote URL) can still authenticate.

- 🐛 fix: add debug logging for git auth failures
  ([`61ce299`](https://github.com/thiesgerken/carapace/commit/61ce299150a9ee09449939d53ca3148ddd3d74e8))

  Log specific reason (no header, malformed creds, invalid token) when sandbox git requests return 401.

- 🐛 fix: use TestModel in session tests to avoid requiring API keys in CI
  ([`5e3dc3f`](https://github.com/thiesgerken/carapace/commit/5e3dc3f56b5f9ddb9ec551a0859499c255057a08))

- 🐛 fix: address security and configuration bugs
  ([`c55d421`](https://github.com/thiesgerken/carapace/commit/c55d42128ce667234d0756b645f861a9750a5179))

  - Fix shell error suppression in _sync_skill_venv that masked pyproject.toml restore failures
  - Change default api_port in GitHttpHandler from 8321 (public API) to 8320 (internal API)

  Applied via @cursor push command

- 🐛 fix: address security and configuration bugs
  ([`6ee6347`](https://github.com/thiesgerken/carapace/commit/6ee6347a15417a180accffc5a30390a3e6882ac1))

  - Fix shell error suppression in _sync_skill_venv that masked pyproject.toml restore failures
  - Change default api_port in GitHttpHandler from 8321 (public API) to 8320 (internal API)

- 🐛 fix: handle null SHA on initial branch push in pre-receive hook
  ([`14c18ef`](https://github.com/thiesgerken/carapace/commit/14c18ef17c23eca610ec146ad4692d9b576d5b2f))

- 🐛 fix: remove unused volume mapping for knowledge directory in docker-compose.yml
  ([`75e7277`](https://github.com/thiesgerken/carapace/commit/75e72778ed8bb463e62a7b80ea529ac5c90b6e7f))

- 🐛 fix: use 127.0.0.1 and --fail in pre-receive hook curl call
  ([`8aba398`](https://github.com/thiesgerken/carapace/commit/8aba398ab50dc3bc9816110c660cc682a8355983))

  Co-authored-by: thiesgerken <7550099+thiesgerken@users.noreply.github.com>

  Agent-Logs-Url: https://github.com/thiesgerken/carapace/sessions/db6aa13c-6f79-4a79-8dce-9144ceaaba75

- 🐛 fix: resolve knowledge_dir relative to config file, not CWD
  ([`2a61a07`](https://github.com/thiesgerken/carapace/commit/2a61a078384f3f62cc0eb5e96807328f7b7e9b80))

  Resolving relative to CWD made container deployments fragile — e.g. Docker mounts knowledge at /knowledge but ./knowledge resolved to /app/knowledge. Now uses the same strategy as data_dir: relative to the config file's parent directory.

- 🐛 fix: load SOUL.md, USER.md, AGENTS.md from knowledge_dir
  ([`1dbefab`](https://github.com/thiesgerken/carapace/commit/1dbefabc1213ec7455d8285f015041e08e0f318a))

  These files were moved to the knowledge repo but build_system_prompt() still loaded them from data_dir, which now only holds config.yaml and sessions.

### ♻️ Refactoring


- ♻️ refactor: clone knowledge repo directly into /workspace
  ([`c8e40ba`](https://github.com/thiesgerken/carapace/commit/c8e40ba181e714263b18ac8ef0136ec7b9a2cc3c))

  Instead of /workspace/knowledge/, the git repo is now cloned into /workspace/ (the container workdir). Simplifies paths throughout the agent system prompt, sandbox manager, example skill, and docs.

- ♻️ refactor: clean up naming inconsistencies across escalation pipeline
  ([`0ac7e7e`](https://github.com/thiesgerken/carapace/commit/0ac7e7e0bacdb5156b68854fcda6210e32e1439b))

  - DomainDecision → EscalationDecision (used for both domain and git push)
  - ProxyApprovalRequest → DomainAccessApprovalRequest (names the action, not the mechanism)
  - escalate_to_user(domain, ...) → escalate_to_user(subject, ...)
  - evaluate_domain() → evaluate_domain_access(), prompt label proxy_domain_request → domain_access_request
  - Explicit kind='domain_access' in evaluate_domain_with context dict (was implicit default)
  - proxy_approval event role → domain_access_approval (back-compat for reading old sessions)
  - on_proxy_approval_request → on_domain_access_approval_request subscriber method
  - Renamed proxy-approval-card.tsx → domain-access-approval-card.tsx
  - Added missing on_git_push_approval_request and on_git_push_info to Matrix subscriber
  - Simplified format_domain_escalation (removed kind param, git pushes use dedicated method)

- ♻️ refactor: per-session token files with lazy loading
  ([`53de96c`](https://github.com/thiesgerken/carapace/commit/53de96c3bed3e6811fefc1cfb888ae7f9794c70c))

  - Store sandbox tokens in sessions/{sid}/token instead of a single
    sandbox_tokens.json.
  - Load tokens lazily in _get_or_create_token(): memory → disk → new.
    No bulk scan at startup.
  - cleanup_session only removes the container reference, keeping
    tokens and domain state so the sandbox can be re-created on
    next use.
  - _cleanup_tracking is now only the ensure_session error-path
    rollback.
  - Add 'no silent failures' guideline to AGENTS.md.

- ♻️ refactor: wait for log readiness then exec git clone
  ([`f43388b`](https://github.com/thiesgerken/carapace/commit/f43388b62fc0ce076e7e769c600869c46ec8df07))

  Instead of running git clone inside the container entrypoint and polling for /workspace/knowledge/.git, the container now starts with only setup-proxy.sh + sleep infinity.  After 'carapace sandbox ready' appears in the container logs, an exec runs the git clone.

  This gives direct visibility into clone errors (exit code + output) and cleanly separates container readiness from repo setup.

- ♻️ refactor: mount whole workspace dir, clone knowledge repo into subdirectory
  ([`5c8eb1c`](https://github.com/thiesgerken/carapace/commit/5c8eb1c118ccd9285abb12ce6572467cc2e9033e))

  Replace the /workspace/tmp bind mount with a full /workspace/ mount (host: sessions/{sid}/workspace/, k8s: PVC subPath).  The knowledge repo is now cloned into /workspace/knowledge/ on first container start; existing clones are left untouched on restart.

  This fixes 'destination path already exists' from git clone (the previous tmp sub-mount caused Docker to pre-create /workspace/) and gives the agent a persistent scratch area outside the git tree.

- ♻️ refactor: make Deps.agent_model required, add ModelType literal
  ([`c5f2729`](https://github.com/thiesgerken/carapace/commit/c5f2729effb009b360865f4a6183055717fd0070))

  - Deps.agent_model is now Model (required, no None)
  - _build_deps resolves fallback eagerly via _resolve_model()
  - create_agent and loop.py use deps.agent_model directly
  - ModelType = Literal['agent', 'sentinel', 'title'] for model commands
  - _apply_model_override model_obj is Model | None (only used for agent)

- ♻️ refactor: replace Any types in Deps with concrete annotations
  ([`d46105e`](https://github.com/thiesgerken/carapace/commit/d46105e59379b28ed005bc65f994e8b97d9b5fac))

  - Deps.sentinel: Sentinel, git_store: GitStore, agent_model: Model | None
  - SessionEngine: git_store typed as GitStore, agent_model as Model | None
  - ActiveSession.agent_model typed as Model | None
  - tests use MagicMock(spec=...) for proper isinstance checks
  - _patch_sentinel() helper for test_session Sentinel class patching

- ♻️ refactor: remove host-side file ops from skill activation
  ([`a1284d4`](https://github.com/thiesgerken/carapace/commit/a1284d409b0c3ca16354f47f6159c50d919a3210))

  - activate_skill no longer copies skill files from knowledge_dir to
    session workspace (git clone already provides them at /workspace)
  - _sync_skill_venv restores trusted pyproject.toml/uv.lock via
    git checkout inside the container instead of shutil.copy2
  - rebuild_skill_venvs checks master knowledge_dir for pyproject.toml
    instead of unmounted session workspace path
  - removed unused shutil import

- ♻️ refactor: reorganize modules into sub-packages
  ([`69cbc0c`](https://github.com/thiesgerken/carapace/commit/69cbc0c6ac51b4cd766dbdd09aa3b2f06d47a187))

  - agent.py + agent_loop.py → agent/{__init__, tools, loop}.py
  - git_http.py + git_store.py → git/{__init__, http, store}.py
  - session.py + session_engine.py + session_manager.py + titler.py
    → session/{__init__, engine, manager, titler}.py
  - Each package re-exports public API from __init__.py
  - All external imports (carapace.session, carapace.agent) still work
  - Deferred titler import promoted to top-level in session/engine.py

- ♻️ refactor: standardise auth to session_id:token Basic Auth
  ([`1e79ce1`](https://github.com/thiesgerken/carapace/commit/1e79ce14c1a5eaf23851cff5c514351785784abf))

  - proxy extracts token from password field (was username)
  - proxy URL uses session_id:token@ format
  - git handler receives pre-authenticated session_id from proxy
  - removed _extract_basic_auth and get_session_by_token from GitHttpHandler
  - manager injects GIT_REPO_URL and clones during sandbox startup
  - git traffic now routes through proxy (removed host.docker.internal bypass)
  - updated tests for new auth contract

- ♻️ refactor: use single PVC for data and knowledge
  ([`bd838c3`](https://github.com/thiesgerken/carapace/commit/bd838c3c682deffd28c5b4cdd8d2f175764b13aa))

  Knowledge directory lives as a subdirectory of the data PVC (/var/lib/carapace/knowledge) — no need for a separate PVC.

### 🔒 Security


- 🔒 fix: escape ref names in pre-receive hook JSON payload
  ([`af672f6`](https://github.com/thiesgerken/carapace/commit/af672f62c35c85b451d726e1261fddc1bacb5b2e))

  Use jq -n with --arg to build the JSON payload instead of shell string interpolation, preventing injection via crafted ref names.

- 🔒 fix: use Path() to validate PATH_INFO against traversal in GitHttpHandler
  ([`54eaee4`](https://github.com/thiesgerken/carapace/commit/54eaee43e03b3dbbfabb758f16dc259d36c9bc73))

  Co-authored-by: thiesgerken <7550099+thiesgerken@users.noreply.github.com>

  Agent-Logs-Url: https://github.com/thiesgerken/carapace/sessions/cc5a4d5f-efd9-42ef-ade5-933dac6420af

- 🔒 refactor: split server into 3-port architecture
  ([`b006e6f`](https://github.com/thiesgerken/carapace/commit/b006e6f21bdab60b40b25919caa1fae7ecb2d011))

  - Public API (8321): REST + WebSocket, Bearer token auth
  - Sandbox API (8322): Git HTTP backend, Basic Auth (session_id:token)
  - Internal API (8320): sentinel callback, loopback only (127.0.0.1)
  - SandboxManager uses sandbox_port for GIT_REPO_URL (was api_port)
  - Pre-receive hook default port updated to 8320
  - Helm chart: add sandboxPort to values, deployment, service, networkpolicy
  - Updated architecture and kubernetes docs for 3-port model

- 🔒 fix: validate PATH_INFO in GitHttpHandler to prevent repo traversal
  ([`8f4f423`](https://github.com/thiesgerken/carapace/commit/8f4f423eb4923835f0d190fbd3a45503d995fe49))

  GIT_PROJECT_ROOT is knowledge_dir.parent, which could be / if knowledge lives at /knowledge. Without validation, git http-backend could serve any git repo on the filesystem.

  Now rejects requests whose PATH_INFO doesn't start with the intended repo name (knowledge_dir.name or knowledge_dir.name.git) with 403.

  Also adds tests for the path validation (forbidden path returns 403, allowed path without .git suffix passes through).

- 🔒 fix: don't bind-mount knowledge repo into sandbox
  ([`0e314ff`](https://github.com/thiesgerken/carapace/commit/0e314ff57e7966f2fbfc594ecec2095b39f15845))

  The sandbox should obtain the knowledge repo via git clone through the Git HTTP handler (port 3128), which enforces the pre-receive hook security gate. Mounting the host repo directly would bypass the sentinel evaluation entirely.

  Also fixes master skill paths to use knowledge_dir instead of data_dir.

### 🔧 Configuration


- 🔧 fix: improve log retrieval error handling with warning level
  ([`e483de1`](https://github.com/thiesgerken/carapace/commit/e483de188762135d0fb921ead895482f72e6fd86))

- 🔧 fix: sync server ports via env vars between Helm and app
  ([`fcce47d`](https://github.com/thiesgerken/carapace/commit/fcce47dc25d1d2778de7b21037b0ce34b02dd77f))

  - ServerConfig now uses BaseSettings with CARAPACE_SERVER_ env prefix,
    supporting CARAPACE_SERVER_PORT, CARAPACE_SERVER_SANDBOX_PORT, etc.
  - Helm deployment template injects port values as env vars so changing
    server.apiPort / sandboxPort / proxyPort in values.yaml automatically
    configures the application without manual config.yaml edits

- 🔧 fix: make API port configurable for pre-receive hook and Helm chart
  ([`a358ade`](https://github.com/thiesgerken/carapace/commit/a358aded04dda7cea245cb5f3480005fd778118d))

  - pre-receive hook uses ${CARAPACE_API_PORT:-8321} instead of hard-coded 8321
  - GitHttpHandler passes CARAPACE_API_PORT in CGI env to git http-backend
  - Helm chart: new server.apiPort / server.proxyPort values
  - all templates reference values instead of hard-coded port numbers

### Other


- enhance post-push success handling with HTTP status and response validation
  ([`a653015`](https://github.com/thiesgerken/carapace/commit/a6530150c5d30e5727e3ea5a8da7b142db8b68a6))

- improve logging
  ([`e274767`](https://github.com/thiesgerken/carapace/commit/e274767d2ea9563d16932b57185cbbef4fe59191))

- 📝 docs: add pre-commit workflow note to AGENTS.md
  ([`116be57`](https://github.com/thiesgerken/carapace/commit/116be57126733efd45e6e31d2e9f3f8572afcf2e))

- Merge remote-tracking branch 'refs/remotes/origin/feat/git-knowledge-store' into feat/git-knowledge-store
  ([`522ed4e`](https://github.com/thiesgerken/carapace/commit/522ed4e9c049e9fba4e81235463ab4eab9a0b757))

- 🔥 refactor: remove config.yaml bootstrapping
  ([`87c99d7`](https://github.com/thiesgerken/carapace/commit/87c99d79bc5d349e781822e89c802b8421addf4b))

  Config() defaults match the bundled asset exactly, so seeding config.yaml on first start adds no value and creates a subtle ordering issue (load_config runs before ensure_data_dir).

- 📝 docs: align architecture.md and memory.md with git-backed knowledge store
  ([`10eb22a`](https://github.com/thiesgerken/carapace/commit/10eb22a1f9a48c4b4769f7f7e8bcb7e3388dea62))

- Merge pull request #53 from thiesgerken/copilot/sub-pr-52
  ([`82d5ebd`](https://github.com/thiesgerken/carapace/commit/82d5ebd8d5a4684602751147599375d0e59b421f))

  Fix PATH_INFO path traversal in GitHttpHandler

- Initial plan
  ([`02f9300`](https://github.com/thiesgerken/carapace/commit/02f93003a04fabc4fe818c5b64ca595d3698cf64))

- Merge pull request #54 from thiesgerken/copilot/sub-pr-52-again
  ([`d6e2944`](https://github.com/thiesgerken/carapace/commit/d6e2944ae9ed254b3f3f866e87424ccc025d0fe0))

  fix: use 127.0.0.1 and --fail in pre-receive hook curl call

- Initial plan
  ([`7922c55`](https://github.com/thiesgerken/carapace/commit/7922c55d5a7d43d8a0f61c6388fb12652220d1b7))

- ignore tmp in .gitignore for workspace
  ([`5c32ce1`](https://github.com/thiesgerken/carapace/commit/5c32ce10e5a72487a1ae90cefc08e727411ff313))

  Co-authored-by: Copilot <175728472+Copilot@users.noreply.github.com>

- mdlint
  ([`bac496c`](https://github.com/thiesgerken/carapace/commit/bac496c10232dbffc0be535cfae23c23cda7d303))

- ✅ test: add unit tests for GitStore and GitHttpHandler
  ([`e0a57a4`](https://github.com/thiesgerken/carapace/commit/e0a57a40215edd98f8307c903a871854b7d2b2d2))

  35 tests covering:
  - GitStore: author template parsing, repo init, hook install,
    commit (new file, empty, idempotent), remote management, pull/push
  - GitHttpHandler: Basic Auth extraction (valid, missing, wrong scheme,
    empty password, case-insensitive), CGI-to-HTTP conversion, header
    lookup, 401 on unauthenticated/invalid token requests

- 📝 chore: add comment to except ValueError in _host_path
  ([`61a0114`](https://github.com/thiesgerken/carapace/commit/61a011454d39fccbd0188397290b1af444970125))

## v0.41.1 (2026-03-21)


### 🔧 Configuration


- 🔧 config: add custom changelog template with descriptive section headings
  ([`2c237e7`](https://github.com/thiesgerken/carapace/commit/2c237e70b1fe6862859f3b979dc0cf90b825d9e4))

  Map gitmoji to labeled headings (e.g. '### 🐛 Bug Fixes' instead of '### 🐛'). Uses template_dir with a custom CHANGELOG.md.j2 Jinja2 template.

## v0.41.0 (2026-03-21)


### ✨ Features


- ✨Merge pull request #51 from thiesgerken/feature/model-switching
  ([`8239715`](https://github.com/thiesgerken/carapace/commit/823971555ea1275e272953f62c2e1de588503afb))

  ✨ feat: add /model slash command for per-session model switching

- ✨ feat: add available models list
  ([`39bf195`](https://github.com/thiesgerken/carapace/commit/39bf1958a963613aebdd0fc6da81e499cfcbc5ae))

- ✨ feat: add /model slash command for per-session model switching
  ([`1129d4f`](https://github.com/thiesgerken/carapace/commit/1129d4fd2d2125b4c4e828e1d131ac6dd2392877))

  Support switching agent, sentinel, and title models on the fly within a session via /model [--type agent|sentinel|title] [model | reset]. No args shows all three models in a table. Usage tracking correctly buckets tokens under the actual model used.

### 🐛 Bug Fixes


- 🐛 fix: prevent showing model suggestions if the argument matches an available model
  ([`5e792bd`](https://github.com/thiesgerken/carapace/commit/5e792bd1e5b23452c937d96397520ff2aaab07f0))

- 🐛 fix: add timeout to AsyncClient to make gemini work
  ([`6c0a1c7`](https://github.com/thiesgerken/carapace/commit/6c0a1c77b1f6a8091c0560b5b23f44ee7c97fbb2))

### ♻️ Refactoring


- ♻️ refactor: split /model into /models, /model, /model-sentinel, /model-title
  ([`ccda12b`](https://github.com/thiesgerken/carapace/commit/ccda12b07ead82b903f9abe3638673630ace639b))

  - /models: overview table of all model types with available models
  - /model, /model-sentinel, /model-title: view/set individual models
  - Changing title model triggers automatic title regeneration
  - handle_slash_command is now async to support title regeneration
  - Simplified frontend autocomplete (no more --type flag parsing)

### Other


- Merge remote-tracking branch 'origin/main' into feature/model-switching
  ([`796a358`](https://github.com/thiesgerken/carapace/commit/796a35887a1c7310d0e6ac31095aab99e5671294))

- fix to model autocomplete
  ([`5c80563`](https://github.com/thiesgerken/carapace/commit/5c805634e4f1224c76ef9feb3d749df302d47231))

- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`a46cfa9`](https://github.com/thiesgerken/carapace/commit/a46cfa93cdadc3d74478096996f92d470ef11e24))

## v0.40.2 (2026-03-21)


### Other


- 📝 docs: convert README architecture diagram to mermaid
  ([`911ad49`](https://github.com/thiesgerken/carapace/commit/911ad49551503ac015d32a4ad145385eb4e1344c))

- 📝 docs: rewrite docs to match actual implementation
  ([`93938cf`](https://github.com/thiesgerken/carapace/commit/93938cf7f5b11d9d7507a0170c5f4f4f8f19f8a9))

  - Rewrite architecture.md, sandbox.md, memory.md, sessions-and-channels.md, skills.md to reflect current codebase
  - Move credentials.md to docs/plans/ (credential broker is mock-only)
  - Create docs/plans/ for future features: memory (vector search, daily logs), channels (cron/heartbeat, E2EE), kubernetes (per-session PVCs, StatefulSets, git-backed storage)
  - Update security.md (audit format JSONL→YAML, fix descriptions)
  - Update kubernetes.md (ASCII→mermaid diagram, add plans link)
  - Update README.md: fix architecture description, remove aspirational features, update status and tech stack

### 🐛 Bug Fixes


- 🐛 fix: resolve ESLint errors in use-websocket hook
  ([`762a216`](https://github.com/thiesgerken/carapace/commit/762a21670d6ac2f6fe407363d53f388a613fb7a5))

## v0.40.1 (2026-03-21)


### ⬆️ Dependencies


- ⬆️ upgrade ruff-pre-commit to v0.15.7
  ([`e765c54`](https://github.com/thiesgerken/carapace/commit/e765c543ce87a6fcd18405516ce4759d9463fcb0))

- ⬆️ upgrade deps and fix a small linter issue
  ([`075cee7`](https://github.com/thiesgerken/carapace/commit/075cee7685ba12d6dbbe48b3664421948ed11ac6))

### 🐛 Bug Fixes


- 🐛 fix: skip autofocus on mobile to prevent hidden input
  ([`381766d`](https://github.com/thiesgerken/carapace/commit/381766de632ede1faed08da2602526874aae8654))

## v0.40.0 (2026-03-20)


### ✨ Features


- ✨ support other model providers as well
  ([`15a61ad`](https://github.com/thiesgerken/carapace/commit/15a61ad9e2f351bc8bd140dc716e06d2519af891))

### Other


- 💚 hardcode package name
  ([`87d6730`](https://github.com/thiesgerken/carapace/commit/87d67303bb3c05574a02e0f21145f540afb38b20))

- 💚 skip release on main if not needed
  ([`9b2e31a`](https://github.com/thiesgerken/carapace/commit/9b2e31ab71423abdd0209ac85fa432784c623a24))

## v0.39.1 (2026-03-18)


### 💄 UI/UX


- 💄 fix: improve mobile UX (viewport, touch targets, safe areas, input zoom)
  ([`5021676`](https://github.com/thiesgerken/carapace/commit/50216766b6afea81e8ce0e025df39bb056809dca))

### Other


- relock
  ([`93855bd`](https://github.com/thiesgerken/carapace/commit/93855bd5a8061e4515ed7a08f950b83d159467b6))

## v0.39.0 (2026-03-18)


### 🐛 Bug Fixes


- 🐛 fix: ensure uv is installed in build command
  ([`250f607`](https://github.com/thiesgerken/carapace/commit/250f60775d62fb62863d932a48399554e49d239e))

- 🐛 fix: show usage bar immediately on session load
  ([`67234c3`](https://github.com/thiesgerken/carapace/commit/67234c389f9fb99389c02ff603ad3a15cbfda167))

- 🐛 fix: only auto-scroll chat when already at bottom
  ([`fd73fa6`](https://github.com/thiesgerken/carapace/commit/fd73fa6da232db99608270ceb54a30e860b86170))

### ✨ Features


- ✨ feat: swipe to open/close sidebar drawer on mobile
  ([`e6e00de`](https://github.com/thiesgerken/carapace/commit/e6e00de80738d0af0a8a98124901a150c33c8c47))

- ✨ revamp Dockerfile for backend as non-root
  ([`4fe876f`](https://github.com/thiesgerken/carapace/commit/4fe876f7335e1971ea054c5f0a2be2910164242f))

### 👷 CI/Build


- 👷 ci: sync uv.lock in build_command & expand patch_tags
  ([`106308c`](https://github.com/thiesgerken/carapace/commit/106308ce061df8b18ef6bdb689f7149ccd01c637))

## v0.38.5 (2026-03-16)


### Other


- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`8d2c3b7`](https://github.com/thiesgerken/carapace/commit/8d2c3b76a1c6efd360d3a7988894cfd7484631f4))

## v0.38.4 (2026-03-16)


### 🐛 Bug Fixes


- 🐛 fix: remove dead code in DockerRuntime
  ([`bef59a2`](https://github.com/thiesgerken/carapace/commit/bef59a20768e2f340556644269979911a32f0dc9))

  - Remove unused build_image() method (never called)
  - Rename get_network_gateway → _get_network_gateway (internal helper)
  - Remove unused 'import io'

- 🐛 update ignore patterns to exclude node_modules during skill save
  ([`d5dd419`](https://github.com/thiesgerken/carapace/commit/d5dd41925eae71d8961c77f17abb4145615be638))

### 💄 UI/UX


- 💄 improve exception formatting in UI
  ([`377fd85`](https://github.com/thiesgerken/carapace/commit/377fd85611d92a2197ef855a4640eecd1c2c2428))

## v0.38.3 (2026-03-16)


### 🐛 Bug Fixes


- 🐛 fix tool call arg type assertion
  ([`e6f2778`](https://github.com/thiesgerken/carapace/commit/e6f27789aa1859f1413afa60399ded003c83b57a))

## v0.38.2 (2026-03-16)


### Other


- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`78ddea0`](https://github.com/thiesgerken/carapace/commit/78ddea0947bf8433748493f2434ecc721c052d66))

## v0.38.1 (2026-03-16)


### Other


- 📋 less asking for git commit
  ([`0584fd2`](https://github.com/thiesgerken/carapace/commit/0584fd24e76c943f0213798de9aaca9274fab002))

### 🐛 Bug Fixes


- 🐛 fix: persist user message to history on failed agent turns
  ([`107abfe`](https://github.com/thiesgerken/carapace/commit/107abfefd6d7993721ee000b9e0e50c0354a21ab))

  When run_agent_turn raises an exception (e.g. failed tool call), the message history was never saved. The next turn loaded stale history, losing both the user message and any context from the failed turn.

  Add _save_user_message_on_failure() which appends the user's ModelRequest to the persisted history in both CancelledError and Exception handlers so the agent retains context across failures.

- 🐛 improve error handling for crashing sandbox
  ([`7e8bcf4`](https://github.com/thiesgerken/carapace/commit/7e8bcf456b7fd40ebf81cfc26b73e9122dfa8800))

## v0.38.0 (2026-03-16)


### ✨ Features


- ✨ feat: make workspace files editable copies with save_workspace_file tool
  ([`267c021`](https://github.com/thiesgerken/carapace/commit/267c021d34f9f88c3794ab0c767afd14a1fcaba5))

  Replace read-only bind mounts of AGENTS.md, SOUL.md, USER.md, and SECURITY.md with writable copies in the session workspace. The agent can now edit these files in the sandbox and persist changes back to the main data directory via the new save_workspace_file tool.

  - Sentinel reads SECURITY.md from disk on every evaluation (dynamic
    instructions callable) so policy changes take effect immediately
  - SessionEngine no longer threads security_md through the stack
  - save_workspace_file is security-gated and restricted to the four
    known workspace files
  - SECURITY.md updated to instruct sentinel to always escalate saves

## v0.37.0 (2026-03-16)


### ✨ Features


- ✨ improve handling of SECURITY.md (reload often) + add approvals to events + remove load_security_md
  ([`e94fd40`](https://github.com/thiesgerken/carapace/commit/e94fd4061aebacb5eff8dad34755189051e55344))

- ✨ feat: add CARAPACE_RESET_ASSETS flag to overwrite bundled assets on startup
  ([`65adde5`](https://github.com/thiesgerken/carapace/commit/65adde5f7a234f68877daf0de89e2988f8fc4caf))

  When set to a truthy value (1/true/yes), ensure_data_dir() overwrites SECURITY.md, CORE.md, and bundled skills with the versions shipped in the container image. User-owned files (SOUL.md, USER.md, config.yaml) are never overwritten — only seeded when missing.

  - bootstrap.py: respect CARAPACE_RESET_ASSETS env var
  - docker-compose.yml: pass through the new env var
  - Helm chart: new resetAssets value (default false)

## v0.36.0 (2026-03-16)


### ✨ Features


- ✨ improve proxy setup
  ([`dde455a`](https://github.com/thiesgerken/carapace/commit/dde455a701cba5a94fd464d6ef7237e44ce58a2c))

### 🐛 Bug Fixes


- 🐛 improve uv documentation for agent
  ([`01a3fd1`](https://github.com/thiesgerken/carapace/commit/01a3fd17deb5f258a77f3e854964961c2295da59))

## v0.35.1 (2026-03-15)


### 🐛 Bug Fixes


- 🐛remove dead code
  ([`53543fe`](https://github.com/thiesgerken/carapace/commit/53543fe8be48ecf8567c3c1d3356c0d23c161f1a))

## v0.35.0 (2026-03-15)


### ✨ Features


- ✨ feat: stream LLM responses to CLI, web UI, and Matrix
  ([`e00f979`](https://github.com/thiesgerken/carapace/commit/e00f979afe6bb4f286f3353ca254cd2b916d823e))

  Use Pydantic AI's event_stream_handler to emit token chunks during agent.run() without changing the existing approval/deferred-tools loop. Chunks are broadcast via the subscriber protocol and replaced by the authoritative Done message on completion.

  - CLI: progressive Markdown rendering via rich.Live
  - Web UI: streaming message kind replaced atomically on done
  - Matrix: single notice edited in-place every 200 chars, then
    replaced with final m.text on done

## v0.34.1 (2026-03-15)


### Other


- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`18ff1cf`](https://github.com/thiesgerken/carapace/commit/18ff1cf74ca91cad072cb9f5bf0d59fb76e84bd1))

## v0.34.0 (2026-03-15)


### 🐛 Bug Fixes


- 🐛 fix: remove unnecessary packages from Dockerfile
  ([`7ea00f3`](https://github.com/thiesgerken/carapace/commit/7ea00f33ac6cc849a69b32676c3417faa551cda1))

### ✨ Features


- ✨ feat: switch sandbox image to python:3.14-slim-trixie
  ([`031837a`](https://github.com/thiesgerken/carapace/commit/031837aed52d59504c41a5cec5d469e60cf3c641))

  Share the base image with the server container so layers are deduplicated on disk. Replace apk with apt-get, copy uv binary from the official image, and drop redundant python3/py3-pip/ ca-certificates packages.

## v0.33.4 (2026-03-15)


### 🐛 Bug Fixes


- 🐛 fix: chmod writable sandbox dirs instead of chown (K8s storage compat)
  ([`bf924de`](https://github.com/thiesgerken/carapace/commit/bf924deec7a6a25c08eaf4daa072e63849bcdb8e))

## v0.33.3 (2026-03-15)


### Other


- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`bfff432`](https://github.com/thiesgerken/carapace/commit/bfff432f5533d710c021b11870f41d447f011daf))

## v0.33.2 (2026-03-15)


### 🐛 Bug Fixes


- 🐛 fix: prevent mobile header from scrolling away in long conversations
  ([`71e155d`](https://github.com/thiesgerken/carapace/commit/71e155d12e062844f9b8e2770c0d594ae6e34583))

  Replace h-full with flex-1 min-h-0 on ChatView root so the messages area properly constrains to remaining viewport height after the mobile header, enabling overflow-y-auto instead of growing past the screen.

- 🐛 fix: add initContainer to chown writable PVC dirs in K8s sandbox pods
  ([`2452b4a`](https://github.com/thiesgerken/carapace/commit/2452b4a42cfc5e6b0b378eee649e0f5dc018df3c))

## v0.33.1 (2026-03-15)


### 🐛 Bug Fixes


- 🐛 make sure to refetch matrix token if user_id changes + accept pending invites at startup
  ([`eb553c9`](https://github.com/thiesgerken/carapace/commit/eb553c979c02f94ac70e15a85f48950f19ca0e7e))

## v0.33.0 (2026-03-15)


### ✨ Features


- ✨ feat: log startup message in sandbox containers before sleep
  ([`3059171`](https://github.com/thiesgerken/carapace/commit/30591715528dff44b126a9a8a35399f7efb47110))

## v0.32.3 (2026-03-15)


### 🐛 Bug Fixes


- 🐛 fix: update k8s_owner_ref to True for sandbox pods
  ([`6c8c72d`](https://github.com/thiesgerken/carapace/commit/6c8c72dd84d0fe85aa39f9aee551c8fd9b0d42f6))

## v0.32.2 (2026-03-15)


### 🐛 Bug Fixes


- 🐛 fix: add ArgoCD tracking annotation to sandbox pods for app discovery
  ([`b158fd2`](https://github.com/thiesgerken/carapace/commit/b158fd2b9c560c4615fc1811f90f12b046688cc0))

## v0.32.1 (2026-03-15)


### 🐛 Bug Fixes


- 🐛💚 update pre-commit and actions
  ([`fd4a265`](https://github.com/thiesgerken/carapace/commit/fd4a2656728fd77106d437bfe44bbe4b954731ca))

## v0.32.0 (2026-03-15)


### Other


- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`0249cb0`](https://github.com/thiesgerken/carapace/commit/0249cb007d705636301b3cf1e858af6816936692))

## v0.31.0 (2026-03-15)


### ✨ Features


- ✨ feat: make sandbox pod ownerReference configurable (default off)
  ([`7219c8f`](https://github.com/thiesgerken/carapace/commit/7219c8f5f2885d1e6e60917b9bb2f1eb8efeda8f))

- ✨ better url guessing in ui
  ([`2bece2e`](https://github.com/thiesgerken/carapace/commit/2bece2e77749251d18309ed167b7a459ec3fdb2a))

## v0.30.2 (2026-03-15)


### 🐛 Bug Fixes


- 🐛 fix: use Always restart policy for sandbox pods and rename to carapace-sandbox-*
  ([`d0c3335`](https://github.com/thiesgerken/carapace/commit/d0c33351ae5746ff6fecc2f9ba6a71d12468d88c))

### Other


- 📝 docs: add NetworkPolicy security warnings to Kubernetes docs
  ([`373634b`](https://github.com/thiesgerken/carapace/commit/373634bab2010360efee5d4ce0c5bf1ba9025aac))

## v0.30.1 (2026-03-15)


### 🐛 Bug Fixes


- 🐛 fix: move kubernetes from optional to regular dependency
  ([`a0a8d94`](https://github.com/thiesgerken/carapace/commit/a0a8d942fbf8baf052ba13d6a0b770de04f58ecf))

## v0.30.0 (2026-03-15)


### Other


- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`97d9cb6`](https://github.com/thiesgerken/carapace/commit/97d9cb6dbbf7779613362eaafee95f8b93b08182))

## v0.29.0 (2026-03-15)


### ✨ Features


- ✨ feat(chart): support config.yaml via ConfigMap
  ([`6c19915`](https://github.com/thiesgerken/carapace/commit/6c19915f89ed9177dca024d41570af82f57fb574))

- ✨ feat: replace auto-generated token with CARAPACE_TOKEN env var
  ([`0f45c40`](https://github.com/thiesgerken/carapace/commit/0f45c40b5af2346a6b90a2f845e227a3b79fa7cd))

## v0.28.1 (2026-03-15)


### 🐛 Bug Fixes


- 🐛 fix: use version_pattern for Chart.yaml version bumping and override helm package version
  ([`df66025`](https://github.com/thiesgerken/carapace/commit/df6602514ae6578b81d846fe1e1efb95d1f29287))

### Other


- 📝 docs: add Helm chart install command to release notes
  ([`2cf0c30`](https://github.com/thiesgerken/carapace/commit/2cf0c304278727c437c3293c4d701f0c62efb967))

## v0.28.0 (2026-03-15)


### ✨ Features


- ✨ feat: Gateway API HTTPRoute, OCI chart publishing, PVC finalizers, default resources
  ([`7b4dba6`](https://github.com/thiesgerken/carapace/commit/7b4dba6f3a5984dfc6cba3a43dc7953f79472d1b))

## v0.27.0 (2026-03-15)


### Other


- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`9c3e094`](https://github.com/thiesgerken/carapace/commit/9c3e0941f6915cee642ea52c47ca953d3f22f42b))

## v0.26.0 (2026-03-15)


### ✨ Features


- ✨ feat: mount all API endpoints under /api prefix
  ([`d660c9b`](https://github.com/thiesgerken/carapace/commit/d660c9b71b4376355ceadf5b612e7562a6df00c7))

- ✨ feat: add Helm chart for Kubernetes deployment
  ([`b9ef7cd`](https://github.com/thiesgerken/carapace/commit/b9ef7cdc5bb146ba63bab2c34932673c24b0700f))

## v0.25.3 (2026-03-14)


### 🐛 Bug Fixes


- 🐛 no need to add that to soul.md
  ([`7fc25bb`](https://github.com/thiesgerken/carapace/commit/7fc25bb429442db6ba64b3fbd71ec5916b91e66c))

### Other


- 📝 docs: clarify that the agent has internet access (security-gated)
  ([`e4b550b`](https://github.com/thiesgerken/carapace/commit/e4b550b0456d14e2e51d9c82663a2f403cfe22a0))

## v0.25.2 (2026-03-14)


### 🐛 Bug Fixes


- 🐛 fix linter issues due to missing stuff in the protocol
  ([`1e8c1eb`](https://github.com/thiesgerken/carapace/commit/1e8c1eba6c2dabb7917df9524eaa33aa6d979d1c))

### Other


- runtime stuff
  ([`332a43d`](https://github.com/thiesgerken/carapace/commit/332a43d14aca93c2636fe0a01c1e02cd918876aa))

- no sandbox versioning automatically
  ([`fcc65ef`](https://github.com/thiesgerken/carapace/commit/fcc65efcd318cc7d1085f37cd57f0b8bf8ced15f))

## v0.25.1 (2026-03-14)


### 🐛 Bug Fixes


- 🐛 fix cors mounting
  ([`18af792`](https://github.com/thiesgerken/carapace/commit/18af792ec2d3f57fa5142283ce370c687cab55c5))

- 🐛 fix usagetracker import issues
  ([`07979a6`](https://github.com/thiesgerken/carapace/commit/07979a685d099106470fc1704b696f261afcfe90))

### Other


- lint
  ([`f4262a9`](https://github.com/thiesgerken/carapace/commit/f4262a91c59261825fffa6e2a53c8e046ec6c9d7))

- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`49694a9`](https://github.com/thiesgerken/carapace/commit/49694a98a7e5ced9e60f15f5d4ab8738e5e64f2c))

## v0.25.0 (2026-03-14)


### 💄 UI/UX


- 💄 lint issues
  ([`c3673b5`](https://github.com/thiesgerken/carapace/commit/c3673b5f7b76405b1664659be549757725513a0e))

### ✨ Features


- ✨ feat: add Kubernetes sandbox runtime and deployment manifests
  ([`547855b`](https://github.com/thiesgerken/carapace/commit/547855b50044745f98def3af38666d53be9a8983))

  - KubernetesRuntime implements ContainerRuntime protocol using k8s API
  - Sandbox pods use PVC subPaths, ownerReferences, NetworkPolicy isolation
  - Runtime selection via config.sandbox.runtime (docker|kubernetes)
  - Kustomize manifests in k8s/ (namespace, PVC, RBAC, deployments, ingress)
  - Full deployment guide at docs/kubernetes.md
  - 19 unit tests with mocked k8s API
  - Add pytest-asyncio with asyncio_mode=auto

### Other


- 📋 update TODO.md: refine Sandbox/Docker and Channels sections, remove outdated tasks
  ([`932c985`](https://github.com/thiesgerken/carapace/commit/932c9851c97bad80c7a22c2e7abdf8073417fe15))

## v0.24.0 (2026-03-14)


### Other


- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`d733ba2`](https://github.com/thiesgerken/carapace/commit/d733ba2f6206245e4a457ca2d6d39693bab36956))

- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`7959a5e`](https://github.com/thiesgerken/carapace/commit/7959a5e710c1839a01b4af71a11f29297127460b))

## v0.23.0 (2026-03-14)


### ✨ Features


- ✨ feat: build skill venvs inside session container
  ([`b6cab4f`](https://github.com/thiesgerken/carapace/commit/b6cab4f2a76f8b35c5d2fcb38de98cd01eaf22f8))

  Replace the ephemeral build container (_build_skill_venv with network=None) with uv sync executed inside the session's own sandbox container.  A per-session exec lock serializes all container commands; the proxy bypass flag is set/cleared atomically under that lock so no concurrent command can exploit the window.

  - Add per-session asyncio.Lock for exec serialization
  - Proxy bypass (wildcard "*") scoped to locked _exec calls only
  - _sync_skill_venv copies trusted pyproject.toml/uv.lock from
    master before building, closing TOCTOU tampering
  - Persist activated_skills in SessionState (survives restarts)
  - Rebuild venvs automatically on container recreation
  - Re-sync venv after save_skill using trusted master deps
  - Remove ephemeral build container code (K8s-incompatible)

- ✨ feat: validate sandbox image at startup, restructure README quickstart
  ([`29cf9eb`](https://github.com/thiesgerken/carapace/commit/29cf9ebf7744e4aa0533a8d77e19b5bb1eeb8f74))

  - Add image_exists() to DockerRuntime
  - Server exits with clear error if sandbox image is missing
  - Split Getting Started into Docker Compose deployment and development setup
  - Add Docker to prerequisites, document 'docker compose build sandbox'

### Other


- 📋 update skills.md, remove mentions of skill dockerfiles
  ([`af9923a`](https://github.com/thiesgerken/carapace/commit/af9923a2ff71f1f9e307a44ff178f816f277fbf3))

- fix CI
  ([`5e26f54`](https://github.com/thiesgerken/carapace/commit/5e26f5438773957df27ff34023060ef479933b6d))

- 📝 docs: reorder README — demo first, dev setup last
  ([`908ce2f`](https://github.com/thiesgerken/carapace/commit/908ce2f979c0593b5235545e12b0bbb9668d7c13))

- 📝 docs: add commit-before-asking convention to AGENTS.md
  ([`3ce548e`](https://github.com/thiesgerken/carapace/commit/3ce548e0d3122781961961a17ecf11f0592ebc0c))

### 🐛 Bug Fixes


- 🐛💚 restructure release workflow to build images before creating release
  ([`f746f04`](https://github.com/thiesgerken/carapace/commit/f746f044b91e2a6fc432de3eecc13e95f038db1c))

  - Split into: version → docker builds (parallel) → publish
  - Version step uses --no-vcs-release to defer GitHub Release creation
  - Publish step creates release with wheels + docker pull commands in one shot
  - No more patching release notes after the fact

## v0.22.0 (2026-03-14)


### Other


- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`2966b0d`](https://github.com/thiesgerken/carapace/commit/2966b0de7d9cb61aae9e0622a1c555ebb2581ecc))

## v0.21.0 (2026-03-14)


### ✨ Features


- ✨ feat: add OCI labels, sandbox version tracking, and docker pull commands in release notes
  ([`cf6d200`](https://github.com/thiesgerken/carapace/commit/cf6d2001332efc6b44b1760f4c72a766bdecaec0))

  - Add docker/metadata-action to all image builds for proper GHCR linking
  - Add update-release job to append docker pull commands to release notes
  - Add _SANDBOX_IMAGE_VERSION to models.py, managed by semantic-release
  - Default sandbox base_image now includes version tag instead of :latest

- ✨move sandbox Dockerfile out of backend assets, remove on-demand build
  ([`a72d34e`](https://github.com/thiesgerken/carapace/commit/a72d34e601898acb07b6be3ab8f8772a4c963d1b))

  - Move src/carapace/assets/Dockerfile → sandbox/Dockerfile
  - Remove get_sandbox_dockerfile() from bootstrap.py
  - Remove build_image() call and _BUILTIN_SANDBOX_IMAGE from server.py
  - Change SandboxConfig.base_image default to 'carapace-sandbox:latest'
  - Add build-only sandbox service to docker-compose.yml (profiles: build)
  - Add docker-sandbox CI/release jobs to build and push the image

### Other


- igns plans
  ([`d0c8b30`](https://github.com/thiesgerken/carapace/commit/d0c8b307ab8b9d3f4e3e312b0efbd2a07f311e58))

- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`7ece752`](https://github.com/thiesgerken/carapace/commit/7ece752ec76ef05a1a248b2dc0da4351359001d3))

### ⚡ Performance


- ⚡ perf: switch append_events and write_audit to append-only YAML
  ([`95ee976`](https://github.com/thiesgerken/carapace/commit/95ee976dc79f39a0b7286895309499046d3133ad))

### ♻️ Refactoring


- ♻️ refactor: split shared approval queue into typed tool/proxy queues
  ([`f928781`](https://github.com/thiesgerken/carapace/commit/f92878180d551c8ca73991fe4e4f11e116897c45))

- ♻️ refactor: wire security callbacks at session activation, not per-turn
  ([`8523ce3`](https://github.com/thiesgerken/carapace/commit/8523ce39ce62ab553829d19ce7aff75a2e2aea2f))

- ♻️ refactor: replace global security dicts with dependency injection
  ([`74c5c90`](https://github.com/thiesgerken/carapace/commit/74c5c90547f87d2d086f33f22e3116d875f8cd9b))

- ♻️ refactor: split session.py into session_manager.py and session_engine.py
  ([`6c6a604`](https://github.com/thiesgerken/carapace/commit/6c6a604dbb09cae74c589b09d6a780e82b16319e))

  - session_manager.py: SessionManager (pure file I/O, no async)
  - session_engine.py: SessionSubscriber, ActiveSession, SessionEngine (lifecycle, orchestration)
  - session.py: backward-compatible re-export shim
  - Update test mock targets to carapace.session_engine.Sentinel

## v0.20.0 (2026-03-14)


### 🔒 Security


- 🔒 security: make CORS origins configurable, default to localhost:3000
  ([`23d5247`](https://github.com/thiesgerken/carapace/commit/23d5247e0007d3ecb9bc4137b20211c21fc8664f))

  - Add cors_origins field to ServerConfig (default: ["http://localhost:3000"])
  - Move CORS middleware setup into lifespan so it reads from config
  - Replaces previous allow_origins=["*"]

### ♻️ Refactoring


- ♻️ refactor: move SLASH_COMMANDS to ws_models, eliminate all deferred imports
  ([`8ad0990`](https://github.com/thiesgerken/carapace/commit/8ad09900515d03b798e0b57474910b28c890ed95))

  - Move _SLASH_COMMANDS from server.py to ws_models.py as SLASH_COMMANDS
  - Hoist deferred imports to module level in session.py (MemoryStore, run_agent_turn, SLASH_COMMANDS)
  - Hoist deferred imports to module level in commands.py (MemoryStore, UserVouchedEntry)
  - No circular dependencies existed — the deferred imports were unnecessary

- ♻️ refactor: DockerRuntime explicitly inherits ContainerRuntime Protocol
  ([`ff0f471`](https://github.com/thiesgerken/carapace/commit/ff0f4718163d1c66385ca8db14035287133c39d7))

- ♻️ refactor: remove legacy Matrix mode, extract _resolve_pending helper
  ([`c7fbed2`](https://github.com/thiesgerken/carapace/commit/c7fbed20302f656ba8a15c703d87329def1ba57c))

  - Remove dual code paths (engine vs standalone) from MatrixChannel
  - Make engine parameter required
  - Delete legacy-only methods: _run_turn, _run_turn_locked, _keep_typing, _build_deps, _room_lock
  - Extract _resolve_pending() to deduplicate approve/deny slash commands
  - Update all Matrix tests to use mock SessionEngine
  - Net: -220 lines

### Other


- 🔥 cleanup: delete dead _resolve_path and its tests
  ([`a52ac7a`](https://github.com/thiesgerken/carapace/commit/a52ac7a44eb1c26dd2c420bce2d88507065f27af))

- 📝 docs: clarify stdlib logging import in server.py
  ([`d0a4140`](https://github.com/thiesgerken/carapace/commit/d0a4140c7b229d05babce9377c817d42e41280c7))

- 🏷️ types: HistoryMessage.role as Literal instead of plain str
  ([`31ea104`](https://github.com/thiesgerken/carapace/commit/31ea104433a0f07a0c24580a43f5cb6d0774c8a5))

- 📝 docs: add deferred-import ban to coding guidelines
  ([`6c5d7be`](https://github.com/thiesgerken/carapace/commit/6c5d7be834c3ffec61a4ac115ba259477b03fcda))

### 🔧 Configuration


- 🔧 style: add missing future annotations to runtime.py
  ([`9b41830`](https://github.com/thiesgerken/carapace/commit/9b41830b84ff7e42d77b4ad27d1c28beb1dc4890))

### ✨ Features


- ✨ feat: render Matrix /usage report as Markdown tables
  ([`815fc9f`](https://github.com/thiesgerken/carapace/commit/815fc9fc366899124b1317b04333cd1b8a0f34f8))

### 🐛 Bug Fixes


- 🐛 fix: convert cost string to float before formatting in Matrix /usage command
  ([`011e68e`](https://github.com/thiesgerken/carapace/commit/011e68e09fa3706ce5d0a0d0ae07b5a7d2fb6c1d))

## v0.19.1 (2026-03-14)


### 🐛 Bug Fixes


- 🐛 fix: echo slash commands as user_message so they appear in the UI
  ([`f29a715`](https://github.com/thiesgerken/carapace/commit/f29a7157c7c3d8c27a8108eb6e6511e5106123cf))

## v0.19.0 (2026-03-14)


### ✨ Features


- ✨ refactor session handling (#45)
  ([`d07cd03`](https://github.com/thiesgerken/carapace/commit/d07cd0370f0567e4aec2164e09070a5cd2bb3fcf))

  * ✨ refactor session handling

  * 🐛 remove bad session / security fallbacks

  * avoid double websocket subs

  * 🐛 fix read method to check for file existence correctly

  * ca certs in sandbox

  * fix bugs due to refactor

  * more tests

  * play with matrix verbosity

  * fix valueerror

  * fix typing

  * fix tests without anthropic key

  * ♻️  refactor matrix.py into multiple files

  * adjust style guide

  * fix typing issues

## v0.18.4 (2026-03-08)


### 🐛 Bug Fixes


- 🐛 fix tests
  ([`e2c059b`](https://github.com/thiesgerken/carapace/commit/e2c059b919274089c7b06e9fce229fab0b0241a2))

## v0.18.3 (2026-03-08)


### 🐛 Bug Fixes


- 🐛 focus textarea on mount and add title attribute for session display
  ([`e447382`](https://github.com/thiesgerken/carapace/commit/e4473822577c1e27dd01aa1f04452109627fd0ef))

## v0.18.2 (2026-03-08)


### Other


- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`16346e8`](https://github.com/thiesgerken/carapace/commit/16346e8139abf3a787bdf4ab742d1f122bcf7b3e))

## v0.18.1 (2026-03-08)


### 🐛 Bug Fixes


- 🐛 fix linter issues
  ([`d21115c`](https://github.com/thiesgerken/carapace/commit/d21115cf5d080f401de4d93539c1307a25c2f89b))

- 🐛 fix react lints
  ([`e9f3c69`](https://github.com/thiesgerken/carapace/commit/e9f3c69048bb89e0a1dd61a669c9c75d1a6b83a0))

- 🐛 fix dependency in submit callback to use queuedMessage instead of hasQueuedMessage
  ([`d95d9ef`](https://github.com/thiesgerken/carapace/commit/d95d9ef0b6766286b9d48d1359435adcbf784123))

## v0.18.0 (2026-03-08)


### Other


- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`85d8e88`](https://github.com/thiesgerken/carapace/commit/85d8e88413d85851663caab528af31a95f93b048))

## v0.17.1 (2026-03-08)


### 🐛 Bug Fixes


- 🐛 don't immediately append queued messages to history
  ([`9d6b55a`](https://github.com/thiesgerken/carapace/commit/9d6b55a8a481618c24c52ba5b891e102bc63cfa9))

### ✨ Features


- ✨ title generation
  ([`52149c3`](https://github.com/thiesgerken/carapace/commit/52149c3245c982bffc43a655b6eb344ceabf167a))

## v0.17.0 (2026-03-08)


### Other


- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`06df22e`](https://github.com/thiesgerken/carapace/commit/06df22ef29d1443374f9d5f870f47a078a2fc920))

## v0.16.0 (2026-03-08)


### Other


- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`abfab2e`](https://github.com/thiesgerken/carapace/commit/abfab2e299d3004fad5a211a4b89295e04f11e7c))

## v0.15.0 (2026-03-08)


### ✨ Features


- ✨ show a gauge with current session size
  ([`472e730`](https://github.com/thiesgerken/carapace/commit/472e73027f3848cad6aafa88fae5048764b68551))

- ✨ add queued message handling and interrupt functionality to chat view
  ([`4093130`](https://github.com/thiesgerken/carapace/commit/40931308f2225d7a9b4f0289552bf51b8cb1b84c))

- ✨ hold session id in url param
  ([`05437c3`](https://github.com/thiesgerken/carapace/commit/05437c3d5664a62cbdbcb8609320311ea9f92eb4))

- ✨ autocomplete for slash commands
  ([`18893d2`](https://github.com/thiesgerken/carapace/commit/18893d2699419fe784abbf47e6b60cabfd8b3f8e))

- ✨ add slash command autocomplete feature to chat input
  ([`03dc93d`](https://github.com/thiesgerken/carapace/commit/03dc93d7239a2886d3d38586748c396964d46dbb))

## v0.14.0 (2026-03-08)


### ✨ Features


- ✨ stop button to cancel agent
  ([`675d133`](https://github.com/thiesgerken/carapace/commit/675d1334c7950704321873a65f4f8ee4829871f7))

### 🐛 Bug Fixes


- 🐛 play around with approval options
  ([`3122dfc`](https://github.com/thiesgerken/carapace/commit/3122dfc796c4b1c365a1109a9e01b269286fa044))

## v0.13.0 (2026-03-08)


### 🐛 Bug Fixes


- 🐛 escalation for eicar.com did not work
  ([`8704fd6`](https://github.com/thiesgerken/carapace/commit/8704fd6ffad52611e7f008cecc2e035eacd6c711))

- 🐛 escalation for eicar.com did not work
  ([`364125f`](https://github.com/thiesgerken/carapace/commit/364125f84b1ee4ddfcaf43c588213a716a2ed57f))

### Other


- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`f3de4df`](https://github.com/thiesgerken/carapace/commit/f3de4dfdb42d697f7b32ca7086466b30df040d52))

## v0.12.1 (2026-03-08)


### 🐛 Bug Fixes


- 🐛 restore approvals on UI reload
  ([`143e850`](https://github.com/thiesgerken/carapace/commit/143e8507ae7212fb801c87c1cd696c2d1299f74c))

- 🐛 fix tool call approval
  ([`125c850`](https://github.com/thiesgerken/carapace/commit/125c8506f3e7e204dbaee993c2273c455898937d))

- 🐛 make the sidebar slightly wider for the new ids
  ([`d70615c`](https://github.com/thiesgerken/carapace/commit/d70615cfbf99933b8ff5fe937e810b2ee4d438cd))

### Other


- document linting in agents.md
  ([`4c40804`](https://github.com/thiesgerken/carapace/commit/4c4080413d5ecf963c7a15edcd917adf5c0c2388))

- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`bb722fc`](https://github.com/thiesgerken/carapace/commit/bb722fc9fef0269f5cd81d003e167988d1075928))

### ✨ Features


- ✨ add a test command to test sentinel escalation
  ([`09026f5`](https://github.com/thiesgerken/carapace/commit/09026f5469b4583df1cfaf007fb2aff89dd5cb20))

- ✨ better readable session ids
  ([`89df1f1`](https://github.com/thiesgerken/carapace/commit/89df1f159c681a80eadb8a49a7cc2ab93d23cec1))

## v0.12.0 (2026-03-08)


### 🐛 Bug Fixes


- 🐛 use short keys for formatting args summary in ToolCallBadge
  ([`73c6ccd`](https://github.com/thiesgerken/carapace/commit/73c6ccd7e6bb65816e9896b70cfca5cb20792d29))

- 🐛 persist proxy requests in events
  ([`c903f4f`](https://github.com/thiesgerken/carapace/commit/c903f4ff91ca2168c51c6540bb7e471099b25213))

- 🐛 fix(frontend): tool call spinner not clearing when proxy_domain intercepts result
  ([`fd1f897`](https://github.com/thiesgerken/carapace/commit/fd1f8977e84c7f48558e028770ca0aded19c74e4))

### ✨ Features


- ✨ docs: add commit message convention using gitmoji
  ([`3ebe25b`](https://github.com/thiesgerken/carapace/commit/3ebe25b5cefaa22cd845e5214f258f681380191a))

- ✨ Update datetime handling to use UTC in models and session management
  ([`004c8db`](https://github.com/thiesgerken/carapace/commit/004c8db338f18a315a7d6df8bd6c3a7aef2799ab))

## v0.11.0 (2026-03-08)


### ✨ Features


- ✨ Rename Bouncer to Sentinel
  ([`49819d8`](https://github.com/thiesgerken/carapace/commit/49819d828ccdd319188b13cef529d08557c97bc6))

## v0.10.0 (2026-03-08)


### Other


- relock
  ([`362fd15`](https://github.com/thiesgerken/carapace/commit/362fd1555d37d26d116fb4575ed2a875589c9b98))

### ✨ Features


- ✨ Enhance message handling in ChatView to support tool results and additional message details
  ([`1600386`](https://github.com/thiesgerken/carapace/commit/1600386480da69d0f935493642307ea3e1dd579a))

- ✨ Add tool result handling and notifications across components
  ([`080c21a`](https://github.com/thiesgerken/carapace/commit/080c21a2f1ecc523735962bf00683b4d00a774f8))

## v0.9.0 (2026-03-08)


### ✨ Features


- ✨ Tool/Proxy Approval via Shadow-Agent  (#39)
  ([`463f10e`](https://github.com/thiesgerken/carapace/commit/463f10ed7daf095c82ad34666f3862eccf8f77cb))

  * ✨ Security v2

  * 🛡️ Update SECURITY.md to enhance security guidelines and clarify agent behavior regarding prompt injection and accidental rogue actions. Added detailed sections on command scrutiny, sandbox operations, and user escalation protocols.

  * Update docs/credentials.md

  Co-authored-by: Copilot <175728472+Copilot@users.noreply.github.com>

  * Convert `test_format_domain_escalation` to plain `def` (#40)

  * Initial plan

  * Remove async from test_format_domain_escalation (no await expressions)

  Co-authored-by: thiesgerken <7550099+thiesgerken@users.noreply.github.com>

  ---------

  Co-authored-by: copilot-swe-agent[bot] <198982749+Copilot@users.noreply.github.com>

  * Include SECURITY.md in sandbox workspace mounts (#42)

  * Fix _build_mounts to include SECURITY.md as readonly mount

  * Remove dead `bouncer_messages` field from `SessionSecurity` (#43)

  * Remove dead bouncer_messages field from SessionSecurity

  * Remove unused asyncio.Lock from SessionSecurity (#44)

  * Remove unused _lock (asyncio.Lock) and asyncio import from SessionSecurity

  * Move function-level imports to module level in server, models, and matrix (#41)

  * fix: move function-level imports to module level in server.py, models.py, matrix.py

  * remove sandbox=on

  * Handle session retrieval with fallback to initialization in MatrixChannel

  * Verbessere die Funktion get_host_ip, um die IP-Adresse des Hosts im Docker-Netzwerk zu ermitteln und eine Fallback-Option für die Gateway-IP hinzuzufügen.

  * Füge Audit-Logging für Benutzerentscheidungen hinzu und verbessere die Protokollierung von Toolaufrufen

  * Vereinfache die Entscheidungslogik für Proxygenehmigungen und aktualisiere das Modell zur Unterstützung neuer Entscheidungen

  * Füge Referenzzählung für Sicherheitssitzungen hinzu und verbessere die Sitzungsbereinigung

  * make the read/write/patch ops work in the sandbox

  * Add domain info callbacks and switch history/usage/event storage to YAML format

  * fix yaml

  * Remove dash from detail display in ToolCallBadge component

  Co-authored-by: Copilot <198982749+Copilot@users.noreply.github.com>

### Other


- Enhance Python style guidelines to encourage clarity in user requests. Added a note advising users to avoid technical debt and seek better solutions.
  ([`ab6b668`](https://github.com/thiesgerken/carapace/commit/ab6b66818b988ac93a06d98353616a111ef82386))

## v0.8.0 (2026-02-22)


### ✨ Features


- ✨ Matrix as additional frontend (#37)
  ([`bb92183`](https://github.com/thiesgerken/carapace/commit/bb92183d2d3711d76c462275ff7c742a48099c24))

  * ✨ Matrix as additional frontend

  * pass-through matrix pw

  * make it possible to auth using password instead of token

  * improve error handling in matrix code

  * Enhance Matrix channel command handling and logging

  - Updated approval command from `/approve` to `/allow` for clarity.
  - Improved session command result formatting to include activated, disabled rules, approved credentials, and allowed domains.
  - Refactored agent turn execution to run as a background task, allowing for immediate response to new events.
  - Added a new method `_run_turn_locked` to manage room-specific locks during agent turns.
  - Set logging levels for additional libraries to WARNING in server.py for better log management.

  * fix tests

### Other


- 💚 add docker builds to the ci (#38)
  ([`fcb36f6`](https://github.com/thiesgerken/carapace/commit/fcb36f62ccc5cd0d22bf9d4bc6bf67bf92314fff))

## v0.7.1 (2026-02-22)


### 🐛 Bug Fixes


- 🐛 bad gitignore
  ([`36ada40`](https://github.com/thiesgerken/carapace/commit/36ada4061bc0fdc65a522999424f66d7dfd9d8e3))

## v0.7.0 (2026-02-22)


### ✨ Features


- ✨ route sandbox http calls through the backend using a CONNECT proxy (#36)
  ([`58b96e8`](https://github.com/thiesgerken/carapace/commit/58b96e88329a7184a7cdf4263e96216eaa52336b))

  * ✨ route sandbox http calls through the backend using a CONNECT proxy

  * ✨ Enhance Docker configuration and logging for sandbox environment

  - Added `tty` support in `docker-compose.yml` for the carapace service.
  - Updated volume mappings to include the source directory for carapace.
  - Introduced `ANTHROPIC_API_KEY` as an environment variable in the Docker setup.
  - Changed frontend port mapping from 3000 to 3001.
  - Enhanced logging in `server.py` to display network interface information and resolved sandbox network names.
  - Improved `DockerRuntime` to manage network names and ensure correct network connections for containers.
  - Updated `SandboxManager` to dynamically resolve and log proxy URLs based on the container's network settings.

  * ✨ Implement proxy domain approval mechanism in sandbox

  - Added support for proxy domain approval requests in the chat view and message components.
  - Introduced `handleProxyApproval` function to manage user decisions on proxy access.
  - Updated `SandboxManager` to handle domain approval requests and decisions, integrating with the proxy server.
  - Enhanced WebSocket communication to facilitate proxy approval responses.
  - Improved session management to display allowed domains and their scopes in the CLI.
  - Refactored related components to ensure seamless integration of the new approval workflow.

  * Fix content length in forbidden response for proxy policy

  * Enhance ProxyServer to filter hop-by-hop headers and enforce connection closure. Updated header processing to drop existing Connection headers and append "Connection: close" to prevent HTTP/1.1 keep-alive issues.

  * Fix session token management and enhance error handling in SandboxManager

  - Evict orphaned tokens from previous failed attempts to ensure clean session initialization.
  - Refactor IP resolution logic to include error handling, ensuring proper cleanup on failure.
  - Maintain existing functionality for proxy URL generation and container configuration.

  * Refactor SandboxManager proxy configuration in tests

  - Simplified the instantiation of SandboxManager in test cases by removing the hardcoded proxy URL.
  - Updated the `_build_proxy_env` method calls to include the proxy URL as a parameter, enhancing flexibility in testing proxy configurations.
  - Ensured that the tests maintain their functionality while improving code clarity and maintainability.

  * Refactor ProxyServer domain checking methods in tests

  - Renamed `_check_domain` method to `_is_allowed` for clarity in the ProxyServer class.
  - Updated test cases to reflect the new method name while maintaining existing functionality.
  - Improved code readability and consistency in domain approval checks.

  * Remove unused proxyApprovalState ref

  The proxyApprovalState ref was written to but never read. Proxy approval state is tracked directly on message objects via the decision property, making this ref redundant.

  Applied via @cursor push command

  * Fix proxy approval allow-all CLI choices

  Co-authored-by: Thies Gerken <thiesgerken@users.noreply.github.com>

  * Enhance WebSocket error handling and improve test setup

  - Added contextlib suppression to handle unexpected WebSocket errors gracefully by closing the connection with code 1011.
  - Updated the test server setup to return an empty list for domain info in the SandboxManager, improving test reliability.

  * fix: preserve proxy approvals across container recreation

  ---------

  Co-authored-by: Cursor Agent <cursoragent@cursor.com>

## v0.6.0 (2026-02-22)


### ✨ Features


- ✨ Docker sandboxing for sessions (#35)
  ([`ce5ca5b`](https://github.com/thiesgerken/carapace/commit/ce5ca5bcc4a7e94e89c5e09c01088e46dedc6e6c))

  * ✨ Docker sandboxing for sessions

  * ✨ Update logging guidelines in AGENTS.md and python-style.mdc

  - Added a section on logging best practices, specifying the exclusive use of `loguru` over stdlib `logging`.
  - Included instructions for importing `loguru` and using f-strings in log calls for improved readability and performance.

  * add loguru

  * Refactor logging to use loguru across the codebase

  - Replaced instances of the standard logging library with loguru for improved logging capabilities.
  - Updated log messages to utilize f-strings for better readability and performance.
  - Removed the `enabled` field from `SandboxConfig` as it is no longer needed.
  - Enhanced error handling and logging in the Docker runtime and sandbox manager for better debugging and maintenance.

  * ✨ Enhance Docker runtime with network management

  - Added a method to ensure the existence of Docker networks before container creation.
  - Improved the DockerRuntime class to manage and log network creation, enhancing the overall functionality of the sandbox environment.

  * Fix input prompt formatting in approval request to escape brackets for proper display

  * Refactor sandbox configuration and Docker integration

  - Removed the carapace-sandbox-image service from docker-compose.yml and deleted its Dockerfile.
  - Updated SandboxConfig to allow an empty base_image, enabling auto-building from a bundled Dockerfile.
  - Introduced a method to read the bundled Dockerfile content in bootstrap.py.
  - Enhanced DockerRuntime with a build_image method to build the sandbox image from the bundled Dockerfile.
  - Adjusted server lifespan logic to build the sandbox image if no base_image is specified in the configuration.

  * Enhance error handling and logging in sandbox and Docker runtime

  - Introduced custom exceptions `ContainerGoneError` and `SkillVenvError` for better error management in the sandbox environment.
  - Updated the `DockerRuntime` and `SandboxManager` classes to handle these exceptions, improving robustness during container execution and skill virtual environment building.
  - Enhanced logging to provide clearer insights into errors and warnings related to container management and skill activation.

  * Set logging levels for specific libraries to WARNING in server.py

  - Adjusted logging configuration to set the logging level to WARNING for the "httpcore", "httpx", and "docker" libraries, improving log clarity and reducing verbosity.

  * Enhance logging configuration in server.py

  - Added "anthropic" and "websockets" to the list of libraries with WARNING logging level.
  - Introduced a custom emoji patcher for log records to replace specific prefixes with emojis, improving log readability.

  * Update Python style guidelines in python-style.mdc

  - Clarified the use of Pydantic `BaseModel` for structured data, removing references to stdlib `@dataclass`.
  - Introduced the use of `Annotated[type, Field(...)]` for field metadata and defaults, emphasizing correct usage.
  - Specified that non-nullable fields should not be assigned `None` with `# type: ignore`, promoting better type safety.
  - Updated guidance on avoiding mutable default arguments to use `Annotated` for consistency.

  * Refactor agent and sandbox management for improved structure and logging

  - Removed the local command execution fallback in favor of a more streamlined sandbox execution approach.
  - Enhanced the `Deps` class to utilize Pydantic's `BaseModel` and `Annotated` for better type safety and field management.
  - Updated the `SessionContainer` and `Mount` classes to inherit from `BaseModel`, ensuring consistent data handling.
  - Improved error handling in the agent's skill activation process with enhanced logging using `loguru`.
  - Adjusted server cleanup logic to ensure proper management of sandbox resources.

  * Rename `bash` tool to `shell` in agent.py for clarity and update command execution in DockerRuntime to use `bash` instead of `sh` for consistency in command handling.

  * Update Dockerfile to use specific version of uv and remove unnecessary apt-get commands

  * Update default server host in ServerConfig to allow external access

  * Improve WebSocket error handling in _chat_loop function

  - Added reconnection logic for both sending messages and reading server responses upon ConnectionClosed exceptions.
  - Enhanced user feedback during reconnection attempts to improve user experience.

  * Refactor WebSocket connection handling in cli.py

  - Updated the WebSocket connection logic to use the `websockets.asyncio.client` module directly for improved clarity and consistency.
  - Enhanced type hinting for the `_connect_ws` function to specify the return type as `ClientConnection`.

  * Refactor skill management in Deps class and server dependency building

  - Updated the `Deps` class to initialize `skill_catalog` and `activated_skills` with default empty lists for improved clarity and consistency.
  - Modified the `_build_deps` function in `server.py` to pass an empty list for `activated_skills`, ensuring proper initialization during dependency construction.

  * Add CARAPACE_HOST_DATA_DIR environment variable and update SandboxManager for host path handling

  - Introduced the `CARAPACE_HOST_DATA_DIR` environment variable in `docker-compose.yml` to specify the host data directory.
  - Updated `server.py` to retrieve and pass the host data directory to the `SandboxManager`.
  - Enhanced `SandboxManager` to handle host paths for bind mounts, ensuring correct path resolution when running in Docker.
  - Improved logging to provide feedback on host data directory overrides during sandbox initialization.

  * Implement skill name validation in SandboxManager

  - Added a regex-based validation function for skill names to ensure they are non-empty, start with an alphanumeric character, and contain only valid characters.
  - Integrated the validation function into the `activate_skill`, `_build_skill_venv`, and `save_skill` methods to enforce skill name rules and return appropriate error messages when invalid names are provided.
  - Refactored the `SessionContainer` class to initialize `activated_skills` with an empty list for consistency.

  * fix lint issues

  * Enhance documentation in agent.py for skill activation and command execution

  - Updated the prompt for skill activation to clarify the setup of a virtual environment.
  - Improved the docstring for the exec function to specify that it typically runs bash commands.
  - Removed the unused shell function to streamline the code.

  * Refactor session directory structure in SandboxManager

  - Changed the session directory structure to use a single 'workspace' directory for skills and temporary files.
  - Updated the relevant methods to reflect the new paths for skill and temporary directories, ensuring consistent handling of session data.

## v0.5.0 (2026-02-20)


### ✨ Features


- ✨ Implement token usage tracking and reporting (#34)
  ([`00fbd8e`](https://github.com/thiesgerken/carapace/commit/00fbd8eab83a2906cb6902064ce06e1ab65a15f8))

  * ✨ Implement token usage tracking and reporting

  - Added a new `UsageTracker` class to monitor token usage across models and categories.
  - Introduced a `/usage` command in the CLI to display token usage statistics.
  - Enhanced the `classify_operation` and `check_rules` functions to record usage data.
  - Updated the frontend to visualize usage data with a new `UsageView` component.
  - Bumped `carapace` version to 0.4.0 to reflect these changes.

  * ✨ Enhance usage tracking and reporting features

  - Updated `pyproject.toml` to specify version constraints for dependencies.
  - Added new `costs` field to `UsagePayload` for tracking costs associated with token usage.
  - Implemented cost estimation in `UsageTracker` to calculate total costs based on token usage.
  - Enhanced frontend components to display command results and usage costs.
  - Improved session management to persist usage data and events for better tracking.
  - Updated CLI to include costs in the `/usage` command output.

  This commit builds upon the previous implementation of token usage tracking, providing a more comprehensive view of resource utilization.

## v0.4.0 (2026-02-20)


### ✨ Features


- ✨ Add a web frontend (#31)
  ([`4d7e028`](https://github.com/thiesgerken/carapace/commit/4d7e0281acdb0fef1c252d0ce818fe6afc98ba6e))

## v0.3.0 (2026-02-19)


### ✨ Features


- ✨ Revamp Carapace architecture with server and CLI client integration (#30)
  ([`6644bfe`](https://github.com/thiesgerken/carapace/commit/6644bfe8bca5e79801320c76fed669e1775fa4f5))

  * ✨ Revamp Carapace architecture with server and CLI client integration

  - Introduced a FastAPI server for handling requests and WebSocket connections.
  - Updated CLI to connect to the server, replacing the previous interactive model.
  - Enhanced documentation in AGENTS.md and README.md to reflect new server and client structure.
  - Added bearer token authentication for secure communication between CLI and server.
  - Updated project dependencies to include FastAPI, Uvicorn, and WebSockets.
  - Version bump to 0.2.0 to signify major architectural changes.

  * ✨ Implement session locking in WebSocket chat handler

  - Added asyncio locks to manage concurrent access to session data, ensuring serialized agent turns.
  - Refactored chat_ws function to utilize session locks for loading and saving message history and session state.
  - Improved error handling and logging during agent execution.

  * 🧹 Clean up unused server URL function in CLI

  - Removed the `_server_url` function as it was no longer needed in the updated architecture.
  - Streamlined the code for better readability and maintenance.

  * ✨ Improve error handling for approval requests in CLI and server

  - Added exception handling for keyboard interruptions during approval requests in the CLI, ensuring a graceful denial message is displayed.
  - Updated server logic to handle interrupted approvals by marking them as denied and clearing pending requests, enhancing overall robustness.

  * Fix 5 bugs: WebSocket auth exception, token permissions, session lock cleanup, async input blocking, and verbose output routing

  - Use WebSocketException instead of HTTPException for WebSocket auth failures
  - Set token file permissions to 0600 for security
  - Clean up session locks on WebSocket disconnect to prevent memory leak
  - Use run_in_executor for approval prompt input to avoid blocking event loop
  - Route verbose tool call output via WebSocket instead of server stdout

  Applied via @cursor push command

  * Fix fire-and-forget WebSocket send by saving task references

  - Save created tasks in a set to prevent garbage collection
  - Add error handling to log WebSocket send failures
  - Cancel pending tasks on client disconnect
  - This ensures the server detects dropped clients and stops expensive LLM calls

  * pc

  * Refactor WebSocket chat handler for improved control flow and error handling

  - Changed return statement to break in command handling for better flow control.
  - Added a finally block to ensure session locks are cleaned up on disconnect.
  - Enhanced error handling for unexpected agent output types during message sending.

  * Enhance session management in WebSocket chat handler

  - Introduced an async context manager for session connections to manage locks more effectively.
  - Updated chat_ws function to utilize the new session connection management, ensuring proper lock handling during WebSocket interactions.
  - Improved error handling and cleanup on client disconnect to prevent memory leaks and ensure session integrity.

  ---------

  Co-authored-by: Cursor Agent <cursoragent@cursor.com>

### Other


- 💚 Update build command in pyproject.toml to include 'uv lock'
  ([`5cedc87`](https://github.com/thiesgerken/carapace/commit/5cedc87e2c8a74a142eaab058013e8993fcbdc45))

## v0.2.0 (2026-02-15)


### ✨ Features


- ✨ Integrate Logfire for enhanced logging and tracing
  ([`7c1ddeb`](https://github.com/thiesgerken/carapace/commit/7c1ddeb0cb5787fa0ff3f6883c3a9b2a2c0c1008))

  - Added `logfire` dependency to `pyproject.toml` and `uv.lock`.
  - Configured Logfire in the CLI to enable tracing based on user token.
  - Updated `CarapaceConfig` to include `logfire_token` field.
  - Modified example `config.yaml` to indicate where to set the Logfire token.

### Other


- 📝 Update README.md to include new security guideline for skills
  ([`83d90b1`](https://github.com/thiesgerken/carapace/commit/83d90b1f343811cdb8ffb278470680e3d8da4225))

  - Added a section emphasizing the importance of reviewing skills before installation, highlighting that skills are considered trusted code and the user's responsibility in managing them.

## v0.1.0 (2026-02-15)


### ✨ Features


- ✨ Update commit parser options in pyproject.toml
  ([`632eaf4`](https://github.com/thiesgerken/carapace/commit/632eaf494bc4a6a29472427323cd38efdcda368e))

  - Added major, minor, and patch tags for semantic release.
  - Enhanced commit parsing configuration to support emoji and text tags.

- ✨ Implement message replay functionality in chat session
  ([`dfe883b`](https://github.com/thiesgerken/carapace/commit/dfe883bfaededd25087aa887a282114b3b2dcda7))

  - Added `_replay_history` function to display previous conversation turns.
  - Introduced `--prev` option in the `chat` command to specify the number of previous turns to replay.
  - Updated response validation logic for improved readability.

- ✨ Add bootstrap module and initial asset files for Carapace (#28)
  ([`655e154`](https://github.com/thiesgerken/carapace/commit/655e154612384688fa5c25d6c20600de78ec1bd4))

  - Introduced `bootstrap.py` to ensure the creation of critical files and directories.
  - Added asset files including `config.yaml`, `CORE.md`, `SOUL.md`, `USER.md`, and rules in `rules.yaml`.
  - Implemented functionality to seed skills and manage data directory initialization in the CLI.

### Other


- 📝 Add Python coding style guide for carapace project
  ([`8f91cf2`](https://github.com/thiesgerken/carapace/commit/8f91cf2e2b65f36a1e277533d6cba3cf5470ade0))

- 📝 Add AGENTS.md for project overview, setup, code style, structure, testing, and CI details
  ([`b79fbbb`](https://github.com/thiesgerken/carapace/commit/b79fbbba67733067727b8e7c4a539b06fe8b3184))

- update readme
  ([`2f1daa1`](https://github.com/thiesgerken/carapace/commit/2f1daa15813b60241506afde11931881fd7d1e66))

- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`85552db`](https://github.com/thiesgerken/carapace/commit/85552db18aa94bd696bc879fefca3801aecc3f34))

- 📝 Add MIT LICENSE file (#3)
  ([`1226e36`](https://github.com/thiesgerken/carapace/commit/1226e3622ac8a65335b3eb16367104af3cdfa7a2))

  Co-authored-by: Cursor Agent <cursoragent@cursor.com>

- fix url in readme
  ([`f2ece16`](https://github.com/thiesgerken/carapace/commit/f2ece16e3f29036c1b85d95b2c3fa39ab88fc564))

- 📝 Enrich README with getting started guide and demo output (#1)
  ([`593d395`](https://github.com/thiesgerken/carapace/commit/593d3952b870e44ebd94f5f376ca2cb31b5b5318))

  * 📝 Enrich README with getting started guide and demo output

  Add installation, running, and configuration instructions. Include a pruned demo session showcasing the interactive CLI.

  Co-authored-by: Cursor <cursoragent@cursor.com>

  * tired of that

  ---------

- 💚 Fix CI: add pytest dev dep and gitmoji PR title check (#2)
  ([`7e0ba76`](https://github.com/thiesgerken/carapace/commit/7e0ba766fd6b13f7c68b191236fce903c06bb48f))

  * 💚 Fix CI: add pytest dev dep and gitmoji PR title check

  - Add pytest to dependency-groups so `uv sync --dev` installs it
  - Add pr-title job to enforce gitmoji prefix on PR titles

  Co-authored-by: Cursor <cursoragent@cursor.com>

  * 💚 Disable color in CLI test runner to fix CI assertions

  * 💚 Use NO_COLOR env var instead of color kwarg in test runner

  * 💚 Strip ANSI escape codes in CLI test assertions

  ---------

## v0.0.0 (2026-02-14)


### Other


- update build command in pyproject.toml to install uv before building
  ([`b67255c`](https://github.com/thiesgerken/carapace/commit/b67255ca8a177da256fcbcfaf40b1d84be8dafa8))

- add ci
  ([`dd57de9`](https://github.com/thiesgerken/carapace/commit/dd57de9d6a1be3ba413bd8c20ed12d45fb5032e4))

- add tests, add precommit, fix lints
  ([`3adb428`](https://github.com/thiesgerken/carapace/commit/3adb4283ae1ec76dc69a4df62bddd7db9a36985d))

- let opus code a PoC
  ([`7e2f876`](https://github.com/thiesgerken/carapace/commit/7e2f876aa755be5176601f7a5fa217cca59f0694))

- add docs and brainstorming
  ([`54eacb2`](https://github.com/thiesgerken/carapace/commit/54eacb2091b136948e35bdd3ae7e3d305a4a1330))
