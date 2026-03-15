# CHANGELOG


## v0.34.0 (2026-03-15)

### ✨

- ✨ feat: switch sandbox image to python:3.14-slim-trixie
  ([`031837a`](https://github.com/thiesgerken/carapace/commit/031837aed52d59504c41a5cec5d469e60cf3c641))

Share the base image with the server container so layers are deduplicated on disk. Replace apk with
  apt-get, copy uv binary from the official image, and drop redundant python3/py3-pip/
  ca-certificates packages.


## v0.33.4 (2026-03-15)

### 🐛

- 🐛 fix: chmod writable sandbox dirs instead of chown (K8s storage compat)
  ([`bf924de`](https://github.com/thiesgerken/carapace/commit/bf924deec7a6a25c08eaf4daa072e63849bcdb8e))


## v0.33.3 (2026-03-15)

### Other

- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`bfff432`](https://github.com/thiesgerken/carapace/commit/bfff432f5533d710c021b11870f41d447f011daf))


## v0.33.2 (2026-03-15)

### 🐛

- 🐛 fix: add initContainer to chown writable PVC dirs in K8s sandbox pods
  ([`2452b4a`](https://github.com/thiesgerken/carapace/commit/2452b4a42cfc5e6b0b378eee649e0f5dc018df3c))

- 🐛 fix: prevent mobile header from scrolling away in long conversations
  ([`71e155d`](https://github.com/thiesgerken/carapace/commit/71e155d12e062844f9b8e2770c0d594ae6e34583))

Replace h-full with flex-1 min-h-0 on ChatView root so the messages area properly constrains to
  remaining viewport height after the mobile header, enabling overflow-y-auto instead of growing
  past the screen.


## v0.33.1 (2026-03-15)

### 🐛

- 🐛 make sure to refetch matrix token if user_id changes + accept pending invites at startup
  ([`eb553c9`](https://github.com/thiesgerken/carapace/commit/eb553c979c02f94ac70e15a85f48950f19ca0e7e))


## v0.33.0 (2026-03-15)

### ✨

- ✨ feat: log startup message in sandbox containers before sleep
  ([`3059171`](https://github.com/thiesgerken/carapace/commit/30591715528dff44b126a9a8a35399f7efb47110))


## v0.32.3 (2026-03-15)

### 🐛

- 🐛 fix: update k8s_owner_ref to True for sandbox pods
  ([`6c8c72d`](https://github.com/thiesgerken/carapace/commit/6c8c72dd84d0fe85aa39f9aee551c8fd9b0d42f6))


## v0.32.2 (2026-03-15)

### 🐛

- 🐛 fix: add ArgoCD tracking annotation to sandbox pods for app discovery
  ([`b158fd2`](https://github.com/thiesgerken/carapace/commit/b158fd2b9c560c4615fc1811f90f12b046688cc0))


## v0.32.1 (2026-03-15)

### 🐛

- 🐛💚 update pre-commit and actions
  ([`fd4a265`](https://github.com/thiesgerken/carapace/commit/fd4a2656728fd77106d437bfe44bbe4b954731ca))


## v0.32.0 (2026-03-15)

### Other

- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`0249cb0`](https://github.com/thiesgerken/carapace/commit/0249cb007d705636301b3cf1e858af6816936692))


## v0.31.0 (2026-03-15)

### ✨

- ✨ better url guessing in ui
  ([`2bece2e`](https://github.com/thiesgerken/carapace/commit/2bece2e77749251d18309ed167b7a459ec3fdb2a))

- ✨ feat: make sandbox pod ownerReference configurable (default off)
  ([`7219c8f`](https://github.com/thiesgerken/carapace/commit/7219c8f5f2885d1e6e60917b9bb2f1eb8efeda8f))


## v0.30.2 (2026-03-15)

### Other

- 📝 docs: add NetworkPolicy security warnings to Kubernetes docs
  ([`373634b`](https://github.com/thiesgerken/carapace/commit/373634bab2010360efee5d4ce0c5bf1ba9025aac))

### 🐛

- 🐛 fix: use Always restart policy for sandbox pods and rename to carapace-sandbox-*
  ([`d0c3335`](https://github.com/thiesgerken/carapace/commit/d0c33351ae5746ff6fecc2f9ba6a71d12468d88c))


## v0.30.1 (2026-03-15)

### 🐛

- 🐛 fix: move kubernetes from optional to regular dependency
  ([`a0a8d94`](https://github.com/thiesgerken/carapace/commit/a0a8d942fbf8baf052ba13d6a0b770de04f58ecf))


## v0.30.0 (2026-03-15)

### Other

- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`97d9cb6`](https://github.com/thiesgerken/carapace/commit/97d9cb6dbbf7779613362eaafee95f8b93b08182))


## v0.29.0 (2026-03-15)

### ✨

- ✨ feat(chart): support config.yaml via ConfigMap
  ([`6c19915`](https://github.com/thiesgerken/carapace/commit/6c19915f89ed9177dca024d41570af82f57fb574))

- ✨ feat: replace auto-generated token with CARAPACE_TOKEN env var
  ([`0f45c40`](https://github.com/thiesgerken/carapace/commit/0f45c40b5af2346a6b90a2f845e227a3b79fa7cd))


## v0.28.1 (2026-03-15)

### Other

- 📝 docs: add Helm chart install command to release notes
  ([`2cf0c30`](https://github.com/thiesgerken/carapace/commit/2cf0c304278727c437c3293c4d701f0c62efb967))

### 🐛

- 🐛 fix: use version_pattern for Chart.yaml version bumping and override helm package version
  ([`df66025`](https://github.com/thiesgerken/carapace/commit/df6602514ae6578b81d846fe1e1efb95d1f29287))


## v0.28.0 (2026-03-15)

### ✨

- ✨ feat: Gateway API HTTPRoute, OCI chart publishing, PVC finalizers, default resources
  ([`7b4dba6`](https://github.com/thiesgerken/carapace/commit/7b4dba6f3a5984dfc6cba3a43dc7953f79472d1b))


## v0.27.0 (2026-03-15)

### Other

- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`9c3e094`](https://github.com/thiesgerken/carapace/commit/9c3e0941f6915cee642ea52c47ca953d3f22f42b))


## v0.26.0 (2026-03-15)

### ✨

- ✨ feat: add Helm chart for Kubernetes deployment
  ([`b9ef7cd`](https://github.com/thiesgerken/carapace/commit/b9ef7cdc5bb146ba63bab2c34932673c24b0700f))

- ✨ feat: mount all API endpoints under /api prefix
  ([`d660c9b`](https://github.com/thiesgerken/carapace/commit/d660c9b71b4376355ceadf5b612e7562a6df00c7))


## v0.25.3 (2026-03-14)

### Other

- 📝 docs: clarify that the agent has internet access (security-gated)
  ([`e4b550b`](https://github.com/thiesgerken/carapace/commit/e4b550b0456d14e2e51d9c82663a2f403cfe22a0))

### 🐛

- 🐛 no need to add that to soul.md
  ([`7fc25bb`](https://github.com/thiesgerken/carapace/commit/7fc25bb429442db6ba64b3fbd71ec5916b91e66c))


## v0.25.2 (2026-03-14)

### Other

- No sandbox versioning automatically
  ([`fcc65ef`](https://github.com/thiesgerken/carapace/commit/fcc65efcd318cc7d1085f37cd57f0b8bf8ced15f))

- Runtime stuff
  ([`332a43d`](https://github.com/thiesgerken/carapace/commit/332a43d14aca93c2636fe0a01c1e02cd918876aa))

### 🐛

- 🐛 fix linter issues due to missing stuff in the protocol
  ([`1e8c1eb`](https://github.com/thiesgerken/carapace/commit/1e8c1eba6c2dabb7917df9524eaa33aa6d979d1c))


## v0.25.1 (2026-03-14)

### Other

- Lint
  ([`f4262a9`](https://github.com/thiesgerken/carapace/commit/f4262a91c59261825fffa6e2a53c8e046ec6c9d7))

- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`49694a9`](https://github.com/thiesgerken/carapace/commit/49694a98a7e5ced9e60f15f5d4ab8738e5e64f2c))

### 🐛

- 🐛 fix cors mounting
  ([`18af792`](https://github.com/thiesgerken/carapace/commit/18af792ec2d3f57fa5142283ce370c687cab55c5))

- 🐛 fix usagetracker import issues
  ([`07979a6`](https://github.com/thiesgerken/carapace/commit/07979a685d099106470fc1704b696f261afcfe90))


## v0.25.0 (2026-03-14)

### Other

- 💄 lint issues
  ([`c3673b5`](https://github.com/thiesgerken/carapace/commit/c3673b5f7b76405b1664659be549757725513a0e))

- 📋 update TODO.md: refine Sandbox/Docker and Channels sections, remove outdated tasks
  ([`932c985`](https://github.com/thiesgerken/carapace/commit/932c9851c97bad80c7a22c2e7abdf8073417fe15))

### ✨

- ✨ feat: add Kubernetes sandbox runtime and deployment manifests
  ([`547855b`](https://github.com/thiesgerken/carapace/commit/547855b50044745f98def3af38666d53be9a8983))

- KubernetesRuntime implements ContainerRuntime protocol using k8s API - Sandbox pods use PVC
  subPaths, ownerReferences, NetworkPolicy isolation - Runtime selection via config.sandbox.runtime
  (docker|kubernetes) - Kustomize manifests in k8s/ (namespace, PVC, RBAC, deployments, ingress) -
  Full deployment guide at docs/kubernetes.md - 19 unit tests with mocked k8s API - Add
  pytest-asyncio with asyncio_mode=auto


## v0.24.0 (2026-03-14)

### Other

- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`d733ba2`](https://github.com/thiesgerken/carapace/commit/d733ba2f6206245e4a457ca2d6d39693bab36956))

- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`7959a5e`](https://github.com/thiesgerken/carapace/commit/7959a5e710c1839a01b4af71a11f29297127460b))


## v0.23.0 (2026-03-14)

### Other

- Fix CI
  ([`5e26f54`](https://github.com/thiesgerken/carapace/commit/5e26f5438773957df27ff34023060ef479933b6d))

- 📋 update skills.md, remove mentions of skill dockerfiles
  ([`af9923a`](https://github.com/thiesgerken/carapace/commit/af9923a2ff71f1f9e307a44ff178f816f277fbf3))

- 📝 docs: add commit-before-asking convention to AGENTS.md
  ([`3ce548e`](https://github.com/thiesgerken/carapace/commit/3ce548e0d3122781961961a17ecf11f0592ebc0c))

- 📝 docs: reorder README — demo first, dev setup last
  ([`908ce2f`](https://github.com/thiesgerken/carapace/commit/908ce2f979c0593b5235545e12b0bbb9668d7c13))

### ✨

- ✨ feat: build skill venvs inside session container
  ([`b6cab4f`](https://github.com/thiesgerken/carapace/commit/b6cab4f2a76f8b35c5d2fcb38de98cd01eaf22f8))

Replace the ephemeral build container (_build_skill_venv with network=None) with uv sync executed
  inside the session's own sandbox container. A per-session exec lock serializes all container
  commands; the proxy bypass flag is set/cleared atomically under that lock so no concurrent command
  can exploit the window.

- Add per-session asyncio.Lock for exec serialization - Proxy bypass (wildcard "*") scoped to locked
  _exec calls only - _sync_skill_venv copies trusted pyproject.toml/uv.lock from master before
  building, closing TOCTOU tampering - Persist activated_skills in SessionState (survives restarts)
  - Rebuild venvs automatically on container recreation - Re-sync venv after save_skill using
  trusted master deps - Remove ephemeral build container code (K8s-incompatible)

- ✨ feat: validate sandbox image at startup, restructure README quickstart
  ([`29cf9eb`](https://github.com/thiesgerken/carapace/commit/29cf9ebf7744e4aa0533a8d77e19b5bb1eeb8f74))

- Add image_exists() to DockerRuntime - Server exits with clear error if sandbox image is missing -
  Split Getting Started into Docker Compose deployment and development setup - Add Docker to
  prerequisites, document 'docker compose build sandbox'

### 🐛

- 🐛💚 restructure release workflow to build images before creating release
  ([`f746f04`](https://github.com/thiesgerken/carapace/commit/f746f044b91e2a6fc432de3eecc13e95f038db1c))

- Split into: version → docker builds (parallel) → publish - Version step uses --no-vcs-release to
  defer GitHub Release creation - Publish step creates release with wheels + docker pull commands in
  one shot - No more patching release notes after the fact


## v0.22.0 (2026-03-14)

### Other

- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`2966b0d`](https://github.com/thiesgerken/carapace/commit/2966b0de7d9cb61aae9e0622a1c555ebb2581ecc))


## v0.21.0 (2026-03-14)

### Other

- Igns plans
  ([`d0c8b30`](https://github.com/thiesgerken/carapace/commit/d0c8b307ab8b9d3f4e3e312b0efbd2a07f311e58))

- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`7ece752`](https://github.com/thiesgerken/carapace/commit/7ece752ec76ef05a1a248b2dc0da4351359001d3))

- ♻️ refactor: replace global security dicts with dependency injection
  ([`74c5c90`](https://github.com/thiesgerken/carapace/commit/74c5c90547f87d2d086f33f22e3116d875f8cd9b))

- ♻️ refactor: split session.py into session_manager.py and session_engine.py
  ([`6c6a604`](https://github.com/thiesgerken/carapace/commit/6c6a604dbb09cae74c589b09d6a780e82b16319e))

- session_manager.py: SessionManager (pure file I/O, no async) - session_engine.py:
  SessionSubscriber, ActiveSession, SessionEngine (lifecycle, orchestration) - session.py:
  backward-compatible re-export shim - Update test mock targets to carapace.session_engine.Sentinel

- ♻️ refactor: split shared approval queue into typed tool/proxy queues
  ([`f928781`](https://github.com/thiesgerken/carapace/commit/f92878180d551c8ca73991fe4e4f11e116897c45))

- ♻️ refactor: wire security callbacks at session activation, not per-turn
  ([`8523ce3`](https://github.com/thiesgerken/carapace/commit/8523ce39ce62ab553829d19ce7aff75a2e2aea2f))

- ⚡ perf: switch append_events and write_audit to append-only YAML
  ([`95ee976`](https://github.com/thiesgerken/carapace/commit/95ee976dc79f39a0b7286895309499046d3133ad))

### ✨

- ✨ feat: add OCI labels, sandbox version tracking, and docker pull commands in release notes
  ([`cf6d200`](https://github.com/thiesgerken/carapace/commit/cf6d2001332efc6b44b1760f4c72a766bdecaec0))

- Add docker/metadata-action to all image builds for proper GHCR linking - Add update-release job to
  append docker pull commands to release notes - Add _SANDBOX_IMAGE_VERSION to models.py, managed by
  semantic-release - Default sandbox base_image now includes version tag instead of :latest

- ✨move sandbox Dockerfile out of backend assets, remove on-demand build
  ([`a72d34e`](https://github.com/thiesgerken/carapace/commit/a72d34e601898acb07b6be3ab8f8772a4c963d1b))

- Move src/carapace/assets/Dockerfile → sandbox/Dockerfile - Remove get_sandbox_dockerfile() from
  bootstrap.py - Remove build_image() call and _BUILTIN_SANDBOX_IMAGE from server.py - Change
  SandboxConfig.base_image default to 'carapace-sandbox:latest' - Add build-only sandbox service to
  docker-compose.yml (profiles: build) - Add docker-sandbox CI/release jobs to build and push the
  image


## v0.20.0 (2026-03-14)

### Other

- ♻️ refactor: DockerRuntime explicitly inherits ContainerRuntime Protocol
  ([`ff0f471`](https://github.com/thiesgerken/carapace/commit/ff0f4718163d1c66385ca8db14035287133c39d7))

- ♻️ refactor: move SLASH_COMMANDS to ws_models, eliminate all deferred imports
  ([`8ad0990`](https://github.com/thiesgerken/carapace/commit/8ad09900515d03b798e0b57474910b28c890ed95))

- Move _SLASH_COMMANDS from server.py to ws_models.py as SLASH_COMMANDS - Hoist deferred imports to
  module level in session.py (MemoryStore, run_agent_turn, SLASH_COMMANDS) - Hoist deferred imports
  to module level in commands.py (MemoryStore, UserVouchedEntry) - No circular dependencies existed
  — the deferred imports were unnecessary

- ♻️ refactor: remove legacy Matrix mode, extract _resolve_pending helper
  ([`c7fbed2`](https://github.com/thiesgerken/carapace/commit/c7fbed20302f656ba8a15c703d87329def1ba57c))

- Remove dual code paths (engine vs standalone) from MatrixChannel - Make engine parameter required
  - Delete legacy-only methods: _run_turn, _run_turn_locked, _keep_typing, _build_deps, _room_lock -
  Extract _resolve_pending() to deduplicate approve/deny slash commands - Update all Matrix tests to
  use mock SessionEngine - Net: -220 lines

- 🏷️ types: HistoryMessage.role as Literal instead of plain str
  ([`31ea104`](https://github.com/thiesgerken/carapace/commit/31ea104433a0f07a0c24580a43f5cb6d0774c8a5))

- 📝 docs: add deferred-import ban to coding guidelines
  ([`6c5d7be`](https://github.com/thiesgerken/carapace/commit/6c5d7be834c3ffec61a4ac115ba259477b03fcda))

- 📝 docs: clarify stdlib logging import in server.py
  ([`d0a4140`](https://github.com/thiesgerken/carapace/commit/d0a4140c7b229d05babce9377c817d42e41280c7))

- 🔒 security: make CORS origins configurable, default to localhost:3000
  ([`23d5247`](https://github.com/thiesgerken/carapace/commit/23d5247e0007d3ecb9bc4137b20211c21fc8664f))

- Add cors_origins field to ServerConfig (default: ["http://localhost:3000"]) - Move CORS middleware
  setup into lifespan so it reads from config - Replaces previous allow_origins=["*"]

- 🔥 cleanup: delete dead _resolve_path and its tests
  ([`a52ac7a`](https://github.com/thiesgerken/carapace/commit/a52ac7a44eb1c26dd2c420bce2d88507065f27af))

- 🔧 style: add missing future annotations to runtime.py
  ([`9b41830`](https://github.com/thiesgerken/carapace/commit/9b41830b84ff7e42d77b4ad27d1c28beb1dc4890))

### ✨

- ✨ feat: render Matrix /usage report as Markdown tables
  ([`815fc9f`](https://github.com/thiesgerken/carapace/commit/815fc9fc366899124b1317b04333cd1b8a0f34f8))

### 🐛

- 🐛 fix: convert cost string to float before formatting in Matrix /usage command
  ([`011e68e`](https://github.com/thiesgerken/carapace/commit/011e68e09fa3706ce5d0a0d0ae07b5a7d2fb6c1d))


## v0.19.1 (2026-03-14)

### 🐛

- 🐛 fix: echo slash commands as user_message so they appear in the UI
  ([`f29a715`](https://github.com/thiesgerken/carapace/commit/f29a7157c7c3d8c27a8108eb6e6511e5106123cf))


## v0.19.0 (2026-03-14)

### ✨

- ✨ refactor session handling ([#45](https://github.com/thiesgerken/carapace/pull/45),
  [`d07cd03`](https://github.com/thiesgerken/carapace/commit/d07cd0370f0567e4aec2164e09070a5cd2bb3fcf))

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

* ♻️ refactor matrix.py into multiple files

* adjust style guide

* fix typing issues


## v0.18.4 (2026-03-08)

### 🐛

- 🐛 fix tests
  ([`e2c059b`](https://github.com/thiesgerken/carapace/commit/e2c059b919274089c7b06e9fce229fab0b0241a2))


## v0.18.3 (2026-03-08)

### 🐛

- 🐛 focus textarea on mount and add title attribute for session display
  ([`e447382`](https://github.com/thiesgerken/carapace/commit/e4473822577c1e27dd01aa1f04452109627fd0ef))


## v0.18.2 (2026-03-08)

### Other

- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`16346e8`](https://github.com/thiesgerken/carapace/commit/16346e8139abf3a787bdf4ab742d1f122bcf7b3e))


## v0.18.1 (2026-03-08)

### 🐛

- 🐛 fix dependency in submit callback to use queuedMessage instead of hasQueuedMessage
  ([`d95d9ef`](https://github.com/thiesgerken/carapace/commit/d95d9ef0b6766286b9d48d1359435adcbf784123))

- 🐛 fix linter issues
  ([`d21115c`](https://github.com/thiesgerken/carapace/commit/d21115cf5d080f401de4d93539c1307a25c2f89b))

- 🐛 fix react lints
  ([`e9f3c69`](https://github.com/thiesgerken/carapace/commit/e9f3c69048bb89e0a1dd61a669c9c75d1a6b83a0))


## v0.18.0 (2026-03-08)

### Other

- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`85d8e88`](https://github.com/thiesgerken/carapace/commit/85d8e88413d85851663caab528af31a95f93b048))


## v0.17.1 (2026-03-08)

### ✨

- ✨ title generation
  ([`52149c3`](https://github.com/thiesgerken/carapace/commit/52149c3245c982bffc43a655b6eb344ceabf167a))

### 🐛

- 🐛 don't immediately append queued messages to history
  ([`9d6b55a`](https://github.com/thiesgerken/carapace/commit/9d6b55a8a481618c24c52ba5b891e102bc63cfa9))


## v0.17.0 (2026-03-08)

### Other

- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`06df22e`](https://github.com/thiesgerken/carapace/commit/06df22ef29d1443374f9d5f870f47a078a2fc920))


## v0.16.0 (2026-03-08)

### Other

- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`abfab2e`](https://github.com/thiesgerken/carapace/commit/abfab2e299d3004fad5a211a4b89295e04f11e7c))


## v0.15.0 (2026-03-08)

### ✨

- ✨ add queued message handling and interrupt functionality to chat view
  ([`4093130`](https://github.com/thiesgerken/carapace/commit/40931308f2225d7a9b4f0289552bf51b8cb1b84c))

- ✨ add slash command autocomplete feature to chat input
  ([`03dc93d`](https://github.com/thiesgerken/carapace/commit/03dc93d7239a2886d3d38586748c396964d46dbb))

- ✨ autocomplete for slash commands
  ([`18893d2`](https://github.com/thiesgerken/carapace/commit/18893d2699419fe784abbf47e6b60cabfd8b3f8e))

- ✨ hold session id in url param
  ([`05437c3`](https://github.com/thiesgerken/carapace/commit/05437c3d5664a62cbdbcb8609320311ea9f92eb4))

- ✨ show a gauge with current session size
  ([`472e730`](https://github.com/thiesgerken/carapace/commit/472e73027f3848cad6aafa88fae5048764b68551))


## v0.14.0 (2026-03-08)

### ✨

- ✨ stop button to cancel agent
  ([`675d133`](https://github.com/thiesgerken/carapace/commit/675d1334c7950704321873a65f4f8ee4829871f7))

### 🐛

- 🐛 play around with approval options
  ([`3122dfc`](https://github.com/thiesgerken/carapace/commit/3122dfc796c4b1c365a1109a9e01b269286fa044))


## v0.13.0 (2026-03-08)

### Other

- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`f3de4df`](https://github.com/thiesgerken/carapace/commit/f3de4dfdb42d697f7b32ca7086466b30df040d52))

### 🐛

- 🐛 escalation for eicar.com did not work
  ([`8704fd6`](https://github.com/thiesgerken/carapace/commit/8704fd6ffad52611e7f008cecc2e035eacd6c711))

- 🐛 escalation for eicar.com did not work
  ([`364125f`](https://github.com/thiesgerken/carapace/commit/364125f84b1ee4ddfcaf43c588213a716a2ed57f))


## v0.12.1 (2026-03-08)

### Other

- Document linting in agents.md
  ([`4c40804`](https://github.com/thiesgerken/carapace/commit/4c4080413d5ecf963c7a15edcd917adf5c0c2388))

- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`bb722fc`](https://github.com/thiesgerken/carapace/commit/bb722fc9fef0269f5cd81d003e167988d1075928))

### ✨

- ✨ add a test command to test sentinel escalation
  ([`09026f5`](https://github.com/thiesgerken/carapace/commit/09026f5469b4583df1cfaf007fb2aff89dd5cb20))

- ✨ better readable session ids
  ([`89df1f1`](https://github.com/thiesgerken/carapace/commit/89df1f159c681a80eadb8a49a7cc2ab93d23cec1))

### 🐛

- 🐛 fix tool call approval
  ([`125c850`](https://github.com/thiesgerken/carapace/commit/125c8506f3e7e204dbaee993c2273c455898937d))

- 🐛 make the sidebar slightly wider for the new ids
  ([`d70615c`](https://github.com/thiesgerken/carapace/commit/d70615cfbf99933b8ff5fe937e810b2ee4d438cd))

- 🐛 restore approvals on UI reload
  ([`143e850`](https://github.com/thiesgerken/carapace/commit/143e8507ae7212fb801c87c1cd696c2d1299f74c))


## v0.12.0 (2026-03-08)

### ✨

- ✨ docs: add commit message convention using gitmoji
  ([`3ebe25b`](https://github.com/thiesgerken/carapace/commit/3ebe25b5cefaa22cd845e5214f258f681380191a))

- ✨ Update datetime handling to use UTC in models and session management
  ([`004c8db`](https://github.com/thiesgerken/carapace/commit/004c8db338f18a315a7d6df8bd6c3a7aef2799ab))

### 🐛

- 🐛 fix(frontend): tool call spinner not clearing when proxy_domain intercepts result
  ([`fd1f897`](https://github.com/thiesgerken/carapace/commit/fd1f8977e84c7f48558e028770ca0aded19c74e4))

- 🐛 persist proxy requests in events
  ([`c903f4f`](https://github.com/thiesgerken/carapace/commit/c903f4ff91ca2168c51c6540bb7e471099b25213))

- 🐛 use short keys for formatting args summary in ToolCallBadge
  ([`73c6ccd`](https://github.com/thiesgerken/carapace/commit/73c6ccd7e6bb65816e9896b70cfca5cb20792d29))


## v0.11.0 (2026-03-08)

### ✨

- ✨ Rename Bouncer to Sentinel
  ([`49819d8`](https://github.com/thiesgerken/carapace/commit/49819d828ccdd319188b13cef529d08557c97bc6))


## v0.10.0 (2026-03-08)

### Other

- Relock
  ([`362fd15`](https://github.com/thiesgerken/carapace/commit/362fd1555d37d26d116fb4575ed2a875589c9b98))

### ✨

- ✨ Add tool result handling and notifications across components
  ([`080c21a`](https://github.com/thiesgerken/carapace/commit/080c21a2f1ecc523735962bf00683b4d00a774f8))

- ✨ Enhance message handling in ChatView to support tool results and additional message details
  ([`1600386`](https://github.com/thiesgerken/carapace/commit/1600386480da69d0f935493642307ea3e1dd579a))


## v0.9.0 (2026-03-08)

### Other

- Enhance Python style guidelines to encourage clarity in user requests. Added a note advising users
  to avoid technical debt and seek better solutions.
  ([`ab6b668`](https://github.com/thiesgerken/carapace/commit/ab6b66818b988ac93a06d98353616a111ef82386))

### ✨

- ✨ Tool/Proxy Approval via Shadow-Agent ([#39](https://github.com/thiesgerken/carapace/pull/39),
  [`463f10e`](https://github.com/thiesgerken/carapace/commit/463f10ed7daf095c82ad34666f3862eccf8f77cb))

* ✨ Security v2

* 🛡️ Update SECURITY.md to enhance security guidelines and clarify agent behavior regarding prompt
  injection and accidental rogue actions. Added detailed sections on command scrutiny, sandbox
  operations, and user escalation protocols.

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

* Verbessere die Funktion get_host_ip, um die IP-Adresse des Hosts im Docker-Netzwerk zu ermitteln
  und eine Fallback-Option für die Gateway-IP hinzuzufügen.

* Füge Audit-Logging für Benutzerentscheidungen hinzu und verbessere die Protokollierung von
  Toolaufrufen

* Vereinfache die Entscheidungslogik für Proxygenehmigungen und aktualisiere das Modell zur
  Unterstützung neuer Entscheidungen

* Füge Referenzzählung für Sicherheitssitzungen hinzu und verbessere die Sitzungsbereinigung

* make the read/write/patch ops work in the sandbox

* Add domain info callbacks and switch history/usage/event storage to YAML format

* fix yaml

* Remove dash from detail display in ToolCallBadge component

Co-authored-by: Copilot <198982749+Copilot@users.noreply.github.com>


## v0.8.0 (2026-02-22)

### Other

- 💚 add docker builds to the ci ([#38](https://github.com/thiesgerken/carapace/pull/38),
  [`fcb36f6`](https://github.com/thiesgerken/carapace/commit/fcb36f62ccc5cd0d22bf9d4bc6bf67bf92314fff))

### ✨

- ✨ Matrix as additional frontend ([#37](https://github.com/thiesgerken/carapace/pull/37),
  [`bb92183`](https://github.com/thiesgerken/carapace/commit/bb92183d2d3711d76c462275ff7c742a48099c24))

* ✨ Matrix as additional frontend

* pass-through matrix pw

* make it possible to auth using password instead of token

* improve error handling in matrix code

* Enhance Matrix channel command handling and logging

- Updated approval command from `/approve` to `/allow` for clarity. - Improved session command
  result formatting to include activated, disabled rules, approved credentials, and allowed domains.
  - Refactored agent turn execution to run as a background task, allowing for immediate response to
  new events. - Added a new method `_run_turn_locked` to manage room-specific locks during agent
  turns. - Set logging levels for additional libraries to WARNING in server.py for better log
  management.

* fix tests


## v0.7.1 (2026-02-22)

### 🐛

- 🐛 bad gitignore
  ([`36ada40`](https://github.com/thiesgerken/carapace/commit/36ada4061bc0fdc65a522999424f66d7dfd9d8e3))


## v0.7.0 (2026-02-22)

### ✨

- ✨ route sandbox http calls through the backend using a CONNECT proxy
  ([#36](https://github.com/thiesgerken/carapace/pull/36),
  [`58b96e8`](https://github.com/thiesgerken/carapace/commit/58b96e88329a7184a7cdf4263e96216eaa52336b))

* ✨ route sandbox http calls through the backend using a CONNECT proxy

* ✨ Enhance Docker configuration and logging for sandbox environment

- Added `tty` support in `docker-compose.yml` for the carapace service. - Updated volume mappings to
  include the source directory for carapace. - Introduced `ANTHROPIC_API_KEY` as an environment
  variable in the Docker setup. - Changed frontend port mapping from 3000 to 3001. - Enhanced
  logging in `server.py` to display network interface information and resolved sandbox network
  names. - Improved `DockerRuntime` to manage network names and ensure correct network connections
  for containers. - Updated `SandboxManager` to dynamically resolve and log proxy URLs based on the
  container's network settings.

* ✨ Implement proxy domain approval mechanism in sandbox

- Added support for proxy domain approval requests in the chat view and message components. -
  Introduced `handleProxyApproval` function to manage user decisions on proxy access. - Updated
  `SandboxManager` to handle domain approval requests and decisions, integrating with the proxy
  server. - Enhanced WebSocket communication to facilitate proxy approval responses. - Improved
  session management to display allowed domains and their scopes in the CLI. - Refactored related
  components to ensure seamless integration of the new approval workflow.

* Fix content length in forbidden response for proxy policy

* Enhance ProxyServer to filter hop-by-hop headers and enforce connection closure. Updated header
  processing to drop existing Connection headers and append "Connection: close" to prevent HTTP/1.1
  keep-alive issues.

* Fix session token management and enhance error handling in SandboxManager

- Evict orphaned tokens from previous failed attempts to ensure clean session initialization. -
  Refactor IP resolution logic to include error handling, ensuring proper cleanup on failure. -
  Maintain existing functionality for proxy URL generation and container configuration.

* Refactor SandboxManager proxy configuration in tests

- Simplified the instantiation of SandboxManager in test cases by removing the hardcoded proxy URL.
  - Updated the `_build_proxy_env` method calls to include the proxy URL as a parameter, enhancing
  flexibility in testing proxy configurations. - Ensured that the tests maintain their functionality
  while improving code clarity and maintainability.

* Refactor ProxyServer domain checking methods in tests

- Renamed `_check_domain` method to `_is_allowed` for clarity in the ProxyServer class. - Updated
  test cases to reflect the new method name while maintaining existing functionality. - Improved
  code readability and consistency in domain approval checks.

* Remove unused proxyApprovalState ref

The proxyApprovalState ref was written to but never read. Proxy approval state is tracked directly
  on message objects via the decision property, making this ref redundant.

Applied via @cursor push command

* Fix proxy approval allow-all CLI choices

Co-authored-by: Thies Gerken <thiesgerken@users.noreply.github.com>

* Enhance WebSocket error handling and improve test setup

- Added contextlib suppression to handle unexpected WebSocket errors gracefully by closing the
  connection with code 1011. - Updated the test server setup to return an empty list for domain info
  in the SandboxManager, improving test reliability.

* fix: preserve proxy approvals across container recreation

---------

Co-authored-by: Cursor Agent <cursoragent@cursor.com>


## v0.6.0 (2026-02-22)

### ✨

- ✨ Docker sandboxing for sessions ([#35](https://github.com/thiesgerken/carapace/pull/35),
  [`ce5ca5b`](https://github.com/thiesgerken/carapace/commit/ce5ca5bcc4a7e94e89c5e09c01088e46dedc6e6c))

* ✨ Docker sandboxing for sessions

* ✨ Update logging guidelines in AGENTS.md and python-style.mdc

- Added a section on logging best practices, specifying the exclusive use of `loguru` over stdlib
  `logging`. - Included instructions for importing `loguru` and using f-strings in log calls for
  improved readability and performance.

* add loguru

* Refactor logging to use loguru across the codebase

- Replaced instances of the standard logging library with loguru for improved logging capabilities.
  - Updated log messages to utilize f-strings for better readability and performance. - Removed the
  `enabled` field from `SandboxConfig` as it is no longer needed. - Enhanced error handling and
  logging in the Docker runtime and sandbox manager for better debugging and maintenance.

* ✨ Enhance Docker runtime with network management

- Added a method to ensure the existence of Docker networks before container creation. - Improved
  the DockerRuntime class to manage and log network creation, enhancing the overall functionality of
  the sandbox environment.

* Fix input prompt formatting in approval request to escape brackets for proper display

* Refactor sandbox configuration and Docker integration

- Removed the carapace-sandbox-image service from docker-compose.yml and deleted its Dockerfile. -
  Updated SandboxConfig to allow an empty base_image, enabling auto-building from a bundled
  Dockerfile. - Introduced a method to read the bundled Dockerfile content in bootstrap.py. -
  Enhanced DockerRuntime with a build_image method to build the sandbox image from the bundled
  Dockerfile. - Adjusted server lifespan logic to build the sandbox image if no base_image is
  specified in the configuration.

* Enhance error handling and logging in sandbox and Docker runtime

- Introduced custom exceptions `ContainerGoneError` and `SkillVenvError` for better error management
  in the sandbox environment. - Updated the `DockerRuntime` and `SandboxManager` classes to handle
  these exceptions, improving robustness during container execution and skill virtual environment
  building. - Enhanced logging to provide clearer insights into errors and warnings related to
  container management and skill activation.

* Set logging levels for specific libraries to WARNING in server.py

- Adjusted logging configuration to set the logging level to WARNING for the "httpcore", "httpx",
  and "docker" libraries, improving log clarity and reducing verbosity.

* Enhance logging configuration in server.py

- Added "anthropic" and "websockets" to the list of libraries with WARNING logging level. -
  Introduced a custom emoji patcher for log records to replace specific prefixes with emojis,
  improving log readability.

* Update Python style guidelines in python-style.mdc

- Clarified the use of Pydantic `BaseModel` for structured data, removing references to stdlib
  `@dataclass`. - Introduced the use of `Annotated[type, Field(...)]` for field metadata and
  defaults, emphasizing correct usage. - Specified that non-nullable fields should not be assigned
  `None` with `# type: ignore`, promoting better type safety. - Updated guidance on avoiding mutable
  default arguments to use `Annotated` for consistency.

* Refactor agent and sandbox management for improved structure and logging

- Removed the local command execution fallback in favor of a more streamlined sandbox execution
  approach. - Enhanced the `Deps` class to utilize Pydantic's `BaseModel` and `Annotated` for better
  type safety and field management. - Updated the `SessionContainer` and `Mount` classes to inherit
  from `BaseModel`, ensuring consistent data handling. - Improved error handling in the agent's
  skill activation process with enhanced logging using `loguru`. - Adjusted server cleanup logic to
  ensure proper management of sandbox resources.

* Rename `bash` tool to `shell` in agent.py for clarity and update command execution in
  DockerRuntime to use `bash` instead of `sh` for consistency in command handling.

* Update Dockerfile to use specific version of uv and remove unnecessary apt-get commands

* Update default server host in ServerConfig to allow external access

* Improve WebSocket error handling in _chat_loop function

- Added reconnection logic for both sending messages and reading server responses upon
  ConnectionClosed exceptions. - Enhanced user feedback during reconnection attempts to improve user
  experience.

* Refactor WebSocket connection handling in cli.py

- Updated the WebSocket connection logic to use the `websockets.asyncio.client` module directly for
  improved clarity and consistency. - Enhanced type hinting for the `_connect_ws` function to
  specify the return type as `ClientConnection`.

* Refactor skill management in Deps class and server dependency building

- Updated the `Deps` class to initialize `skill_catalog` and `activated_skills` with default empty
  lists for improved clarity and consistency. - Modified the `_build_deps` function in `server.py`
  to pass an empty list for `activated_skills`, ensuring proper initialization during dependency
  construction.

* Add CARAPACE_HOST_DATA_DIR environment variable and update SandboxManager for host path handling

- Introduced the `CARAPACE_HOST_DATA_DIR` environment variable in `docker-compose.yml` to specify
  the host data directory. - Updated `server.py` to retrieve and pass the host data directory to the
  `SandboxManager`. - Enhanced `SandboxManager` to handle host paths for bind mounts, ensuring
  correct path resolution when running in Docker. - Improved logging to provide feedback on host
  data directory overrides during sandbox initialization.

* Implement skill name validation in SandboxManager

- Added a regex-based validation function for skill names to ensure they are non-empty, start with
  an alphanumeric character, and contain only valid characters. - Integrated the validation function
  into the `activate_skill`, `_build_skill_venv`, and `save_skill` methods to enforce skill name
  rules and return appropriate error messages when invalid names are provided. - Refactored the
  `SessionContainer` class to initialize `activated_skills` with an empty list for consistency.

* fix lint issues

* Enhance documentation in agent.py for skill activation and command execution

- Updated the prompt for skill activation to clarify the setup of a virtual environment. - Improved
  the docstring for the exec function to specify that it typically runs bash commands. - Removed the
  unused shell function to streamline the code.

* Refactor session directory structure in SandboxManager

- Changed the session directory structure to use a single 'workspace' directory for skills and
  temporary files. - Updated the relevant methods to reflect the new paths for skill and temporary
  directories, ensuring consistent handling of session data.


## v0.5.0 (2026-02-20)

### ✨

- ✨ Implement token usage tracking and reporting
  ([#34](https://github.com/thiesgerken/carapace/pull/34),
  [`00fbd8e`](https://github.com/thiesgerken/carapace/commit/00fbd8eab83a2906cb6902064ce06e1ab65a15f8))

* ✨ Implement token usage tracking and reporting

- Added a new `UsageTracker` class to monitor token usage across models and categories. - Introduced
  a `/usage` command in the CLI to display token usage statistics. - Enhanced the
  `classify_operation` and `check_rules` functions to record usage data. - Updated the frontend to
  visualize usage data with a new `UsageView` component. - Bumped `carapace` version to 0.4.0 to
  reflect these changes.

* ✨ Enhance usage tracking and reporting features

- Updated `pyproject.toml` to specify version constraints for dependencies. - Added new `costs`
  field to `UsagePayload` for tracking costs associated with token usage. - Implemented cost
  estimation in `UsageTracker` to calculate total costs based on token usage. - Enhanced frontend
  components to display command results and usage costs. - Improved session management to persist
  usage data and events for better tracking. - Updated CLI to include costs in the `/usage` command
  output.

This commit builds upon the previous implementation of token usage tracking, providing a more
  comprehensive view of resource utilization.


## v0.4.0 (2026-02-20)

### ✨

- ✨ Add a web frontend ([#31](https://github.com/thiesgerken/carapace/pull/31),
  [`4d7e028`](https://github.com/thiesgerken/carapace/commit/4d7e0281acdb0fef1c252d0ce818fe6afc98ba6e))


## v0.3.0 (2026-02-19)

### Other

- 💚 Update build command in pyproject.toml to include 'uv lock'
  ([`5cedc87`](https://github.com/thiesgerken/carapace/commit/5cedc87e2c8a74a142eaab058013e8993fcbdc45))

### ✨

- ✨ Revamp Carapace architecture with server and CLI client integration
  ([#30](https://github.com/thiesgerken/carapace/pull/30),
  [`6644bfe`](https://github.com/thiesgerken/carapace/commit/6644bfe8bca5e79801320c76fed669e1775fa4f5))

* ✨ Revamp Carapace architecture with server and CLI client integration

- Introduced a FastAPI server for handling requests and WebSocket connections. - Updated CLI to
  connect to the server, replacing the previous interactive model. - Enhanced documentation in
  AGENTS.md and README.md to reflect new server and client structure. - Added bearer token
  authentication for secure communication between CLI and server. - Updated project dependencies to
  include FastAPI, Uvicorn, and WebSockets. - Version bump to 0.2.0 to signify major architectural
  changes.

* ✨ Implement session locking in WebSocket chat handler

- Added asyncio locks to manage concurrent access to session data, ensuring serialized agent turns.
  - Refactored chat_ws function to utilize session locks for loading and saving message history and
  session state. - Improved error handling and logging during agent execution.

* 🧹 Clean up unused server URL function in CLI

- Removed the `_server_url` function as it was no longer needed in the updated architecture. -
  Streamlined the code for better readability and maintenance.

* ✨ Improve error handling for approval requests in CLI and server

- Added exception handling for keyboard interruptions during approval requests in the CLI, ensuring
  a graceful denial message is displayed. - Updated server logic to handle interrupted approvals by
  marking them as denied and clearing pending requests, enhancing overall robustness.

* Fix 5 bugs: WebSocket auth exception, token permissions, session lock cleanup, async input
  blocking, and verbose output routing

- Use WebSocketException instead of HTTPException for WebSocket auth failures - Set token file
  permissions to 0600 for security - Clean up session locks on WebSocket disconnect to prevent
  memory leak - Use run_in_executor for approval prompt input to avoid blocking event loop - Route
  verbose tool call output via WebSocket instead of server stdout

Applied via @cursor push command

* Fix fire-and-forget WebSocket send by saving task references

- Save created tasks in a set to prevent garbage collection - Add error handling to log WebSocket
  send failures - Cancel pending tasks on client disconnect - This ensures the server detects
  dropped clients and stops expensive LLM calls

* pc

* Refactor WebSocket chat handler for improved control flow and error handling

- Changed return statement to break in command handling for better flow control. - Added a finally
  block to ensure session locks are cleaned up on disconnect. - Enhanced error handling for
  unexpected agent output types during message sending.

* Enhance session management in WebSocket chat handler

- Introduced an async context manager for session connections to manage locks more effectively. -
  Updated chat_ws function to utilize the new session connection management, ensuring proper lock
  handling during WebSocket interactions. - Improved error handling and cleanup on client disconnect
  to prevent memory leaks and ensure session integrity.

---------

Co-authored-by: Cursor Agent <cursoragent@cursor.com>


## v0.2.0 (2026-02-15)

### Other

- 📝 Update README.md to include new security guideline for skills
  ([`83d90b1`](https://github.com/thiesgerken/carapace/commit/83d90b1f343811cdb8ffb278470680e3d8da4225))

- Added a section emphasizing the importance of reviewing skills before installation, highlighting
  that skills are considered trusted code and the user's responsibility in managing them.

### ✨

- ✨ Integrate Logfire for enhanced logging and tracing
  ([`7c1ddeb`](https://github.com/thiesgerken/carapace/commit/7c1ddeb0cb5787fa0ff3f6883c3a9b2a2c0c1008))

- Added `logfire` dependency to `pyproject.toml` and `uv.lock`. - Configured Logfire in the CLI to
  enable tracing based on user token. - Updated `CarapaceConfig` to include `logfire_token` field. -
  Modified example `config.yaml` to indicate where to set the Logfire token.


## v0.1.0 (2026-02-15)

### Other

- Fix url in readme
  ([`f2ece16`](https://github.com/thiesgerken/carapace/commit/f2ece16e3f29036c1b85d95b2c3fa39ab88fc564))

- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`85552db`](https://github.com/thiesgerken/carapace/commit/85552db18aa94bd696bc879fefca3801aecc3f34))

- Update readme
  ([`2f1daa1`](https://github.com/thiesgerken/carapace/commit/2f1daa15813b60241506afde11931881fd7d1e66))

- 💚 Fix CI: add pytest dev dep and gitmoji PR title check
  ([#2](https://github.com/thiesgerken/carapace/pull/2),
  [`7e0ba76`](https://github.com/thiesgerken/carapace/commit/7e0ba766fd6b13f7c68b191236fce903c06bb48f))

* 💚 Fix CI: add pytest dev dep and gitmoji PR title check

- Add pytest to dependency-groups so `uv sync --dev` installs it - Add pr-title job to enforce
  gitmoji prefix on PR titles

Co-authored-by: Cursor <cursoragent@cursor.com>

* 💚 Disable color in CLI test runner to fix CI assertions

* 💚 Use NO_COLOR env var instead of color kwarg in test runner

* 💚 Strip ANSI escape codes in CLI test assertions

---------

- 📝 Add AGENTS.md for project overview, setup, code style, structure, testing, and CI details
  ([`b79fbbb`](https://github.com/thiesgerken/carapace/commit/b79fbbba67733067727b8e7c4a539b06fe8b3184))

- 📝 Add MIT LICENSE file ([#3](https://github.com/thiesgerken/carapace/pull/3),
  [`1226e36`](https://github.com/thiesgerken/carapace/commit/1226e3622ac8a65335b3eb16367104af3cdfa7a2))

Co-authored-by: Cursor Agent <cursoragent@cursor.com>

- 📝 Add Python coding style guide for carapace project
  ([`8f91cf2`](https://github.com/thiesgerken/carapace/commit/8f91cf2e2b65f36a1e277533d6cba3cf5470ade0))

- 📝 Enrich README with getting started guide and demo output
  ([#1](https://github.com/thiesgerken/carapace/pull/1),
  [`593d395`](https://github.com/thiesgerken/carapace/commit/593d3952b870e44ebd94f5f376ca2cb31b5b5318))

* 📝 Enrich README with getting started guide and demo output

Add installation, running, and configuration instructions. Include a pruned demo session showcasing
  the interactive CLI.

Co-authored-by: Cursor <cursoragent@cursor.com>

* tired of that

---------

### ✨

- ✨ Add bootstrap module and initial asset files for Carapace
  ([#28](https://github.com/thiesgerken/carapace/pull/28),
  [`655e154`](https://github.com/thiesgerken/carapace/commit/655e154612384688fa5c25d6c20600de78ec1bd4))

- Introduced `bootstrap.py` to ensure the creation of critical files and directories. - Added asset
  files including `config.yaml`, `CORE.md`, `SOUL.md`, `USER.md`, and rules in `rules.yaml`. -
  Implemented functionality to seed skills and manage data directory initialization in the CLI.

- ✨ Implement message replay functionality in chat session
  ([`dfe883b`](https://github.com/thiesgerken/carapace/commit/dfe883bfaededd25087aa887a282114b3b2dcda7))

- Added `_replay_history` function to display previous conversation turns. - Introduced `--prev`
  option in the `chat` command to specify the number of previous turns to replay. - Updated response
  validation logic for improved readability.

- ✨ Update commit parser options in pyproject.toml
  ([`632eaf4`](https://github.com/thiesgerken/carapace/commit/632eaf494bc4a6a29472427323cd38efdcda368e))

- Added major, minor, and patch tags for semantic release. - Enhanced commit parsing configuration
  to support emoji and text tags.


## v0.0.0 (2026-02-14)

### Other

- Add ci
  ([`dd57de9`](https://github.com/thiesgerken/carapace/commit/dd57de9d6a1be3ba413bd8c20ed12d45fb5032e4))

- Add docs and brainstorming
  ([`54eacb2`](https://github.com/thiesgerken/carapace/commit/54eacb2091b136948e35bdd3ae7e3d305a4a1330))

- Add tests, add precommit, fix lints
  ([`3adb428`](https://github.com/thiesgerken/carapace/commit/3adb4283ae1ec76dc69a4df62bddd7db9a36985d))

- Let opus code a PoC
  ([`7e2f876`](https://github.com/thiesgerken/carapace/commit/7e2f876aa755be5176601f7a5fa217cca59f0694))

- Update build command in pyproject.toml to install uv before building
  ([`b67255c`](https://github.com/thiesgerken/carapace/commit/b67255ca8a177da256fcbcfaf40b1d84be8dafa8))
