# Upgrading to skill flakes

The release that ships [#548](https://github.com/thiesgerken/carapace/issues/548) changes how skills run and what the sentinel reviews:

- Skills with commands are Nix flakes. A new service, the [builder](builder.md), builds them, and every session gets their commands on `PATH`.
- Skills are read with `read_skill` instead of being activated. Nothing is granted when a skill is read.
- The sentinel reviews the sandbox boundary: proxy domains, credentials, up-front requests (`cgate request`) and pushes to the knowledge repo. Commands (`exec`) and other tool calls run without review and are kept in the action log.

There is no compatibility mode. Skills that declare `network`, `credentials`, `commands` or `mcp` in their `SKILL.md` stop working until they are converted. They show up as broken, with an error that says what to do. This guide walks through an upgrade in the order you need it.

## Before you upgrade

- Pick a long random builder token, e.g. `openssl rand -hex 20`.
- Kubernetes: check that the nodes support user namespaces for pods ([below](#kubernetes)).
- Docker on Ubuntu 23.10 or later: check the AppArmor setting for user namespaces ([below](#docker-compose)).
- List the skills in your knowledge repos that have a `metadata.carapace` block with `network`, `credentials`, `commands` or `mcp`. Those with `commands` or `mcp` need a flake ([below](#converting-a-skill)); those with only `network` or `credentials` just lose those fields. Skills that only carry instructions keep working.
- Running sessions lose their activated skills during the upgrade (see [Sessions](#sessions)). Let long tasks finish first.

## Deploy the builder

The server needs the builder to build skill flakes. Without one, the server starts and logs a warning, and skills with commands are not built. For the details, see [builder.md](builder.md).

### Docker Compose

The new `docker-compose.yml` has two more services, `builder-init` and `builder`, and a volume `builder-nix`. If you keep your own Compose file, copy them, along with the server's new `CARAPACE_BUILDER_*` variables. Keep its sandbox network `internal: true` as in the shipped file: the server's [egress self-test](security.md#start-up-egress-self-test) runs on Docker too and stops the server if a sandbox can reach the internet directly.

1. Add the token to `.env`:

   ```env
   CARAPACE_BUILDER_TOKEN=<your token>
   ```

   Compose refuses to start without it.
2. On Ubuntu 23.10 and later, allow user namespaces for unconfined processes, or the builder exits. The setting applies to the whole host ([builder.md](builder.md#docker-compose)):

   ```sh
   echo 'kernel.apparmor_restrict_unprivileged_userns = 0' | sudo tee /etc/sysctl.d/60-carapace-builder.conf
   sudo sysctl --system
   ```

   Docker Desktop, Debian and Fedora need nothing.
3. Run `docker compose pull && docker compose up -d`.

The builder sits only on the default network, out of reach of sandboxes.

### Kubernetes

The chart deploys the builder by default (`builder.enabled: true`), into its own namespace `<release namespace>-builder`. The chart creates that namespace with the label `pod-security.kubernetes.io/enforce: privileged`. `helm uninstall` removes it together with the builder's store, which is only a cache. A generated Secret holds the token.

- **Nodes.** The builder pod runs with `hostUsers: false` and `procMount: Unmasked`. The nodes need user namespaces for pods: a recent kernel and container runtime, plus the `UserNamespacesSupport` and `ProcMountType` features ([builder.md](builder.md#kubernetes)). Without them the builder logs that the Nix build sandbox is not effective and exits.
- **Namespaces managed elsewhere** (GitOps): set `builder.createNamespace: false`, and create the namespace with the `privileged` label yourself.
- **Pod Security.** Nothing privileged runs in the release namespace, so it can be labelled `pod-security.kubernetes.io/enforce: baseline`.
- **No user namespaces** in the cluster: run the builder on another machine and set `builder.enabled: false`, `builder.externalUrl`, `builder.externalCacheUrl` and `builder.auth.existingSecret` ([builder.md](builder.md#on-a-separate-machine)).
- **Storage.** The builder's store takes a PVC, 20Gi by default (`builder.persistence.size`).
- **Start-up.** The server's startup probe allows 60 failures instead of 20. Before it serves, the server runs an [egress self-test](security.md#start-up-egress-self-test) that creates one sandbox pod. If you override the probes, keep that room.

### Without Compose or the chart

Run the builder image as in [builder.md](builder.md#on-a-separate-machine), then give the server `CARAPACE_BUILDER_URL`, `CARAPACE_BUILDER_CACHE_URL` and `CARAPACE_BUILDER_TOKEN`. The two URLs go together. A URL without a token stops the server at start.

## Sandboxes

- **The image is built with Nix**, not from Debian. There is no `apt`. Agents install software with `nix run nixpkgs#…`, `uv` or `npm`, and downloaded binaries run through nix-ld ([sandbox.md](sandbox.md#sandbox-image)). If your `AGENTS.md`, `SOUL.md` or a skill tells the agent to `apt-get install`, change that.
- **Fewer tools in the image.** kubectl, poppler-utils and the `pnpm` and `yarn` shims are gone (Node's bundled `corepack` stays). A skill that calls them adds them to its flake (`exec = "${pkgs.kubectl}/bin/kubectl"`, or `runtimeInputs` of a script, see [skill-flakes.md](skill-flakes.md#plain-nixpkgs)); for one-off use the agent runs `nix shell nixpkgs#poppler-utils -c pdftotext …`.
- **Memory.** Evaluating nixpkgs takes about 1.3 GiB, so sandboxes get a 2 GiB memory limit: the Docker runtime sets it, and the chart's `sandbox.resources.limits.memory` defaults to it. If you override that value, keep at least 2Gi.
- **Disk.** On Kubernetes, the skill commands and their store paths live in the container layer, and sandboxes request 2Gi of ephemeral storage (`sandbox.resources.requests.ephemeral-storage`). Raise it for large skill sets ([sandbox.md](sandbox.md#skill-commands-on-path)).
- **Internal destinations.** The session proxy now refuses private, loopback, link-local and cluster-internal addresses. A skill that talks to a host on your LAN (a homelab service, a NAS) gets a `403` until you allow it ([sandbox.md](sandbox.md#internal-destinations)). Each domain still needs an approval.

  | Compose (`.env`) | Helm |
  | --- | --- |
  | `CARAPACE_SANDBOX_PROXY_ALLOWED_NETWORKS=["192.168.178.0/24"]` | `sandbox.allowedInternalNetworks` |
  | `CARAPACE_SANDBOX_PROXY_ALLOWED_HOSTS=["paperless.home.arpa"]` | `sandbox.allowedInternalHosts` |

## Settings

- `agent.max_sentinel_calls_per_tool_call` is now `agent.max_sentinel_calls_per_exec`. The setting lives only in the platform settings, and the database migration renames it there. Nothing to do by hand.
- `CARAPACE_SANDBOX_SKILL_ACTIVATOR_TIMEOUT_SECONDS` is gone, because nothing is activated any more. The server ignores it, so you can delete it.
- Kubernetes without the chart: set `CARAPACE_SANDBOX_K8S_SERVER_SERVICE` to the name of the server's Service. Sandboxes reach the proxy at its ClusterIP, and the server refuses to start without it. The chart sets it to the release name.

## Knowledge repos

Each user's knowledge repo needs the same three checks. Make the changes in a clone of the repo and push them, or ask the agent to do it. Either way the push goes through the sentinel like any other.

### Bundled skills

Bootstrap only seeds bundled skills that are missing, so an existing repo keeps its old copies:

- `carapace`, `web` and `wikipedia` declare commands in their frontmatter, so they show up as broken. Their new versions are flakes.
- `ferret` declares `mcp`, so it breaks too. It is disabled by default.
- `create-skill` and `credentials` stay valid but are stale: they still teach frontmatter declarations and `use_skill`.
- `example` is no longer bundled. The helper examples in [`nix/skills/examples`](../nix/skills/examples) replace it.

To get the new versions, delete the old copies and restart the server. On start, bootstrap seeds every missing bundled skill and commits it:

```sh
git rm -r skills/carapace skills/web skills/wikipedia skills/ferret skills/create-skill skills/credentials skills/example
git commit -m "Remove pre-flake bundled skills"
git push
# then restart the server
```

Re-seeded skills come with their shipped defaults. `web` and `ferret` are disabled again; set `metadata.carapace.disabled: false` to turn them back on. A vault path you had changed in the old frontmatter now goes into the skill's `flake.nix` (`web`: `credentials.BRAVE_API_KEY`; `carapace`: the `server` and `apiKey` bindings at the top of its `flake.nix`). Copies you had changed beyond that need converting like your own skills (below).

`CARAPACE_RESET_ASSETS=true` overwrites the bundled skills and `SECURITY.md` in place, but leaves files that the new versions no longer have (`setup.sh`, the old `pyproject.toml` of `carapace`). Prefer deleting the copies.

### `SECURITY.md`

`SECURITY.md` is only seeded into repos that have none, so yours still describes reviews of `exec` and skill activation. The sentinel uses it as written: a stale policy breaks nothing, but it asks the sentinel to judge things it no longer sees. Compare yours with [`src/carapace/assets/SECURITY.md`](../src/carapace/assets/SECURITY.md) and follow [Upgrading an existing SECURITY.md](security.md#upgrading-an-existing-securitymd). If you never changed it, delete it and restart, and bootstrap seeds the new one.

### Your own instructions

Look through `AGENTS.md`, `SOUL.md` and your skills for what no longer exists: `use_skill`, `exec(…, contexts=[…])`, `/workspace/.carapace/bin`, `setup.sh` activators, and MCP tools named `<server>_<tool>`. The agent now reads a skill with `read_skill` and runs its commands by name.

## Converting a skill

A skill with `commands` or `mcp` gets a `flake.nix` and a `flake.lock` next to its `SKILL.md` ([skill-flakes.md](skill-flakes.md)), and the fields that used to be in its frontmatter move into the flake. A skill that only declared `network` or `credentials`, for ad-hoc use without commands, needs no flake: delete those fields, and its domains are reviewed when a command reaches them, its credentials fetched with `ccred get`.

| Old frontmatter (`metadata.carapace`) | In the flake |
| --- | --- |
| `network.domains` | `needs.domains`, per skill or per command |
| `network.tunnels` (`host`, `remote_port`, `local_port`) | `needs.tunnels = [ "host:port" ]`. The client connects to the real host and port: `/etc/hosts` sends the name to a local forwarder, so there is no `local_port` any more ([sandbox.md](sandbox.md#tunnels)). The host must be a name, not an IP address, and a host on your LAN also needs the [internal-destination allowlist](#sandboxes) |
| `credentials` with `env_var` | `needs.credentials.<VAR> = "<vault path>"` |
| `credentials` with `file` | the command fetches it itself: `ccred get <vault path> -o <file>` ([credentials.md](credentials.md#skill-declared-credentials)) |
| `credentials` with `base64` | the command decodes the value itself |
| `credentials` with neither `env_var` nor `file` | nothing: the agent fetches them with `ccred get <vault path>` when it needs them |
| `commands` (`name`, `command`) | `mkSkill { commands.<name> = { exec = …; description = …; }; }`. A `uv run --directory …` becomes `"${skill.uvEnv { root = ./.; }}/bin/<script>"` |
| `mcp` (HTTP, `auth.type: bearer` or `oauth`) | `skill.mcpCommands { <name> = { url = …; bearer = "<vault path>"; description = …; }; }` (or `oauth = "<vault path>"`). The URL must be `https://` with a host name: `http://` and IP addresses fail the evaluation. `description` is required ([skill-flakes.md](skill-flakes.md#mcp-servers)) |
| `mcp` (stdio, `command`) | `skill.mcpCommands { <name> = { command = …; description = …; needs.credentials… }; }` |
| `disabled`, `hints` | stay in the frontmatter |

Then delete `network`, `credentials`, `commands` and `mcp` from the frontmatter. Their presence is what marks the skill as broken.

The bundled `web` skill shows the whole conversion. Before, in `SKILL.md`:

```yaml
metadata:
  carapace:
    network:
      domains: [api.search.brave.com]
    credentials:
      - vault_path: vault/brave-api-key
        env_var: BRAVE_API_KEY
    commands:
      - name: web_search
        command: uv run --directory /workspace/skills/web web_search
```

After, in `flake.nix` (inputs as in [skill-flakes.md](skill-flakes.md#the-flake)):

```nix
default = skill.mkSkill {
  name = "web";
  commands.web_search = {
    exec = "${env}/bin/web_search";
    description = "Search the web with Brave Search";
    needs = {
      domains = [ "api.search.brave.com" ];
      credentials.BRAVE_API_KEY = "vault/brave-api-key";
    };
  };
};
```

The steps:

1. Write `flake.nix`. Python skills with `pyproject.toml` and `uv.lock` use `uvEnv`. Node skills use `npmApp` with `package-lock.json`. Skills that only call tools need neither: their commands come straight from nixpkgs. Copy from [`nix/skills/examples`](../nix/skills/examples).
2. Lock it and try a command from the workspace, without pushing: `nix flake lock path:./skills/<name>`, then `nix shell path:./skills/<name> -c <command>`.
3. Delete what the flake replaces: `setup.sh`, the old frontmatter fields, and a `.venv` if one was committed.
4. Commit `flake.nix`, `flake.lock` and the sources, then push. The builder builds the skill after the push, and its Knowledge view shows the build state.

The agent can do this itself: the bundled `create-skill` skill covers the flake format. If a build fails, the skill has no commands on `PATH`, and `read_skill` returns the end of the build log.

## Sessions

The database migrations run on start:

- They drop every session's activated skills and context grants, together with the `skill_activated` and `context_grant` entries in the sentinel's action log.
- They rename `max_sentinel_calls_per_tool_call` in the platform settings.
- They turn the sentinel's old `revise` verdicts into denials, so old sessions show them as denied.

A session that was running keeps its conversation. If the agent calls `use_skill` again, it gets "unknown tool" and moves on to `read_skill`. The commands are on `PATH` once the skill is built.

Old turns keep their recorded `gate` spans in the [debug view](debug-view.md). New turns have none.

## Checking the upgrade

1. The server log shows no builder warning at start, and the egress self-test passes.
2. In the Knowledge view, every enabled skill with a flake shows a successful build. Disabled skills (`web` and `ferret` after re-seeding) are not built.
3. Ask the agent to use a skill with commands, e.g. `wikipedia`. It calls `read_skill`, which waits for the build and the profile sync, then runs the command. Its wrapper first sends an up-front `cgate request` for the Wikipedia domains, which the sentinel decides, or you if the sentinel escalates.
