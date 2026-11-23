# Skill builder

Skills with commands are Nix flakes (see [#548](https://github.com/thiesgerken/carapace/issues/548)). The builder is the service that evaluates and builds them, one per installation, shared by all users. The Carapace server sends it a skill directory and gets back store paths and the skill's command metadata. Sandboxes never build pushed skills themselves. The builder never sees a knowledge repo.

## API

The build API listens on port 8330. Every route except `/healthz` requires `Authorization: Bearer <CARAPACE_BUILDER_TOKEN>`.

| Route | |
| --- | --- |
| `GET /healthz` | Liveness, unauthenticated |
| `GET /info` | `{"system": "x86_64-linux"}`, the Nix system the builder builds for |
| `GET /builds/{tree}` | The stored result for a skill tree, or 404 |
| `PUT /builds/{tree}` | Body: the skill directory as a tar archive (gzip or plain), e.g. `git archive <tree>`. Builds, stores and returns the result |

`{tree}` is the Git tree hash of the skill directory (SHA-1 or SHA-256). It is the cache key: a tree that has a result, succeeded or failed, is answered from it without building, and its archive is not even read. The key is the caller's claim: the builder does not recompute it from the archive. The server is trusted to send `git archive <tree>` for `<tree>`, and keeping that invariant is the caller's job. A wrong key sticks until the tree is retried or collected.

`PUT` blocks until the build ends, which takes seconds for a small change and a few minutes for a cold uv skill. Requests for the same tree wait for each other; different trees build in parallel. Callers must not hold up a push or a session on it.

A result:

```json
{
  "tree": "4b825dc642cb6eb9a060e54bf8d69288fbee4904",
  "state": "succeeded",
  "store_paths": ["/nix/store/…-skill-web"],
  "metadata": {"commands": {"…": "…"}},
  "log_tail": "…"
}
```

`state` is `succeeded` or `failed`. A failed result has no store paths, and `log_tail` holds the end of the evaluation and build output (16k characters) that says why. Failed results are stored like successful ones.

### What the builder builds

For a skill directory with `flake.nix` and `flake.lock`, on system `<system>`:

- **Outputs:** `nix build --no-update-lock-file path:<dir>#packages.<system>.default`. `store_paths` lists every output of that package. `mkSkill` puts only the command wrappers into it.
- **Metadata:** `nix eval --json --no-update-lock-file path:<dir>#packages.<system>.default --apply 'p: p.passthru.carapace or null'`. The builder passes this JSON through without reading it. `mkSkill` defines its schema (command names, descriptions, declarations), and the server reads it. It is `null` when the package has no `passthru.carapace`.
- **Locks:** a missing `flake.lock` is a failed build, and so is one that lacks an input (`--no-update-lock-file`). The builder never writes lock files.
- **Evaluation:** import-from-derivation is off, and a flake's `nixConfig` is ignored.

### Architecture

Builder and sandboxes must share one architecture. The builder reports its system at `/info` and builds only for it. The server compares it with its own CPU architecture (sandboxes are Linux on the server's architecture): at start when the builder answers, otherwise before its first request. A mismatch stops the server. An unreachable builder at start only logs a warning, since the builder may come up after the server.

## Inside the image

`carapace-builder` runs two processes. If either stops, the container stops.

- `nix-daemon` as root owns the store and runs builds as `nixbld*` users with `sandbox = true`, `sandbox-fallback = false` and `max-jobs = auto`. Only root is a trusted user.
- The API as the unprivileged user `carapace-builder` (UID 999). It runs every `nix build` and `nix eval` as a short-lived subprocess, and evaluation happens in that subprocess. So evaluation runs without privileges and without any signing key, and the daemon ignores the settings an untrusted client asks for (`sandbox = false`, for example). It does run as the API's user, so an evaluator escape could read the token and rewrite stored results (see [security](security.md#skill-builder)). Running evaluations as a separate user, which needs the API to switch users per subprocess, is the upgrade path.

At start, before it listens, the API builds a fresh probe derivation that fails if it can see the store database, which is only visible outside the build sandbox. If the sandbox cannot be set up or is not in effect, the builder exits with the reason in its log.

The store lives on a volume that replaces `/nix`, so it survives restarts and image updates. Built skills and the dependencies they downloaded stay warm. `carapace-builder-init` runs before every start, with the volume at `/mnt/nix`. It copies the image's own store paths into the volume and roots them, so after an update the volume holds the new image's tools, and the old ones become garbage. Results and GC roots for built trees are under `/nix/var/carapace-builder` on the same volume. Garbage collection comes with [#566](https://github.com/thiesgerken/carapace/issues/566); until then the volume only grows.

## Running it

The server finds the builder through `CARAPACE_BUILDER_URL` and `CARAPACE_BUILDER_TOKEN`. Without a URL there is no builder, and skills with commands are not built. The server logs a warning at start. `CARAPACE_BUILDER_TIMEOUT_SECONDS` (default 1800) bounds one request.

### Docker Compose

`docker-compose.yml` runs `builder-init` and `builder` with a named volume `builder-nix`, and points the server at `http://builder:8330`. Set `CARAPACE_BUILDER_TOKEN` in `.env`. The builder is on the default network only, so sandboxes, which sit on the internal `carapace-sandbox` network, cannot reach it.

The Nix build sandbox needs `security_opt: [seccomp=unconfined, apparmor=unconfined, systempaths=unconfined]`: unshare must be allowed and `/proc` unmasked so that Nix can mount its own. Without all three the builder refuses to start. Plain Docker has no per-container user namespace, so root in the builder is root on the host, with the default capabilities. That is weaker than the Kubernetes setup (see [security](security.md#skill-builder)).

### Kubernetes

The chart deploys the builder by default (`builder.enabled`). That covers a Deployment with an init container, a PVC (`builder.persistence.size`, default 20Gi), a Service, a NetworkPolicy that admits only the server on port 8330, and a generated token Secret. The pod runs with `hostUsers: false` (root in the pod is an unprivileged host user), `procMount: Unmasked`, and `Unconfined` seccomp and AppArmor profiles. It gets no added capabilities.

The cluster has to support user namespaces for pods. That means a recent kernel and container runtime, plus the `UserNamespacesSupport` and `ProcMountType` features. The settings were verified on k3s 1.37 with containerd 2.3 and kernel 7.3. If the builder logs that the Nix build sandbox is not effective, the node or its runtime lacks one of these. Pod Security Admission levels `restricted` and `baseline` reject the pod (unconfined seccomp, unmasked `/proc`), so the builder needs `privileged`. `hostUsers: false` keeps that from meaning root on the node. A Pod Security label covers every pod in its namespace. Sandboxes run in the release namespace and set only `allowPrivilegeEscalation: false` and dropped capabilities, so labelling that namespace `privileged` lifts admission limits on everything the server's service account may create there: hostPath, host network and privileged pods would all be admitted. The pods the server writes don't change, so this costs a layer of defence, not an open door. The alternatives: give the builder its own namespace (below; the release namespace stays at `baseline`), run it outside the cluster (`builder.enabled: false` + `externalUrl`), or accept the trade-off. A separate namespace:

```sh
kubectl create namespace carapace-builder
kubectl label namespace carapace-builder pod-security.kubernetes.io/enforce=privileged
helm upgrade … --set builder.namespace=carapace-builder
```

The chart then puts the builder's Deployment, PVC, Service and NetworkPolicy there, writes the token Secret into both namespaces, and points the server at `http://<release>-builder.carapace-builder:8330`. With `builder.auth.existingSecret`, create that Secret in both namespaces.

### On a separate machine

Only the Carapace server talks to the builder: it sends sources, and from [#565](https://github.com/thiesgerken/carapace/issues/565) on sandboxes fetch from the builder's cache through the server's session proxy. A builder on a stronger machine outside the cluster is therefore just a URL and a token:

```sh
docker volume create carapace-builder-nix
docker run --rm -v carapace-builder-nix:/mnt/nix ghcr.io/thiesgerken/carapace-builder:<version> /bin/carapace-builder-init
docker run -d --name carapace-builder --restart unless-stopped -p 8330:8330 \
  -e CARAPACE_BUILDER_TOKEN=<token> \
  --security-opt seccomp=unconfined --security-opt apparmor=unconfined --security-opt systempaths=unconfined \
  -v carapace-builder-nix:/nix ghcr.io/thiesgerken/carapace-builder:<version>
```

Rerun the init step after pulling a new image. Put TLS in front of port 8330 if the network between server and builder is not trusted. With the chart, switch the in-cluster builder off and point the server at it:

```yaml
builder:
  enabled: false
  externalUrl: https://builder.example.com
  auth:
    existingSecret: carapace-builder # key `token`
```

The builder's architecture must match the sandboxes'.
