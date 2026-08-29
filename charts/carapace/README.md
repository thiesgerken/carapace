# carapace Helm Chart

Helm chart for deploying [carapace](https://github.com/thiesgerken/carapace) on Kubernetes.

## Prerequisites

- Kubernetes 1.27+ with [Gateway API](https://gateway-api.sigs.k8s.io/) CRDs installed
- Helm 3
- A **ReadWriteOnce** (RWO) StorageClass. The server gets its own data PVC and each sandbox session gets its own PVC.
- Container images pushed to a registry (GHCR by default)
- A CNI plugin that enforces **NetworkPolicy** (e.g. Calico, Cilium, k3s built-in)

> **⚠️ SECURITY WARNING — NetworkPolicy is critical**
>
> carapace's security model relies on sandbox pods having **no direct internet access**. All outbound traffic is forced through the server's HTTP proxy, which enforces per-session domain allowlisting and the human-in-the-loop approval flow.
>
> The chart installs a `NetworkPolicy` that restricts sandbox pod egress to the proxy port (3128), the sandbox API port (8322), and DNS only. **If you add broader egress rules to the namespace, or your CNI does not enforce NetworkPolicy, sandbox pods can bypass the proxy entirely — defeating the approval system and all domain-level security controls.**
>
> Before deploying, verify that:
>
> 1. Your CNI plugin enforces NetworkPolicy. k3s and distributions using Calico or Cilium support this out of the box. Standalone Flannel does **not** — it silently ignores NetworkPolicy.
> 2. No other NetworkPolicy in the namespace grants sandbox pods wider egress (Kubernetes NetworkPolicy is additive — a permissive policy cannot be overridden by a restrictive one).
> 3. No namespace-level network rules (e.g. Cilium `CiliumNetworkPolicy`, Calico `GlobalNetworkPolicy`) override the chart's restrictions.

## Install

The chart is published to GHCR as an OCI artifact on every release:

```bash
# Create the namespace and a secret with your API key and bootstrap admin password
kubectl create namespace carapace
kubectl create secret generic carapace-secrets -n carapace \
  --from-literal=ANTHROPIC_API_KEY=sk-ant-... \
  --from-literal=CARAPACE_TOKEN=my-bootstrap-admin-password

# Install from OCI registry
helm install carapace oci://ghcr.io/thiesgerken/charts/carapace \
  --namespace carapace \
  --set ingress.hostname=carapace.example.com \
  --set 'envFrom[0].secretRef.name=carapace-secrets'

# Or install from a local checkout
helm install carapace ./charts/carapace \
  --namespace carapace \
  --set ingress.hostname=carapace.example.com \
  --set 'envFrom[0].secretRef.name=carapace-secrets'
```

For Kustomize-based GitOps:

```yaml
# kustomization.yaml
helmCharts:
  - name: carapace
    repo: oci://ghcr.io/thiesgerken/charts
    version: 0.25.3 # pin to a specific version
    releaseName: carapace
    namespace: carapace
    valuesFile: values.yaml
```

Pull request builds also publish preview images tagged as `pr<PR number>` and a matching OCI chart package. The preview chart uses `appVersion=pr<PR number>`, so the default image tags resolve to the PR images automatically.

Example for PR 99 when the base chart version is `0.28.0`:

```bash
helm install carapace oci://ghcr.io/thiesgerken/charts/carapace \
  --namespace carapace \
  --version 0.28.0-pr.99 \
  --set ingress.hostname=carapace.example.com \
  --set 'envFrom[0].secretRef.name=carapace-secrets'
```

The chart version stays tied to the chart's current base version. If `Chart.yaml` moves to `0.29.0`, the preview for PR 99 becomes `0.29.0-pr.99`.

## Upgrade

```bash
helm upgrade carapace oci://ghcr.io/thiesgerken/charts/carapace -n carapace
```

## Uninstall

```bash
helm uninstall carapace -n carapace
```

> PVCs are **not** deleted on uninstall to protect your data. Remove them manually with `kubectl delete pvc carapace-data -n carapace` if desired.

## Database

carapace stores users, sessions, jobs, auth sessions, sandbox tokens, and notification
subscriptions in a SQL database. Schema migrations run automatically on server startup.
Three options:

- **Bundled PostgreSQL (default).** `postgres.enabled=true` deploys a single in-cluster
  Postgres (its own `<release>-postgres` PVC, Recreate strategy) and wires the server to
  it. With plain Helm the password is auto-generated into the `<release>-postgres` Secret
  and reused across upgrades via a `lookup`.

  > **GitOps (Argo CD / Flux): use `postgres.auth.existingSecret`.** The auto-generate
  > path relies on Helm `lookup`, which returns nothing when manifests are rendered with
  > `helm template`. Argo CD/Flux then regenerate a fresh random password on every sync,
  > but Postgres only applies the password at initdb — so the running DB keeps the old one
  > and the server crashes with `password authentication failed for user "carapace"`.
  > Point `postgres.auth.existingSecret` at a Secret you manage (SealedSecret, External
  > Secrets, …) containing `postgres-password` and `database-url`
  > (`postgresql+psycopg://carapace@<release>-postgres:5432/carapace`, password omitted).
  > Alternatively set an explicit `postgres.auth.password`.
- **External database.** Set `postgres.enabled=false` and `database.url` to a SQLAlchemy
  URL, e.g. `postgresql+psycopg://user:pass@my-pg:5432/carapace`.
- **SQLite on the data PVC.** Set `postgres.enabled=false` and leave `database.url` empty.
  The DB is a file (`carapace.db`) on the existing data PVC — fine for the single-replica
  server, no extra infra.

## Configuration

All images default to the chart's `appVersion` tag. Release charts use the semantic-release project version, and PR preview charts use `pr<PR number>`.

### Required configuration

| What                   | How                                                                                                                                                                    |
| ---------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Bootstrap password** | Set `CARAPACE_TOKEN` in the Secret referenced via `envFrom`. It is only used as the initial password for the bootstrap `admin` user when no enabled admin user exists. |
| **LLM API key**        | Set `ANTHROPIC_API_KEY`, `OPENROUTER_API_KEY`, or another configured provider key in the same Secret. Not needed at startup: the server boots without one so an admin can configure the model catalog first. |
| **Ingress hostname**   | `--set ingress.hostname=carapace.example.com`                                                                                                                          |
| **Gateway parent ref** | `--set ingress.parentRefs[0].name=my-gateway` (defaults to `default-gateway`)                                                                                          |

### Injecting secrets and environment variables

The chart does **not** create Secret resources — manage them externally and reference them:

```yaml
# values.yaml
envFrom:
  - secretRef:
      name: carapace-secrets # your externally managed Secret
  - configMapRef:
      name: carapace-env # optional ConfigMap for non-sensitive environment variables

extraEnv:
  - name: SOME_OTHER_VAR
    value: foo
```

Set the server log level via `logLevel` (default `info`; `debug`, `warning`, `error`).

`sandbox.warmPoolSize` (default `1`) keeps that many generic warm sandboxes ready for faster claims; set it to `0` to disable.

`sandbox.skillActivator` configures the absolute activator path inside sandbox images. It defaults to the executable shipped by the official image. Set it to an empty string for no-op skill activation when using an image without an activator.

### Application configuration

The chart no longer accepts application `config.yaml` through Helm values and does not render a ConfigMap for it. Platform and user settings are managed from the web UI after install:

- **Settings** -> **Admin** -> **Platform** for model catalog, default models, OpenAI-compatible base URLs, OpenRouter API keys, reasoning options, and default budgets.
- **Settings** -> **Admin** -> **Users** for local users, roles, passwords, and assignment of existing data.
- **Settings** -> **Account** for per-user model defaults, Matrix, Git, and credential backends.
- **Settings** -> **Jobs** for saved jobs and schedules.

The model catalog and the scalar `agent`/`sessions` settings edited in **Platform** are stored in the database (`models` + `platform_settings` tables). A fresh database starts **empty**; until an admin configures the catalog the server runs on the built-in default models. The admin UI is the source of truth.

There is no `config.yaml`. The server reads its data root from `CARAPACE_DATA_DIR`
(the chart sets `/var/lib/carapace`, the data PVC) and all other operator/bootstrap settings
from env vars: `CARAPACE_DATABASE_URL`, `CARAPACE_LOG_LEVEL`, `CARAPACE_SERVER_*`,
`CARAPACE_AUTH_*` (e.g. `CARAPACE_AUTH_COOKIE__SECURE=true`), `CARAPACE_NOTIFICATIONS_*`,
`CARAPACE_SANDBOX_*`. Set them through `envFrom`/`extraEnv`.

The chart deploys Redis by default and wires the server to `<release>-redis` via `CARAPACE_CACHE_REDIS_URL`. If you disable the bundled Redis, provide an external URL with `extraEnv` or `envFrom`:

```yaml
extraEnv:
  - name: CARAPACE_CACHE_REDIS_URL
    value: redis://redis.example.internal:6379/0
```

Historical chart versions accepted application config under a Helm `config` value and mounted it from a ConfigMap at `/var/lib/carapace/config.yaml`. Current chart versions do not render or mount that ConfigMap and the server no longer reads a config file at all; configure operator settings via env vars and platform settings via the web UI. Do not keep a `config:` block in Helm values; it is ignored.

### Bitwarden / Vaultwarden credential backend

To use a Bitwarden-compatible vault (including Vaultwarden) as a credential backend, the chart can deploy one or more standalone Bitwarden CLI companion Pods behind nginx Basic Auth proxies. Each instance gets its own Service, Secret, and optional PVC, which makes it a good fit for per-user credential backend URLs. The chart also creates a NetworkPolicy that only allows ingress from the carapace server Pod.

The Bitwarden CLI image (`carapace-bitwarden-cli`) is built as part of the carapace release and bundles the Bitwarden CLI. On startup it logs in, unlocks the vault, and starts `bw serve`. The liveness probe periodically calls `/sync` to keep the vault data fresh.

1. **Create a Secret** with Bitwarden CLI credentials. The chart mounts it read-only at `/run/secrets/bitwarden`; the Bitwarden CLI entrypoint reads keys from files when the matching env vars are unset (see [`bitwarden-cli/README.md`](../../bitwarden-cli/README.md)).

```bash
kubectl create secret generic carapace-bw-personal -n carapace \
  --from-literal=BW_CLIENTID=user.xxxxxxxx-... \
  --from-literal=BW_CLIENTSECRET=xxxxxxxxxxxx \
  --from-literal=BW_MASTER_PASSWORD=your-master-password \
  --from-literal=BW_EMAIL=you@example.com
```

Omit `BW_EMAIL` when using only API key login (`BW_CLIENTID` + `BW_CLIENTSECRET`). Omit `BW_CLIENTID` and `BW_CLIENTSECRET` when using password-only login (then `BW_EMAIL` is required).

Supported **Secret** keys (each becomes a file name under the mount):

| Key                  | Required | Description                                                                |
| -------------------- | -------- | -------------------------------------------------------------------------- |
| `BW_MASTER_PASSWORD` | yes      | Master password for vault decryption                                       |
| `BW_EMAIL`           | no       | Account email; required for password-only login (omit for API key login)   |
| `BW_CLIENTID`        | no       | API key client ID (generate in Bitwarden web UI → Account Settings → Keys) |
| `BW_CLIENTSECRET`    | no       | API key client secret                                                      |

When both `BW_CLIENTID` and `BW_CLIENTSECRET` are present, the Bitwarden CLI uses API key login (required if 2FA is enabled). Otherwise it uses password login and needs `BW_EMAIL` in the Secret. The master password is needed in both cases. As the project readme mentions, it is recommended to use a dedicated user for carapace and share entries to it instead of using your account directly.

2. **Create a Basic Auth Secret** for nginx. It must contain an htpasswd file named `htpasswd` unless you override `basicAuth.secretKey`.

```bash
htpasswd -nB carapace > /tmp/carapace-bitwarden-htpasswd
kubectl create secret generic carapace-bitwarden-basic-auth -n carapace \
  --from-file=htpasswd=/tmp/carapace-bitwarden-htpasswd
```

3. **Enable a Bitwarden instance** in your values:

```yaml
bitwarden:
  instances:
    - name: personal
      fullnameOverride: carapace-bitwarden
      serverUrl: https://vault.example.com
      existingSecret: carapace-bw-personal
      basicAuth:
        existingSecret: carapace-bitwarden-basic-auth
      resources:
        requests:
          cpu: 50m
          memory: 128Mi
        limits:
          memory: 256Mi
```

4. **Configure the matching credential backend** in **Settings** -> **Account** -> **Credentials**. The equivalent backing user config is:

```yaml
credentials:
  backends:
    personal:
      type: bitwarden
      url: http://carapace-bitwarden
      basic_auth:
        username: carapace
        password: change-me
```

Multiple instances are supported — just add more entries with different names and ports. Each instance gets its own companion Pod, Kubernetes Secret, Service, Basic Auth proxy, and (when persistence is enabled) PVC mounted at `/var/lib/bitwarden-cli` so Bitwarden CLI device/session data survives Pod reschedules — reducing repeated logins and “new device” emails from the vault provider. Set `bitwarden.persistence.enabled` to `false` if you prefer ephemeral Bitwarden CLI data.

The Bitwarden CLI binds to a fixed localhost-only internal port (`8088`) inside its Pod, while nginx exposes the configured service port for carapace. The service port defaults to `80` and must not be `8088`.

### Key values

| Value                                                  | Default                          | Description                                                         |
| ------------------------------------------------------ | -------------------------------- | ------------------------------------------------------------------- |
| `image.registry`                                       | `ghcr.io`                        | Server image registry                                               |
| `image.repository`                                     | `thiesgerken/carapace`           | Server image repository                                             |
| `image.tag`                                            | `""` (appVersion)                | Server image tag                                                    |
| `frontend.enabled`                                     | `true`                           | Deploy the Next.js frontend                                         |
| `frontend.image.tag`                                   | `""` (appVersion)                | Frontend image tag                                                  |
| `server.probes.startup.initialDelaySeconds`            | `15`                             | Delay before the server startup probe runs                          |
| `server.probes`                                        | see `values.yaml`                | Server startup, liveness, and readiness probe timing                |
| `sandbox.image.tag`                                    | `""` (appVersion)                | Sandbox base image tag                                              |
| `sandbox.sandboxesName`                                | `null` (`<release>-sandboxes`)   | `Sandboxes` CR name; set `""` to use the Deployment as owner        |
| `ingress.enabled`                                      | `true`                           | Create a Gateway API HTTPRoute                                      |
| `ingress.hostname`                                     | `carapace.example.com`           | Ingress hostname                                                    |
| `ingress.parentRefs`                                   | `[{name: default-gateway}]`      | Gateway parent references                                           |
| `ingress.annotations`                                  | `{}`                             | Extra annotations on the HTTPRoute                                  |
| `persistence.data.storageClassName`                    | `""` (cluster default)           | StorageClass for the data PVC                                       |
| `persistence.data.size`                                | `10Gi`                           | Data PVC size                                                       |
| `persistence.data.finalizers`                          | `[]`                             | Data PVC finalizers (e.g. `kubernetes.io/pvc-protection`)           |
| `priorityClassName`                                    | `""`                             | PriorityClass for all pods (server, frontend, sandbox)              |
| `envFrom`                                              | `[]`                             | Secret/ConfigMap refs injected into the server                      |
| `extraEnv`                                             | `[]`                             | Extra env vars for the server container                             |
| `redis.enabled`                                        | `true`                           | Deploy the bundled Redis required for session-list cache            |
| `redis.image.tag`                                      | `8-alpine`                       | Redis image tag                                                     |
| `redis.resources`                                      | requests: 25m/64Mi, limit: 128Mi | Redis resource requests/limits                                      |
| `postgres.enabled`                                     | `true`                           | Deploy the bundled in-cluster PostgreSQL                            |
| `postgres.auth.password`                               | `""` (auto-generated)            | DB password; empty auto-generates into the `<release>-postgres` Secret (Helm `lookup`, **not** GitOps-safe) |
| `postgres.auth.existingSecret`                         | `""`                             | Externally managed Secret (needs `passwordKey` + `urlKey`); **recommended for GitOps** |
| `postgres.persistence.size`                            | `8Gi`                            | Postgres data PVC size                                              |
| `database.url`                                         | `""`                             | External SQLAlchemy URL (used only when `postgres.enabled=false`)   |
| `resources`                                            | requests: 200m/256Mi, limit: 1Gi | Server resource requests/limits                                     |
| `frontend.resources`                                   | requests: 50m/64Mi, limit: 128Mi | Frontend resource requests/limits                                   |
| `bitwarden.image.tag`                                  | `""` (appVersion)                | bitwarden-cli image tag                                             |
| `bitwarden.nginx.image.tag`                            | pinned nginx digest              | nginx image tag/digest for standalone Basic Auth proxy              |
| `bitwarden.probes.bwServe.startup.initialDelaySeconds` | `30`                             | Delay before the `bw serve` startup probe runs                      |
| `bitwarden.probes.nginx.readiness.initialDelaySeconds` | `15`                             | Delay before the nginx readiness probe runs                         |
| `bitwarden.probes`                                     | see `values.yaml`                | Bitwarden `bw serve` and nginx probe timing                         |
| `bitwarden.persistence.enabled`                        | `true`                           | Create a PVC per instance for CLI data (`BITWARDENCLI_APPDATA_DIR`) |
| `bitwarden.persistence.size`                           | `256Mi`                          | Size of each Bitwarden instance PVC                                 |
| `bitwarden.persistence.storageClassName`               | `""` (cluster default)           | StorageClass for Bitwarden PVCs                                     |
| `bitwarden.persistence.finalizers`                     | `[]`                             | Finalizers for Bitwarden PVCs                                       |
| `bitwarden.instances`                                  | `[]`                             | List of standalone `bw serve` proxy instances (see above)           |

See [values.yaml](values.yaml) for the complete reference.

The `Sandboxes` CR is currently used only as an ownership/metadata anchor. The chart installs the CRD and a singleton resource, but no operator/controller is deployed yet; runtime sandbox lifecycle is still managed directly by the carapace server.

## Development

```bash
# Lint the chart
helm lint charts/carapace

# Render templates locally (dry-run)
helm template carapace charts/carapace \
  --namespace carapace \
  --set 'envFrom[0].secretRef.name=carapace-secrets'
```
