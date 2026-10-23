# Development

The committed Nix flake and lockfile own builds, checks, and runtime images. Python dependencies come from `uv.lock` through uv2nix, preferring wheels on Python 3.14. Frontend dependencies come from `frontend/pnpm-lock.yaml`; the exact pnpm release is in `frontend/package.json`. The sandbox remains a Debian Dockerfile because agents install packages at runtime and need an FHS-compatible loader.

The local Python package source includes only `pyproject.toml`, `README.md`, and `src/`. Python check inputs are scoped separately, so changes under `docs/`, `charts/`, or `frontend/`, and changelog updates, do not invalidate Python builds and checks.

The server, Python checks, and native developer shell use the same Python 3.14 override, with `stripConfig`, `stripIdlelib`, and `stripTests` enabled. This removes the static interpreter archive and development-only standard-library files without changing the wheel ABI. The customized interpreter builds from source on a cold store; trusted release CI caches Linux x64 builds in Cachix.

## Native developer shell

```sh
nix develop
uv sync --dev
```

The shell provides Python 3.14, uv, Node.js 24, pinned pnpm, Git, Helm, Skopeo, and jq. uv manages `.venv`; `UV_PYTHON` selects the Nix interpreter and `UV_PYTHON_DOWNLOADS=never` prevents another interpreter download. With direnv and nix-direnv, run `direnv allow` once in each checkout or worktree to load `.envrc` automatically.

For host iteration, start a disposable Redis, build the sandbox, then run the server:

```sh
docker run --rm -d --name carapace-dev-redis -p 127.0.0.1:6379:6379 redis:8-alpine
docker build -t carapace-sandbox:local sandbox
export CARAPACE_SANDBOX_BASE_IMAGE=carapace-sandbox:local
export CARAPACE_DATA_DIR=./data/development
export CARAPACE_CACHE_REDIS_URL=redis://localhost:6379/0
export CARAPACE_DATABASE_URL=sqlite+pysqlite:///./data/development/carapace.db
uv run carapace-server
```

Stop the disposable Redis with `docker stop carapace-dev-redis`. The SQLite URL keeps development SQL storage local. For Postgres-backed host iteration, expose a separate development Postgres port and set `CARAPACE_DATABASE_URL` accordingly; keep development data separate from an existing deployment.

In another shell:

```sh
pnpm --dir frontend install --frozen-lockfile
pnpm --dir frontend dev
```

Next.js serves port 3000 and proxies `/api` to `http://127.0.0.1:8321`; set `CARAPACE_BACKEND_URL` for a different host server. Compose images are immutable and no longer bind-mount `src/carapace`. Use `uv run` for live server code.

## Native Linux images on Apple Silicon

Install [Determinate Nix](https://docs.determinate.systems/) and authorize its Native Linux Builder with a free FlakeHub account:

```sh
determinate-nixd auth login
determinate-nixd status
nix build .#packages.aarch64-linux.server-image --out-link result-server-image
nix build .#packages.aarch64-linux.frontend-image --out-link result-frontend-image
nix build .#packages.aarch64-linux.bitwarden-image --out-link result-bitwarden-image
for image in result-{server,frontend,bitwarden}-image; do docker load -i "$image"; done
docker build --platform linux/arm64 -t carapace-sandbox:local sandbox
export COMPOSE_FILE=docker-compose.yml:docker-compose.local.yml
docker compose up -d
```

These are native ARM Linux builds, not x86 emulation. Only x86_64 Linux images are published. Non-Nix x64 users pull release images as described in the [quickstart](quickstart.md).

On Linux x64, omit `packages.aarch64-linux.` from the Nix output paths and omit the sandbox `--platform` argument. The local Compose overlay selects `:local` images with `pull_policy: never` and points the server at `carapace-sandbox:local`.

The server, frontend, and Bitwarden images use UID/GID 999, a read-only root, dropped capabilities, and writable `/tmp`. The server data directory and Bitwarden state need persistent writable mounts. The frontend listens on 8080; Compose's proxy and the chart keep their public ports unchanged.

The Bitwarden runtime keeps the upstream bundle and the transitive package closure of its literal `require()` calls, preserving nested `node_modules` resolution and required peers. Its install check loads every discovered external from the installed bundle's directory. The wrapper and auxiliary script shebangs use the matching slim Node.js 22 interpreter, keeping the npm-enabled toolchain out of the runtime closure. The sidecar entrypoint is unchanged.

## Checks and runtime smoke

On Linux:

```sh
nix flake check
```

`checks.<system>` includes `pytest`, `pyrefly`, `ruff`, `frontend-lint`, `frontend-test`, `frontend-build`, and `helm`. For the commands below, `<system>` is `x86_64-linux` or `aarch64-linux`.

The check derivations substitute the activator's deliberately absolute FHS executable paths only in their private source copy, using `--replace-fail`; the deployed sandbox script is unchanged. SHA-256-pinned `cl100k_base` and `o200k_base` BPE files populate a shared tiktoken cache used by checks and the server image, so tokenization needs no first-use network download on a fresh pod.

Checks set `SSL_CERT_FILE` to the pinned CA bundle because HTTP clients initialize TLS even when tests do not make network requests.

```sh
nix build .#checks.<system>.pytest
nix build .#ciBuilds.<system>.server-image
```

On Apple Silicon, `nix flake check --system aarch64-linux` runs the Linux checks through the builder. A plain `nix flake check` also evaluates the native macOS development/tooling outputs.

`ciBuilds.<host-system>` contains every mandatory check, runtime package/image, and CI/release tool profile. To realize them with the locked runner:

```sh
nix build --inputs-from . nixpkgs#nix-fast-build --out-link result-build-tool
# Linux x64:
result-build-tool/bin/nix-fast-build --no-nom --flake .#ciBuilds.x86_64-linux --systems x86_64-linux --out-link result-ci
# Apple Silicon:
result-build-tool/bin/nix-fast-build --no-nom --flake .#ciBuilds.aarch64-darwin --systems "aarch64-darwin aarch64-linux" --out-link result-ci
```

Load the three runtime images, build the native sandbox image, and run:

```sh
python3 scripts/smoke-images.py
```

The smoke uses disposable volumes and dynamic ports. It checks authenticated server readiness with Postgres and Redis, rejects a real knowledge-repo push through the sentinel for a missing session, verifies effective UID 999 and read-only roots, and checks default and overridden frontend CSP headers. Bitwarden runs without a network under the runtime restrictions: status, password generation, server configuration round-trip, and the explicit unauthenticated `bw serve` rejection. No LLM credentials or vault account are needed. Real vault login, unlock, sync, and an authenticated Bitwarden API listener remain outside this smoke.

Focused host checks remain available:

```sh
uv run pyrefly check
uv run pytest
uvx ruff check src/
pnpm --dir frontend lint
pnpm --dir frontend test
helm lint charts/carapace
```

`prek run` remains separate because its hooks fetch from the network.

## Dependency refresh

Renovate updates `flake.lock`, uv, frontend dependencies, and image digests. After a pnpm version or frontend lockfile change, run:

```sh
python3 scripts/update-nix-deps.py
```

The command refreshes official pnpm binary hashes when needed and verifies the `fetchPnpmDeps` content hash. It selects ARM Linux on Apple Silicon; `--system x86_64-linux` selects x64. Commit the pin/hash updates with the dependency change. Frontend dependency PRs are not auto-merged because this refresh is manual.

Frontend fonts are licensed variable WOFF2 inputs committed in `frontend/src/fonts/`, with notices in `frontend/public/fonts/`. Twemoji's pinned archive is fetched by Nix; `postFetch` retains only `v/17.0.2/svg` in the store. The build prepopulates the existing emoji script cache, so the script needs no network access. If its pinned Twemoji revision/version changes, update `nix/frontend.nix` and refresh `nix/twemoji-hash` with the fixed-output mismatch reported by Nix.

The only Python source-build override supplies setuptools to `http-ece`, whose release has no wheel. Keep overrides tied to observed build failures.

## CI and publishing

[CI](../.github/workflows/ci.yml) calls [Nix verification](../.github/workflows/nix-verify.yml). Workflows read the public [`thiesgerken` Cachix cache](https://thiesgerken.cachix.org) and skip outputs already in it; only release runs push to it, so PR builds never write it. The flake offers the cache to local builds through `nixConfig` (accept it when Nix asks; it takes effect for trusted users). It holds only x86_64-linux outputs. PR verification has read-only repository access, builds the sandbox, smoke-tests loaded images, and uploads the verified x64 image archives and chart data.

Failed Nix builds retain expanded log tails in CI. Locally, `nix log .#checks.<system>.<name>` shows the stored build log for a failing check.

[PR publication](../.github/workflows/publish-pr.yml) runs the trusted workflow from `main` after successful CI. It checks that the tested SHA still belongs to an open same-repository PR against `main`, then publishes those archives with Skopeo. It does not check out or execute PR code with registry write access. Chart previews use `<base>-pr.<number>` and `<base>-pr.<number>.g<sha>`.

[Releases](../.github/workflows/release.yml) version with semantic-release, verify the resulting tag, publish the verified archives as `<version>` and `latest`, then publish the chart and GitHub release with the uv-built distribution. Semantic-release remains a tooling exception: its PyPI version is pinned, but its transitive dependencies are not locked by the flake.

See the native builder's [known constraints](https://docs.determinate.systems/troubleshooting/native-linux-builder/) for shared-store filesystem and builder configuration issues.

The pytest check can abort with `SIGILL` inside the native Linux builder VM while loading cryptography's Rust extension. Run `uv run pytest` on the host instead; x86_64 CI runs the full Nix pytest check.
