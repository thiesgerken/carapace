# Skill builder

Skills with commands are Nix flakes (see [#548](https://github.com/thiesgerken/carapace/issues/548)). The builder is the service that evaluates and builds them, one per installation, shared by all users. The Carapace server sends it a knowledge repo's `skills/` directory with the name of one skill and gets back store paths and the skill's command metadata. Sandboxes never build pushed skills themselves; they download the results from the builder's [binary cache](#binary-cache). The builder never sees a knowledge repo.

## API

The build API listens on port 8330. Every route except `/healthz` requires `Authorization: Bearer <CARAPACE_BUILDER_TOKEN>`.

| Route | |
| --- | --- |
| `GET /healthz` | Liveness, unauthenticated |
| `GET /info` | `{"system": "x86_64-linux", "cache_public_keys": ["carapace-builder-1:…", "cache.nixos.org-1:…"]}`: the Nix system the builder builds for, and the keys sandboxes trust for its [cache](#binary-cache) |
| `GET /builds/{key}` | The stored result for a build key, or 404 |
| `GET /builds/{key}/files/{path}` | A file of that build's skill directory, as raw bytes. 404 for a missing file or a result without a skill directory, 400 for a path out of the directory, a symlink, a directory or a file over 1 MiB |
| `PUT /builds/{key}?skill=<name>` | Body: the `skills/` directory as a tar archive (gzip or plain), e.g. `git archive HEAD:skills`. Builds skill `<name>`, stores and returns the result. `&retry=true` builds a key again whose stored result failed |
| `POST /updates?input=<name>&input=…` | Body: the `skills/` directory as a tar archive. Runs `nix flake update <name> --output-lock-file <tmp>` for each input on its own and returns `{"inputs": {"<name>": {"lock": "…", "log_tail": "…"}}}`: the lock that update would write, or `null` with the log when it failed. Stores nothing ([update checks](skills.md#updates)) |
| `PUT /roots` | Body: `{"keys": [...]}`, the build keys of the skills at the current heads (see [garbage collection](#garbage-collection)). 204 |
| `POST /gc` | Runs garbage collection now and returns `{"dropped": [keys], "log_tail": "…"}` |

`{key}` is a sha256 (64 hex characters) the server computes over everything the skill's build depends on ([skills.md](skills.md#building-skills)). It is the cache key: a key that has a result, succeeded or failed, is answered from it without building (unless it failed and `retry` is set), and its archive is not even read. The key is the caller's claim: the builder does not recompute it from the archive, and keeping key and archive together is the server's job. A wrong key sticks until it is retried or collected. `<name>` is an attribute of `packages.<system>` in `skills/flake.nix`: a letter or `_`, then letters, digits, `_`, `'` or `-`, since it ends up in a flake reference.

`PUT` blocks until the build ends, which takes seconds for a small change and a few minutes for a cold uv skill. Requests for the same key wait for each other; different keys build in parallel. Callers must not hold up a push or a session on it.

A result:

```json
{
  "key": "9f2b6c1e…",
  "skill": "web",
  "state": "succeeded",
  "store_paths": ["/nix/store/…-skill-web"],
  "metadata": {"commands": {"…": "…"}},
  "log_tail": "…"
}
```

`state` is `succeeded` or `failed`. A failed result has no store paths, and `log_tail` holds the end of the evaluation and build output (16k characters) that says why. Failed results are stored like successful ones.

### What the builder builds

For skill `<name>` of a `skills/` directory with `flake.nix` and `flake.lock`, on system `<system>`:

- **Declarations:** `nix eval --json --no-update-lock-file path:<dir>#packages.<system>.<name>.passthru.carapace --apply 'c: { inherit (c) settings credentials; }'`, what the skill declares (settings with type, description and default; credential slots with type and description) without this instance's values. Returned as `declarations` even when the manifest then fails, so the Knowledge view can offer the setting or slot a skill is missing; `null` when the package does not evaluate or declares something this builder cannot read.
- **Manifest:** `nix eval --json --no-update-lock-file path:<dir>#manifests.<system>.<name>`, before the build, so a mistake in the declarations or in `skills/config.json` fails before anything builds. The builder passes this JSON through as `metadata`, looking only at `enable`: a skill that is off (`{"enable": false}`) is not built. `skillsFlake` defines its schema ([skill-flakes.md](skill-flakes.md#the-manifest)), and the server reads it. A skills flake without `manifests` fails with a hint to write its outputs with `skillsFlake`.
- **Outputs:** `nix build --no-update-lock-file path:<dir>#packages.<system>.<name>`. `store_paths` lists every output of that package. `mkSkill` puts the command wrappers into it, and a reference to the skill directory (a store path of its own) that brings it along. Only that attribute is evaluated, so another skill's mistakes do not fail it.
- **Skill directory:** right after the evaluation, the builder takes `skillDir` from the manifest (it must be a top-level store path) and reads `SKILL.md` and the list of regular files from it, never following a symlink. The result carries them as `skill_dir`, `skill_md` and `skill_files`, also when the build then fails. A manifest without `skillDir` leaves them empty.
- **Locks:** a missing `flake.lock` is a failed build, and so is one that lacks an input (`--no-update-lock-file`). The builder never writes lock files.
- **Evaluation:** import-from-derivation is off, and a flake's `nixConfig` is ignored.

An update check (`POST /updates`) fetches each input's upstream with `nix flake update <name>`, which evaluates the inputs' `flake.nix` but builds nothing. Only that input moves, so `nixpkgs` and `carapace` stay as locked, and one input that cannot be fetched does not hide the others. It fetches into a throwaway store under the work directory, not the daemon's: an update locks whatever a local skill's `flake.nix` names, an unlocked `path:/…` input included, and the daemon's store is what the [binary cache](#binary-cache) serves to every sandbox. Builds don't need this, since `--no-update-lock-file` never fetches an input the lock lacks.

### Architecture

Builder and sandboxes must share one architecture. The builder reports its system at `/info` and builds only for it. The server compares it with its own CPU architecture (sandboxes are Linux on the server's architecture): at start when the builder answers, otherwise before its first request. A mismatch stops the server. An unreachable builder at start only logs a warning, since the builder may come up after the server.

## Binary cache

The cache listens on port 8331, without authentication, and is the only substituter of every sandbox. It answers from the builder's own store first, then from the upstream caches in order:

- **Own store:** harmonia serves it on loopback and signs every narinfo with the builder's key (`carapace-builder-1`), generated on first start and kept on the store volume, readable only by root and harmonia. NARs are zstd-compressed when the client accepts it, which Nix does.
- **Upstreams:** `cache.nixos.org` by default. A narinfo keeps the upstream's signature, which does not cover its `URL:` line, so only that line is rewritten to `upstream/<i>/nar/…`, and the NAR comes through the builder too. Redirects are followed by the builder, to public `https` hosts only (anything else is a 502), never handed to a sandbox. NARs pass through as the upstream compressed them.
- **Errors:** a 404 only when every source says so. An unreachable or failing source is a 502, because Nix remembers a 404 as a missing path.

Only `GET` and `HEAD` of `/nix-cache-info`, `/<hash>.narinfo`, `/nar/<name>` and `/upstream/<i>/nar/<name>` are answered, with hashes and NAR names in Nix's base32 (32 characters for a store hash, 32 to 52 for a NAR) and NAR suffixes `.nar`, `.nar.xz`, `.nar.zst`, `.nar.bz2` or `.nar.br`. Every other path is a 404 and goes nowhere. The build daemon substitutes from the same upstreams.

`CARAPACE_BUILDER_UPSTREAM_CACHES` on the builder (Helm: `builder.upstreamCaches`) sets the upstreams, as a JSON list. It replaces the default instead of extending it, so a list that adds a cache has to name `cache.nixos.org` too:

```env
CARAPACE_BUILDER_UPSTREAM_CACHES=[{"url": "https://cache.nixos.org", "public_key": "cache.nixos.org-1:6NCHdD59X431o0gWypbMrAURkbJ16ZPMQFGspcDShjY="}, {"url": "https://nix-community.cachix.org", "public_key": "nix-community.cachix.org-1:mB9FSh9qf2dCimDSUo8Zy7bkq5CX+/rkCWyvRCYg3Fs="}]
```

[#548](https://github.com/thiesgerken/carapace/issues/548) proposed nginx in front of harmonia for the fall-through. It is a small Python listener in the builder's API process instead: per source it has to tell a 404 (try the next) from an error (stop with a 502), follow redirects itself and rewrite the narinfo's `URL:`, which in nginx means chained `error_page` locations, intercepted redirects and `sub_filter`, plus one more server to run.

Sandboxes reach the cache only through their session proxy, as `http://cache.carapace.internal` (see [sandbox](sandbox.md#builder-cache)).

## Inside the image

`carapace-builder` runs three processes. If one stops, the container stops.

- `nix-daemon` as root owns the store and runs builds as `nixbld*` users with `sandbox = true`, `sandbox-fallback = false` and `max-jobs = auto`. Only root is a trusted user.
- The API as the unprivileged user `carapace-builder` (UID 999). It runs every `nix build` and `nix eval` as a short-lived subprocess, and evaluation happens in that subprocess. So evaluation runs without privileges and without any signing key, and the daemon ignores the settings an untrusted client asks for (`sandbox = false`, for example). It does run as the API's user, so an evaluator escape could read the token and rewrite stored results (see [security](security.md#skill-builder)). Running evaluations as a separate user, which needs the API to switch users per subprocess, is the upgrade path.

- harmonia as the unprivileged user `harmonia` (UID 998), the only user besides root that can read the signing key. It reads the store database directly.
- The API runs the [cache](#binary-cache) listener on port 8331 alongside the build API.

At start, before it listens, the API builds a fresh probe derivation that fails if it can see the store database, which is only visible outside the build sandbox. If the sandbox cannot be set up or is not in effect, the builder exits with the reason in its log.

The store lives on a volume that replaces `/nix`, so it survives restarts and image updates. Built skills and the dependencies they downloaded stay warm. `carapace-builder-init` runs before every start, with the volume at `/mnt/nix`. It copies the image's own store paths into the volume and roots them, so after an update the volume holds the new image's tools, and the old ones become garbage. Results and GC roots for built keys are under `/nix/var/carapace-builder` on the same volume.

## Garbage collection

The builder does not know users or heads; the server tells it. At start, hourly and after every sandbox push, the server sends `PUT /roots` with the build keys of the skills at every user's current head, and the builder notes when it last saw each one. A key no head has referenced for the grace period loses its stored result and its GC root together, so no result ever names a deleted path. The grace period exists because Nix's GC knows nothing about sandboxes still downloading a path a push just replaced. A key that was built but never sent starts its grace period at the first GC run after the build.

GC runs every `CARAPACE_BUILDER_GC_INTERVAL_HOURS` (default 24) with a grace period of `CARAPACE_BUILDER_GC_GRACE_HOURS` (default 24), both on the builder. It drops the expired keys and then runs `nix-store --gc` through the daemon, which deletes everything no root keeps: the outputs of dropped keys, and the build-time dependencies of every skill (compilers, nixpkgs sources), which a later rebuild downloads again. The image's own tools are rooted by `carapace-builder-init`. A failing GC run stops the builder, so the store never grows unnoticed. To run it by hand:

```sh
curl -X POST -H "Authorization: Bearer $CARAPACE_BUILDER_TOKEN" http://builder:8330/gc
```

The server reaches the builder at least hourly, so an unreachable server only lets roots expire after a whole grace period. If that happens, the next lookup of a skill finds no result and builds it again.

### Sizing the store

What stays after a GC run is the runtime closure of every skill the heads reference, about 0.2 to 0.45 GB per uv or npm skill and shared between skills on the same nixpkgs pin, plus about 1 GB for the image's tools. Between runs, each build adds its build-time dependencies on top: about 1.5 GB for a nixpkgs pin the builder has not seen yet, much less for one it has. The chart's default of 20Gi covers a few dozen skills on two or three pins with a daily GC. With many diverging pins, or many pushes per day, give it more disk or shorten the interval.

## Running it

The server builds a skill after a push that changes its key and otherwise on first use (see [skills.md](skills.md#building-skills)). It finds the builder through `CARAPACE_BUILDER_URL`, `CARAPACE_BUILDER_CACHE_URL` (its cache, port 8331) and `CARAPACE_BUILDER_TOKEN`; the two URLs come together. Without them there is no builder, and skills with commands are not built. The server logs a warning at start. `CARAPACE_BUILDER_TIMEOUT_SECONDS` (default 1800) bounds one request.

### Docker Compose

`docker-compose.yml` runs `builder-init` and `builder` with a named volume `builder-nix`, and points the server at `http://builder:8330` and `http://builder:8331`. Set `CARAPACE_BUILDER_TOKEN` in `.env`. The builder is on the default network only, so sandboxes, which sit on the internal `carapace-sandbox-<instance>` network ([instances](sandbox.md#instances)), cannot reach it. Compose has no egress rules: the builder, and so every skill flake it evaluates, reaches whatever the host reaches, your LAN included. To limit that, firewall the container on the host or run the builder on Kubernetes.

The Nix build sandbox needs `security_opt: [seccomp=unconfined, apparmor=unconfined, systempaths=unconfined]`: unshare must be allowed and `/proc` unmasked so that Nix can mount its own. Without all three the builder refuses to start.

Ubuntu 23.10 and later also deny user namespaces to processes without an AppArmor profile (`kernel.apparmor_restrict_unprivileged_userns=1`), which includes the unconfined builder. Allow them on such a host:

```sh
echo 'kernel.apparmor_restrict_unprivileged_userns = 0' | sudo tee /etc/sysctl.d/60-carapace-builder.conf
sudo sysctl --system
```

This switches the restriction off for the whole host, not only for the builder. If that is not acceptable, run the builder on Kubernetes or on another machine. Docker Desktop, Debian and Fedora hosts need nothing extra. The builder never falls back to building without the sandbox: if user namespaces are missing, it logs Nix's reason and exits. Plain Docker has no per-container user namespace, so root in the builder is root on the host, with the default capabilities. That is weaker than the Kubernetes setup (see [security](security.md#skill-builder)).

### Dev stack

The [dev stack](development.md#dev-stack) runs the builder as a container too, from the `builder-image` built from the checkout: `builder-init` and `builder` with the volume `carapace-builder-nix-<instance>`, ports published on loopback at the stack's builder ports (`7506` and `7507` for stack 0). The server reaches it there, sandboxes reach the cache through the session proxy. Stopping the stack removes the container; the volume keeps the store. Set `CARAPACE_BUILDER_TOKEN` in `.env`. As under Compose, nothing limits where the builder connects to.

### Kubernetes

The chart deploys the builder by default (`builder.enabled`). That covers a Deployment with an init container, a PVC (`builder.persistence.size`, default 20Gi), a Service, two NetworkPolicies, and a generated token Secret. One admits only the server on ports 8330 and 8331. The other limits the builder's egress (see [egress](#egress-on-kubernetes)). The pod runs with `hostUsers: false` (root in the pod is an unprivileged host user), `procMount: Unmasked`, and `Unconfined` seccomp and AppArmor profiles. It gets no added capabilities.

The cluster has to support user namespaces for pods. That means a recent kernel and container runtime, plus the `UserNamespacesSupport` and `ProcMountType` features. The settings were verified on k3s 1.37 with containerd 2.3 and kernel 7.3. If the builder logs that the Nix build sandbox is not effective, the node or its runtime lacks one of these. Pod Security Admission levels `restricted` and `baseline` reject the pod (unconfined seccomp, unmasked `/proc`), so the builder needs `privileged`. `hostUsers: false` keeps that from meaning root on the node.

A Pod Security label covers every pod in its namespace, and the server creates sandbox pods in the release namespace. Labelling that namespace `privileged` would lift admission limits on everything the server's service account may create there (hostPath, host network, privileged pods). So the builder gets its own namespace, `<release namespace>-builder` by default (`builder.namespace`). The chart creates it with `pod-security.kubernetes.io/enforce: privileged`, and `helm uninstall` removes it with the store PVC (the store is a cache). The release namespace works with `baseline` (see [Kubernetes](kubernetes.md#pod-security)).

The chart puts the builder's Deployment, PVC, Service and NetworkPolicy into the builder namespace, writes the token Secret into both namespaces, and points the server at `http://<release>-builder.<builder namespace>:8330` (and `:8331`). The NetworkPolicy admits only server pods from the release namespace. With `builder.auth.existingSecret`, create that Secret in both namespaces.

The chart only ships the ingress side and adds no egress policy for the server. If the release namespace denies egress by default, or only allows it within the namespace, allow server pods egress to cluster DNS, the API server (it manages sandboxes through it) and the builder namespace on ports 8330 and 8331, on top of its outbound traffic to model providers and the domains it proxies for sandboxes. Without the builder rule, every sandbox start fails with `The skill builder is configured but unreachable`.

#### Egress on Kubernetes

The builder evaluates agent-authored flakes and fetches whatever their locks name, so its egress policy (`<release>-builder-egress`) lets it reach the internet but nothing that isn't globally routable: private ranges (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `fc00::/7`), carrier-grade NAT (`100.64.0.0/10`), loopback, link-local (`169.254.0.0/16`, `fe80::/10`, cloud metadata endpoints included), multicast and reserved ranges. That matches the sandbox proxy's [private-address rule](sandbox.md). DNS to `kube-dns` in `kube-system` stays allowed.

**A binary cache or other substituter in your own network is blocked by default.** List it in `builder.egress.allowedCidrs`, as must anything else private the builder needs: an upstream cache from `builder.upstreamCaches` on a LAN address, a Git server that skill flakes fetch from, or NodeLocal DNSCache (`169.254.20.10/32`):

```yaml
builder:
  egress:
    allowedCidrs:
      - 192.168.10.5/32  # the LAN's binary cache
```

Pod and service ranges outside these private ranges are not covered; most clusters use private ones. Whether `ipBlock` rules apply to traffic to other pods at all depends on the network plugin (Cilium never matches pods by `ipBlock`, so they stay unreachable either way).

When namespaces are managed elsewhere (GitOps), set `builder.createNamespace: false` and create the namespace with the label yourself:

```sh
kubectl create namespace carapace-builder
kubectl label namespace carapace-builder pod-security.kubernetes.io/enforce=privileged
```

Setting `builder.namespace` to the release namespace runs the builder next to the server; that namespace then needs `privileged`. To avoid the privileged namespace altogether, run the builder outside the cluster (`builder.enabled: false` + `externalUrl`, below).

### On a separate machine

Only the Carapace server talks to the builder: it sends sources, and sandboxes fetch from the builder's cache through the server's session proxy. A builder on a stronger machine outside the cluster is therefore just a URL and a token:

```sh
docker volume create carapace-builder-nix
docker run --rm -v carapace-builder-nix:/mnt/nix ghcr.io/thiesgerken/carapace-builder:<version> /bin/carapace-builder-init
docker run -d --name carapace-builder --restart unless-stopped -p 8330:8330 -p 8331:8331 \
  -e CARAPACE_BUILDER_TOKEN=<token> \
  --security-opt seccomp=unconfined --security-opt apparmor=unconfined --security-opt systempaths=unconfined \
  -v carapace-builder-nix:/nix ghcr.io/thiesgerken/carapace-builder:<version>
```

Rerun the init step after pulling a new image. Put TLS in front of ports 8330 and 8331 if the network between server and builder is not trusted. With the chart, switch the in-cluster builder off and point the server at it:

```yaml
builder:
  enabled: false
  externalUrl: https://builder.example.com
  externalCacheUrl: https://builder-cache.example.com
  auth:
    existingSecret: carapace-builder # key `token`
```

The builder's architecture must match the sandboxes'.
