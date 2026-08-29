# CEP-001: Sandbox-provided skill activator

**Status:** Implemented in this pull request.

## Summary

Move all automatic skill activation behavior out of Carapace core and behind one activator supplied by the sandbox image.

Carapace continues to own `use_skill`, security approval, activation lifecycle, and command shims. The sandbox activator owns runtime materialization. It may perform side effects such as `uv sync`, `pnpm install`, `setup.sh`, or realizing Nix packages. It may also return command overrides that Carapace installs through its existing shims.

## Motivation and use case

Carapace currently detects package-manager and hook files in server code through `SKILL_ACTIVATION_PROVIDERS`. It runs uv, npm, pnpm, and `setup.sh` in a fixed order. This only works when the selected sandbox image contains those tools and supports their assumptions, so the behavior belongs to the execution layer provided by that image.

The motivating deployment uses a custom Nix-based sandbox:

- The workspace has one committed and locked root flake.
- Skills contribute Nix modules and packages.
- CI and a binary cache provide package closures.
- Running `nix develop` for every skill command is too expensive.
- Multiple skills should not require composing devshell environments.
- Carapace core should not gain Nix-specific behavior.

A Nix activator can realize all packages for one skill in one invocation and return direct store-backed commands.

## Goals

- Move the complete current activation-provider chain into the official sandbox image.
- Let custom sandbox images replace that behavior without changing Carapace core.
- Preserve the existing `metadata.carapace.commands` schema and concrete command semantics.
- Allow activation-time side effects and optional command overrides through one extension point.
- Resolve or prepare all commands for one skill in one activator invocation.
- Run the activator only at explicit lifecycle synchronization points, such as initial skill loading and sandbox recreation.

## Non-goals

- Nix-aware behavior in Carapace core.
- PATH composition between skills.
- A general multi-phase lifecycle-hook framework.
- File watching, input fingerprints, or automatic reactivation after workspace edits.
- Re-resolution or a manual refresh tool.

## Existing skill schema

Existing skills continue to declare concrete commands:

```yaml
metadata:
  carapace:
    commands:
      - name: web_search
        command: uv run --directory /workspace/skills/web web_search
      - name: web_fetch
        command: uv run --directory /workspace/skills/web web_fetch
```

The activator receives these declarations. For each command it may either:

1. Return a command override.
2. Omit the command, causing Carapace to use the original declared command unchanged.

The official activator can therefore reproduce current behavior by preparing dependencies, running `setup.sh` when present, and returning no overrides. A custom activator can instead use the alias name or its own skill-file conventions to return another command without changing the skill schema.

No activator command is embedded in skill metadata. The activator is selected by the deployment, not by the skill.

## Activator configuration

A compatible sandbox image provides one activator executable at an operator-configured absolute path:

```text
CARAPACE_SANDBOX_SKILL_ACTIVATOR=/usr/local/bin/carapace-skill-activator
CARAPACE_SANDBOX_SKILL_ACTIVATOR_TIMEOUT_SECONDS=600
```

The path must be absolute and outside `/workspace`, `/tmp`, `/var/tmp`, and `/dev/shm`. Activator integrity remains a deployment requirement; core does not prove that the configured file is immutable. The official Carapace sandbox image ships the default implementation. Docker Compose and the Helm chart configure its path. A custom sandbox image may provide a different implementation at that or another path.

When no activator is configured, Carapace uses no-op activation: it performs no runtime preparation, receives no command overrides, and installs the originally declared commands unchanged. A configured path that is missing or not executable is an activation error.

Carapace core does not retain the legacy uv, npm, pnpm, or `setup.sh` provider chain as a fallback. No-op activation is therefore an intentional execution-layer compatibility break for configurations that omit the activator: a command such as `uv run ...` is preserved, but the preceding `uv sync` no longer happens. This avoids keeping two activation implementations indefinitely and does not require a skill-schema migration.

## Conceptual activator protocol

Carapace invokes the activator once per skill with all declared commands:

```json
{
  "protocol_version": 1,
  "skill": "web",
  "skill_dir": "/workspace/skills/web",
  "workspace": "/workspace",
  "source_revision": "0123456789abcdef0123456789abcdef01234567",
  "commands": [
    {
      "name": "web_search",
      "command": "uv run --directory /workspace/skills/web web_search"
    },
    {
      "name": "web_fetch",
      "command": "uv run --directory /workspace/skills/web web_fetch"
    }
  ]
}
```

It returns optional command overrides and status messages:

```json
{
  "protocol_version": 1,
  "command_overrides": {
    "web_search": "/nix/store/...-web-search/bin/web_search",
    "web_fetch": "/nix/store/...-web-fetch/bin/web_fetch"
  },
  "messages": ["Realized 2 skill commands."]
}
```

`protocol_version` identifies the protocol spoken by both sides and must equal `1`. `source_revision` is the exact committed knowledge-repository object ID selected by core. The activator decides which inputs it consumes from that revision and how it restores or materializes them. Core never resets the complete skill directory.

`command_overrides` replaces only the listed aliases; an omitted command always uses its original declaration. Overrides use the same shell-command semantics as existing skill commands and may include arguments or environment preparation.

`messages` contains model-facing activation status. Messages must be short, non-sensitive, single-line summaries authored by the activator. Carapace does not pass package-manager or hook output through automatically.

Carapace invokes the executable as:

```text
<activator> --request-base64 <base64-encoded-request-json>
```

The activator writes exactly one response line to stdout, prefixed with `@@CARAPACE_SKILL_ACTIVATOR@@`. Other output is diagnostic only. Exit status zero requires a valid success response. A failure may return a safe, single-line error response before exiting nonzero:

```json
{
  "protocol_version": 1,
  "error": "setup.sh failed with status 1"
}
```

Unknown protocol versions, timeouts, nonzero exits, missing responses, invalid JSON, undeclared override aliases, and invalid command strings fail automatic setup. The default 600-second timeout covers the complete one-skill invocation. It reuses the existing runtime timeout behavior, which is best-effort and does not guarantee that every container backend kills the process.

Carapace validates the complete response before installing shims. Activator side effects are not rolled back. On failure, no new shims are installed, the skill remains active, and current best-effort error reporting is preserved.

## Lifecycle

The activator runs at these explicit synchronization points:

1. Initial `use_skill` activation.
2. Sandbox recreation, before an already activated skill is used again.

No automatic reactivation occurs when workspace files change. Skill development and explicit refresh behavior can be considered separately if needed later.

## Official sandbox activator

The official implementation moves the full current provider chain out of the server and preserves its order and behavior. It detects provider files in `source_revision`, restores only the matching provider inputs into the live skill directory with `git checkout`, then runs:

1. `pyproject.toml` plus `uv.lock` runs `uv sync --locked`.
2. `package.json` plus the npm lockfile runs `npm ci` when pnpm does not apply.
3. `package.json` plus `pnpm-lock.yaml` runs `pnpm install --frozen-lockfile`.
4. `setup.sh` runs `sh ./setup.sh`.

These operations primarily materialize runtime state and may return no command overrides. `setup.sh` belongs here because it is currently an equal activation provider and acts as the generic runtime-preparation mechanism when no specialized provider is sufficient.

A separate lifecycle-hook system may still be useful for events unrelated to skill runtime preparation, but it is outside this CEP.

## Credentials and network policy

The activator preserves the current provider behavior. It receives every successfully resolved, approved skill credential declared with an `env_var` or `file`, and runs with proxy bypass for the invocation. Credentials are not included in the JSON request. Environment credentials are scoped to the process. File credentials are materialized immediately before activation and deleted afterwards.

No additional capability settings are introduced in protocol version 1. The activator is trusted operator-selected deployment code, while skills still cannot grant credentials or network capabilities beyond their approved declarations. A capability switch can be added later if a concrete deployment needs to separate command-time credentials from activation credentials.

## Security model

The activator is trusted deployment code. The skill files, manifests, package definitions, and `setup.sh` it consumes remain untrusted activation input.

Core-enforced controls:

- The activator path is configured by the operator and cannot be overridden by skill metadata.
- The path is absolute and lexically outside writable workspace and temporary directories.
- The activator runs only after `use_skill` security approval.
- Core supplies the exact committed source revision in the request.
- Returned overrides may reference only commands declared by the skill.
- Every response and override is validated before Carapace replaces command shims.

Deployment requirements:

- Activator code must be immutable to the agent through an immutable image path, read-only mount, Nix store path, or an unprivileged agent combined with root-owned files.
- A writable container root filesystem is insufficient when agent commands run as root.
- The activator must select automatically executed inputs from `source_revision`, rather than trusting arbitrary replacements in the live workspace.

Carapace does not attempt to enforce image immutability consistently across Docker and Kubernetes as part of this feature. Activator confidentiality is not a security boundary. Read access can aid auditing. Integrity, not secrecy, is required.

## Alternatives considered

### Keep the current provider chain as a fallback

Rejected because it duplicates activation logic across core and the sandbox image and makes the legacy path difficult to remove. This CEP instead accepts coordinated server and image upgrades.

### Command resolver only

Rejected as too narrow. Current uv, npm, pnpm, and `setup.sh` providers primarily perform side effects and do not resolve commands. Optional command overrides are one output of activation, not the whole abstraction.

### General lifecycle-hook framework

Deferred because the current need has one clear event and contract: prepare a skill runtime during activation. Multiple hook phases would add complexity without serving the motivating use case.

### PATH or devshell injection

Rejected because it introduces global lookup order, collision, environment-composition, and shell-hook questions across several active skills.

### Activator commands in skill frontmatter

Rejected because they make deployment-specific execution skill-controlled and recreate arbitrary automatic shell execution in the schema.

## Packaging and deferred work

The official sandbox image installs a standalone executable at `/usr/local/bin/carapace-skill-activator`. Custom images may copy it from the official image or replace it. The JSON protocol is the compatibility boundary; there is no library or subclass API.

Deferred until a concrete need appears:

- Per-activator credential or network capability switches.
- Strong process termination guarantees after timeout.
- Core-enforced read-only roots or non-root sandbox execution.
- Filesystem rollback after partial activation side effects.
- Manual refresh, file watching, or activation fingerprints.
