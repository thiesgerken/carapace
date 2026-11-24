# Development

The committed Nix flake and lockfile own builds, checks, and runtime images. Python dependencies come from `uv.lock` through uv2nix, preferring wheels on Python 3.14. Frontend dependencies come from `frontend/package-lock.json` through `importNpmLock`, which fetches each package by the integrity hash in the lockfile; npm ships with the pinned Node.js. The sandbox image is a Nix image without an FHS layout; see [sandbox image](sandbox.md#sandbox-image) for how foreign binaries still run in it.

The local Python package source includes only `pyproject.toml`, `README.md`, and `src/`. Python check inputs are scoped separately, so changes under `docs/`, `charts/`, or `frontend/`, and changelog updates, do not invalidate Python builds and checks.

The server image and Python checks use a Python 3.14 override with `stripConfig`, `stripIdlelib`, and `stripTests` enabled. This removes the static interpreter archive and development-only standard-library files without changing the wheel ABI. The customized interpreter builds from source on a cold store; trusted release CI caches Linux x64 builds in Cachix. The native developer shell keeps the cached `pkgs.python314` interpreter and uv manages its separate `.venv`.

## Native developer shell

```sh
nix develop
uv sync --dev
```

The shell provides Python 3.14, uv, Node.js 24 (with npm), Git, Helm, Skopeo, and jq. uv manages `.venv`; `UV_PYTHON` selects the Nix interpreter and `UV_PYTHON_DOWNLOADS=never` prevents another interpreter download. With direnv and nix-direnv, run `direnv allow` once in each checkout or worktree to load `.envrc` automatically.

For host iteration, start a disposable Redis and the [skill builder](builder.md), build and load the sandbox and builder images, then run the server:

```sh
docker run --rm -d --name carapace-dev-redis -p 127.0.0.1:6379:6379 redis:8-alpine
docker load -i "$(nix build .#packages.x86_64-linux.sandbox-image --no-link --print-out-paths)"  # aarch64-linux on ARM Linux
docker load -i "$(nix build .#packages.x86_64-linux.builder-image --no-link --print-out-paths)"  # aarch64-linux on ARM Linux
export CARAPACE_BUILDER_TOKEN="$(openssl rand -hex 20)"
docker volume create carapace-dev-builder-nix
docker run --rm -v carapace-dev-builder-nix:/mnt/nix carapace-builder:local /bin/carapace-builder-init
docker run -d --name carapace-dev-builder -p 127.0.0.1:8330:8330 -p 127.0.0.1:8331:8331 \
  -e CARAPACE_BUILDER_TOKEN \
  --security-opt seccomp=unconfined --security-opt apparmor=unconfined --security-opt systempaths=unconfined \
  -v carapace-dev-builder-nix:/nix carapace-builder:local
export CARAPACE_SANDBOX_BASE_IMAGE=carapace-sandbox:local
export CARAPACE_DATA_DIR=./data/development
export CARAPACE_CACHE_REDIS_URL=redis://localhost:6379/0
export CARAPACE_BUILDER_URL=http://127.0.0.1:8330
export CARAPACE_BUILDER_CACHE_URL=http://127.0.0.1:8331
uv run carapace-server
```

Sandboxes need a Linux Docker host here: they reach the server's proxy and Git endpoint through the gateway of their internal network, which Docker Desktop puts inside its VM, so on a Mac the start-up egress self-test fails. With `CARAPACE_SANDBOX_EGRESS_SELF_TEST=false` the server starts on a Mac anyway, for the UI and the API, but sandboxes still can't reach the proxy or the Git endpoint: no knowledge clone, no domain or credential access, so no real turn that runs commands. For those, run the stack from [native Linux images](#native-linux-images-on-apple-silicon) on Apple Silicon. The builder's cache on loopback works because the session proxy forwards cache reads to it without the destination check.

The server reads `CARAPACE_TOKEN` and the model keys from `.env` in the working directory (see `.env.example`). The SQLite database defaults to `carapace.db` in the data directory. For Postgres-backed host iteration, expose a separate development Postgres port and set `CARAPACE_DATABASE_URL`; keep development data separate from an existing deployment. Clean up with `docker stop carapace-dev-redis`, `docker rm -f carapace-dev-builder` and `docker volume rm carapace-dev-builder-nix`.

In another shell:

```sh
npm --prefix frontend ci
npm --prefix frontend run dev
```

Next.js serves port 3000 and proxies `/api` to `http://127.0.0.1:8321`; set `CARAPACE_BACKEND_URL` for a different host server. Compose images are immutable and no longer bind-mount `src/carapace`. Use `uv run` for live server code.

## Screenshots

UI PRs show the pages they change: before and after, light and dark, plus phone width when the layout changes. carapace is public, so screenshots only ever show demo data. Never point the capture at a real data dir.

`scripts/seed_demo.py` fills a throwaway data dir with a demo user and ready-made sessions, written directly as events. Nothing calls an LLM, the session IDs and contents are fixed, and the timestamps are relative to the seeding time, so the same steps give the same pictures. To show live state, configure a model and start a real turn on top.

| Session ID | Title | Shows |
| --- | --- | --- |
| `demo-sandbox-tour` | Getting To Know The Sandbox | thinking, a titled `exec` with a domain access, sandbox panel |
| `demo-pancake-recipe` | Classic Fluffy Pancake Recipe | `read_skill` waiting for a build and a profile sync, ungated `exec` calls whose domain access the sentinel reviews and whose credential the user releases, the debug view (`&view=debug`) with the turn's timeline and a request timeline per role |
| `demo-recipe-skill` | Creating A Recipe Skill | file read and write, a git push, code blocks |
| `demo-blocked-post` | HTTP POST Blocked In Ask Mode | ask mode, a domain the sentinel denied, and the failed `exec` |
| `demo-internal-host` | Checking The Document Server | a domain the proxy refused as an internal destination, with the reason |
| `demo-change-request` | Fixing The Pancake Ingredients | a push the sentinel sent back for changes (`revise`), then the narrowed push, allowed with a comment for the agent |
| `demo-pending-approval` | Cleaning Up NAS Backups | a pending escalation of an up-front request (a credential and a domain) |
| `demo-budget-stop` | Triage Open Issues | a budget stop with the error box |
| `demo-unexpected-error` | LED Controller Pinout | a turn that stopped on an unexpected error: the failed call and the error box with its traceback |
| `demo-autonomy-limit` | Checking Outdated Dependencies | an autonomy-limit approval card |
| `demo-sales-dashboard` | Q3 Sales Dashboard | artifact references: a first reference, an artifact update, and a deleted artifact; its commits are in the demo user's knowledge repo |
| `demo-subscription` | Refactoring Date Parsing | a Codex (subscription) agent with a paid sentinel, actual and equivalent cost limits |

A session opens at `/?session=<ID>`.

The demo user also has memory data for the Memory pages and the home page: `memory_low` runs on the subscription model, today's budget window holds a session extraction on Sonnet (`demo-pancake-recipe`) and one on Codex (`demo-subscription`), and `demo-recipe-skill` has a pending extraction task for the run dialog. Today's spend sits close to the memory budget's day limits, so the home page shows the budget notice.

1. Start a disposable Redis and the server on a fresh data dir inside the temp directory (the seed refuses any other). Startup bootstraps an `admin` user from `CARAPACE_TOKEN`. Stop a running development server first, or move this one to other ports with `CARAPACE_SERVER_PORT`/`CARAPACE_SERVER_SANDBOX_PORT` and `CARAPACE_BACKEND_URL` for the frontend.

   ```sh
   docker run --rm -d --name carapace-demo-redis -p 127.0.0.1:6390:6379 redis:8-alpine
   export CARAPACE_DATA_DIR="$(mktemp -d)"
   unset CARAPACE_DATABASE_URL  # the demo database must be the default SQLite file in the data dir
   CARAPACE_CACHE_REDIS_URL=redis://127.0.0.1:6390/0 \
   CARAPACE_SANDBOX_BASE_IMAGE=carapace-sandbox:local \
   CARAPACE_SANDBOX_EGRESS_SELF_TEST=false \
   CARAPACE_TOKEN=demo-admin-password-0123456789 \
   uv run carapace-server
   ```

   The demo sessions need no sandbox, so the server skips the egress self-test, which a server on a Mac host can never pass (see [host iteration](#native-developer-shell)). It warns about that at start.

2. In another shell with the same `CARAPACE_DATA_DIR`, seed it once the server is up. Order matters: server startup closes approval requests left open by a previous process, and two demo sessions show open ones. The script refuses a data dir outside the temp directory, a database outside the data dir, and a data dir that already has sessions.

   ```sh
   uv run python scripts/seed_demo.py "$CARAPACE_DATA_DIR"
   ```

3. Start the frontend with `npm --prefix frontend run dev` and log in as `demo` with password `carapace-demo` if you want to look around.

4. Capture with headless Chrome. `scripts/screenshot.mjs` logs in as the demo user over the DevTools protocol (Node built-ins only), since the session cookie is HTTP-only. Per page it writes `NAME-light.png` and `NAME-dark.png` at 1280×800 with device scale factor 2, or `NAME-phone-light.png` and `NAME-phone-dark.png` at 390×844 with `--phone`. It prints the files; without `--out` they land in a fresh temp directory, so they can't end up in a commit. Light and dark come from `--blink-settings=preferredColorScheme=1` and `=0`. The UI is English and the time zone UTC. Each page gets the load event plus `--settle` milliseconds (default 3000) to render. Set `CHROME` to the Chrome binary outside macOS.

   ```sh
   node scripts/screenshot.mjs --out /tmp/shots 'budget=/?session=demo-budget-stop'
   node scripts/screenshot.mjs --out /tmp/shots --phone 'budget=/?session=demo-budget-stop'
   ```

   For "before" pictures, run the base branch's frontend (e.g. from a worktree on `origin/main`) against the same server and capture into another directory.

5. Attach the pictures to the PR instead of committing them. gh 2.99 or newer uploads images natively and rewrites `![alt](./file.png)` references in the body:

   ```sh
   cd /tmp/shots
   gh pr edit 123 -R thiesgerken/carapace --body-file body.md --attach ./budget-light.png --attach ./budget-dark.png
   ```

The README screenshots in `docs/assets/screenshots/` are not regenerated automatically, and most of them can't come from `screenshot.mjs`: the chat opens scrolled to the bottom, and some shots need scrolling or expanded tool details, which the script doesn't do. To retake them, run steps 1 to 3, log in as `demo` in a 1280×800 browser window, and take them by hand:

| README file | Session | Position |
| --- | --- | --- |
| `sandbox_info.png` | `demo-sandbox-tour` | top of the chat |
| `pancake_web.png` | `demo-pancake-recipe` | `web_fetch` call expanded |
| `pancake_skill.png` | `demo-recipe-skill` | first turn, `git push` expanded |
| `pancake_git.png` | `demo-recipe-skill` | git log in the last answer |
| `pancake_tree.png` | `demo-recipe-skill` | workspace tree in the last answer |
| `post_readonly.png` | `demo-blocked-post` | denied call expanded |

Clean up with `docker stop carapace-demo-redis` and by deleting the data dir.

## Native Linux images on Apple Silicon

Install [Determinate Nix](https://docs.determinate.systems/) and authorize its Native Linux Builder with a free FlakeHub account:

```sh
determinate-nixd auth login
determinate-nixd status
nix build .#packages.aarch64-linux.server-image --out-link result-server-image
nix build .#packages.aarch64-linux.frontend-image --out-link result-frontend-image
nix build .#packages.aarch64-linux.bitwarden-image --out-link result-bitwarden-image
nix build .#packages.aarch64-linux.sandbox-image-lite --out-link result-sandbox-image
nix build .#packages.aarch64-linux.builder-image --out-link result-builder-image
for image in result-{server,frontend,bitwarden,sandbox,builder}-image; do docker load -i "$image"; done
export COMPOSE_FILE=docker-compose.yml:docker-compose.local.yml
docker compose up -d
```

These are native ARM Linux builds, not x86 emulation. Only x86_64 Linux images are published. Non-Nix x64 users pull release images as described in the [quickstart](quickstart.md).

On Linux x64, use `packages.x86_64-linux.` in the Nix output paths and the full `sandbox-image`. The local Compose overlay selects `:local` images with `pull_policy: never` and points the server at `carapace-sandbox:local`.

`sandbox-image` cannot be built on the Native Linux Builder: it fails with "Too many open files in system" once a single build opens about 100k files, and the nixpkgs source that the image ships has 90k. Build `sandbox-image-lite` there instead (the commands above do); CI or a real Linux builder builds the full image. The lite image is the same except for that source, so its first `nix run nixpkgs#…` fetches nixpkgs (from `cache.nixos.org`, a few seconds) where the full image needs no network. Building on a Mac also reads macOS's case-insensitive store, so in local images names that differ only in case carry a `~nix~case~hack~1` suffix (terminfo entries, for example). Published x64 images are built on Linux and are not affected.

The server, frontend, and Bitwarden images use UID/GID 999, a read-only root, dropped capabilities, and writable `/tmp`. The server data directory and Bitwarden state need persistent writable mounts. The frontend listens on 8080; Compose's proxy and the chart keep their public ports unchanged.

The Bitwarden runtime keeps the upstream bundle and the transitive package closure of its literal `require()` calls, preserving nested `node_modules` resolution and required peers. Its install check loads every discovered external from the installed bundle's directory. The wrapper and auxiliary script shebangs use the slim Node.js interpreter matching `bitwarden-cli.nodejs`, keeping the npm-enabled toolchain out of the runtime closure. The sidecar entrypoint is unchanged.

## Checks and runtime smoke

On Linux:

```sh
nix flake check
```

`checks.<system>` includes `pytest`, `pyrefly`, `ruff`, `frontend-lint`, `frontend-test`, `frontend-build`, `helm`, and the skill checks: `skill-wrapper-contract`, the examples (`skill-example-*`, `skill-examples-run`) and the bundled skills (`skill-bundled-*`, `skill-bundled-run`). For the commands below, `<system>` is `x86_64-linux` or `aarch64-linux`.

SHA-256-pinned `cl100k_base` and `o200k_base` BPE files populate a shared tiktoken cache used by checks and the server image, so tokenization needs no first-use network download on a fresh pod.

Checks set `SSL_CERT_FILE` to the pinned CA bundle because HTTP clients initialize TLS even when tests do not make network requests.

```sh
nix build .#checks.<system>.pytest
nix build .#ciBuilds.<system>.server-image
```

On Apple Silicon, `nix flake check --system aarch64-linux` runs the Linux checks through the builder. A plain `nix flake check` also evaluates the native macOS development/tooling outputs.

`ciBuilds.<host-system>` contains every mandatory check, runtime package/image, the Helm chart archive, and the CI tool profile; `ciBuilds.x86_64-linux` also holds the Presswerk CLI the release jobs run. To realize them with the locked runner:

```sh
nix build --inputs-from . nixpkgs#nix-fast-build --out-link result-build-tool
# Linux x64:
result-build-tool/bin/nix-fast-build --no-nom --flake .#ciBuilds.x86_64-linux --systems x86_64-linux --out-link result-ci
# Apple Silicon:
result-build-tool/bin/nix-fast-build --no-nom --flake .#ciBuilds.aarch64-darwin --systems "aarch64-darwin aarch64-linux" --out-link result-ci
```

Load the five runtime images and run:

```sh
python3 scripts/smoke-images.py
# with sandbox-image-lite (Apple Silicon): the offline nixpkgs check cannot pass there
CARAPACE_SMOKE_SANDBOX_LITE=1 python3 scripts/smoke-images.py
```

The smoke uses disposable volumes and dynamic ports. It checks authenticated server readiness with Postgres and Redis, which includes the start-up egress self-test in a real sandbox on the internal network (the data volume's mountpoint serves as `CARAPACE_HOST_DATA_DIR`, so sandbox workspaces bind like in `docker-compose.yml`), rejects a real knowledge-repo push through the sentinel for a missing session, verifies effective UID 999 and read-only roots, and checks default and overridden frontend CSP headers. Bitwarden runs without a network under the runtime restrictions: status, password generation, server configuration round-trip, and the explicit unauthenticated `bw serve` rejection. No LLM credentials or vault account are needed. In the sandbox image, without capabilities as on Kubernetes, it checks `cgate`, that the `mcp` bridge loads its SDK, the tools of the server's egress probe (bash `/dev/tcp`, `timeout`, `getent`), that `python3` is python-build-standalone managed by uv, `uv sync` of numpy, `npm ci` of sharp, a downloaded glibc binary through nix-ld, and `nix run nixpkgs#hello` with nixpkgs resolved offline (not for the lite image, see below). The builder runs with the Compose security options, must pass its sandbox probe, builds a skill flake without inputs, answers a second request from the stored result, runs its API as UID 999 and harmonia as UID 998, and serves the built path from its binary cache with the builder's signature. The sandbox checks need internet access. Real vault login, unlock, sync, and an authenticated Bitwarden API listener remain outside this smoke.

Focused host checks remain available:

```sh
uv run pyrefly check
uv run pytest
uvx ruff check src/
npm --prefix frontend run lint
npm --prefix frontend test
helm lint charts/carapace
```

`prek run` remains separate because its hooks fetch from the network.

## Dependency refresh

Renovate updates `flake.lock`, uv, frontend dependencies, and image digests. Frontend updates need no Nix follow-up: the Nix build reads `frontend/package-lock.json` directly, so there is no separate dependency hash to refresh.

npm blocks dependency install scripts unless `allowScripts` in `frontend/package.json` lists the package. When an update introduces a new install script, `npm install` names it; review it, then record the decision with `npm install-scripts approve --no-allow-scripts-pin <pkg>` or `npm install-scripts deny <pkg>`.

`engines.npm` keeps Renovate on npm 11, the major that ships with `nodejs_24` in the dev shell and the Nix build. Renovate otherwise installs the latest npm, and npm 12 refuses to resolve this lockfile (`EALLOWREMOTE`). Raise the range together with the Node.js major in `nix/tools.nix`; a Renovate rule keeps it from moving on its own.

The `overrides` entry in `frontend/package.json` lets the ESLint plugins bundled by `eslint-config-next` use the project's ESLint 10 although their peer ranges still end at 9. Without it, npm treats the conflict as unresolved and `npm ci` tries to reach the registry, which fails in the Nix sandbox. Drop it once those plugins declare ESLint 10 support.

Frontend fonts are licensed variable WOFF2 inputs committed in `frontend/src/fonts/`, with notices in `frontend/public/fonts/`. Twemoji's pinned archive is fetched by Nix; `postFetch` retains only `v/17.0.2/svg` in the store. The build prepopulates the existing emoji script cache, so the script needs no network access. If its pinned Twemoji revision/version changes, update `nix/frontend.nix` and refresh `nix/twemoji-hash` with the fixed-output mismatch reported by Nix.

The only Python source-build override supplies setuptools to `http-ece`, whose release has no wheel. Keep overrides tied to observed build failures.

### Bundled skill pins

The bundled skills with commands (`src/carapace/assets/skills/*/flake.nix`) pin a Carapace commit for their helpers and, in the `carapace` skill, the CLI. When a release changed the helpers (`nix/skills`) or the CLI, point them at that release commit in a regular commit, which then ships with the next release:

```sh
rev=$(git rev-parse vX.Y.Z^{commit})
for flake in src/carapace/assets/skills/*/flake.nix; do
  nix flake lock "path:$(dirname "$flake")" --override-input carapace "github:thiesgerken/carapace/$rev?dir=nix/skills"
done
```

A release commit cannot pin itself, so this cannot be part of the release commit, and releases happen on every push to `main`, so bumping after each one would only churn. CI builds every bundled skill against its pin and against the current helpers, so a pin that falls behind still has to build.

## CI and publishing

[CI](../.github/workflows/ci.yml) calls [Nix verification](../.github/workflows/nix-verify.yml). Workflows read the public [`thiesgerken` Cachix cache](https://thiesgerken.cachix.org) and skip outputs already in it; only release runs push to it, so PR builds never write it. The flake offers the cache to local builds through `nixConfig` (accept it when Nix asks; it takes effect for trusted users). It holds only x86_64-linux outputs. PR verification has read-only repository access, smoke-tests loaded images, and uploads the verified x64 image archives and chart data.

Failed Nix builds retain expanded log tails in CI. Locally, `nix log .#checks.<system>.<name>` shows the stored build log for a failing check.

[PR publication](../.github/workflows/publish-pr.yml) runs the trusted workflow from `main` after successful CI. It checks that the tested SHA still belongs to an open same-repository PR against `main`, then publishes those archives with Skopeo. It does not check out or execute PR code with registry write access. Chart previews use `<base>-pr.<number>` and `<base>-pr.<number>.g<sha>`.

Releases are made by [Presswerk](https://presswerk.dev/) on every push to `main` that brings a release-worthy commit since the last release. The release is declared in the flake's `presswerk.default` output: the version files, the Gitmoji analyzer, the changelog, and the publishers (the five Nix images and the chart on GHCR, the GitHub Release). The CLI comes from the flake's pinned `presswerk` input.

The [release workflow](../.github/workflows/release.yml) runs in two steps. The push run prepares a `🔖 Release vX.Y.Z` commit with the bumped version files and changelog, pushes it to `main` and dispatches the workflow with that commit as the candidate. The candidate run verifies exactly that commit with Nix verification, which pushes the Nix images and the chart to Cachix. The publish job then runs `presswerk publish`, which fetches the images and the chart from Cachix and pushes the tag, the images, the chart and the GitHub Release. Presswerk checks every destination before writing anything, so a failed or cancelled candidate run is safe to repeat:

```sh
gh workflow run release.yml --ref main -f candidate=<full SHA of the release commit>
```

A re-dispatched candidate publishes the same images, since they are matched by store path. Until that candidate is published, the next push run fails because a release is pending. To see what the next release would contain, run `nix run --inputs-from . presswerk -- plan` on an up-to-date `main` (with `GITHUB_TOKEN="$(gh auth token)"`, since it checks the previous GitHub Release). See Presswerk's [recovery guide](https://presswerk.dev/guide/recovery/) for anything else.

See the native builder's [known constraints](https://docs.determinate.systems/troubleshooting/native-linux-builder/) for shared-store filesystem and builder configuration issues.

The pytest check can abort with `SIGILL` inside the native Linux builder VM while loading cryptography's Rust extension. Run `uv run pytest` on the host instead; x86_64 CI runs the full Nix pytest check.
