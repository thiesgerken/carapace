# Carapace Helm Chart

Helm chart for deploying [Carapace](https://github.com/thiesgerken/carapace) on Kubernetes.

## Prerequisites

- Kubernetes 1.27+ with [Gateway API](https://gateway-api.sigs.k8s.io/) CRDs installed
- Helm 3
- A **ReadWriteMany** (RWX) StorageClass (e.g. CephFS, NFS)
- Container images pushed to a registry (GHCR by default)
- A CNI plugin that enforces **NetworkPolicy** (e.g. Calico, Cilium, k3s built-in)

> **⚠️ SECURITY WARNING — NetworkPolicy is critical**
>
> Carapace's security model relies on sandbox pods having **no direct internet access**. All outbound traffic is forced through the server's HTTP proxy, which enforces per-session domain allowlisting and the human-in-the-loop approval flow.
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
# Create the namespace and a secret with your API key and bearer token
kubectl create namespace carapace
kubectl create secret generic carapace-secrets -n carapace \
  --from-literal=ANTHROPIC_API_KEY=sk-ant-... \
  --from-literal=CARAPACE_TOKEN=my-secret-token

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

## Upgrade

```bash
helm upgrade carapace oci://ghcr.io/thiesgerken/charts/carapace -n carapace
```

## Uninstall

```bash
helm uninstall carapace -n carapace
```

> The PVC is **not** deleted on uninstall to protect your data. Remove it manually with `kubectl delete pvc carapace-data -n carapace` if desired.

## Configuration

All images default to the chart's `appVersion` tag, which is kept in sync with the project version by semantic-release.

### Required configuration

| What                   | How                                                                                                                            |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| **API bearer token**   | Set `CARAPACE_TOKEN` in the Secret referenced via `envFrom`. Both the server and CLI/frontend clients must use the same token. |
| **Anthropic API key**  | Set `ANTHROPIC_API_KEY` in the same Secret.                                                                                    |
| **Ingress hostname**   | `--set ingress.hostname=carapace.example.com`                                                                                  |
| **Gateway parent ref** | `--set ingress.parentRefs[0].name=my-gateway` (defaults to `default-gateway`)                                                  |

### Injecting secrets and environment variables

The chart does **not** create Secret resources — manage them externally and reference them:

```yaml
# values.yaml
envFrom:
  - secretRef:
      name: carapace-secrets # your externally managed Secret
  - configMapRef:
      name: carapace-config # optional ConfigMap for non-sensitive settings

extraEnv:
  - name: CARAPACE_LOG_LEVEL
    value: debug
```

### Application configuration

Inline your `config.yaml` under the `config` key — the chart creates a ConfigMap and mounts it at `/data/config.yaml`:

```yaml
# values.yaml
config:
  agent:
    model: anthropic:claude-sonnet-4-6
    sentinel_model: anthropic:claude-haiku-4-5
  channels:
    matrix:
      enabled: true
      homeserver: https://matrix.example.com
      user_id: "@carapace:example.com"
```

Leave `config` empty (`{}`) to skip the ConfigMap entirely and manage the file on the PVC instead.

### Bitwarden / Vaultwarden credential backend

To use a Bitwarden-compatible vault (including Vaultwarden) as a credential backend, the chart can inject one or more `bw serve` sidecar containers into the server Pod. Each sidecar shares the Pod's network namespace, so Carapace reaches it at `127.0.0.1:<port>`. Because `bw serve` only listens on localhost, no NetworkPolicy is needed to protect it — unlike a standalone deployment where the unauthenticated API would be reachable cluster-wide.

The sidecar image (`carapace-bitwarden-cli`) is built as part of the Carapace release and bundles the Bitwarden CLI. On startup it logs in, unlocks the vault, and starts `bw serve`. The liveness probe periodically calls `/sync` to keep the vault data fresh.

1. **Create a Secret** with the Bitwarden CLI credentials:

```bash
kubectl create secret generic carapace-bw-personal -n carapace \
  --from-literal=BW_CLIENTID=user.xxxxxxxx-... \
  --from-literal=BW_CLIENTSECRET=xxxxxxxxxxxx \
  --from-literal=BW_MASTER_PASSWORD=your-master-password \
  --from-literal=BW_EMAIL=you@example.com
```

Omit `BW_EMAIL` when using only API key login (`BW_CLIENTID` + `BW_CLIENTSECRET`).

Supported secret keys:

| Key                  | Required | Description                                                                |
| -------------------- | -------- | -------------------------------------------------------------------------- |
| `BW_MASTER_PASSWORD` | yes      | Master password for vault decryption                                       |
| `BW_EMAIL`           | no       | Account email; required when `BW_CLIENTID` / `BW_CLIENTSECRET` are unset   |
| `BW_CLIENTID`        | no       | API key client ID (generate in Bitwarden web UI → Account Settings → Keys) |
| `BW_CLIENTSECRET`    | no       | API key client secret                                                      |

When `BW_CLIENTID` and `BW_CLIENTSECRET` are provided, the sidecar uses API key login (required if 2FA is enabled). Otherwise it falls back to password login and requires `BW_EMAIL`. The master password is needed in both cases. As the project readme mentions, it is recommended to use a dedicated user for Carapace and share entries to it instead of using your account directly.

2. **Enable the sidecar** in your values:

```yaml
bitwarden:
  instances:
    - name: bw-personal
      port: 8087
      serverUrl: https://vault.example.com
      existingSecret: carapace-bw-personal
      resources:
        requests:
          cpu: 50m
          memory: 128Mi
        limits:
          memory: 256Mi
```

3. **Configure the matching credential backend** in your application config:

```yaml
config:
  credentials:
    backends:
      personal:
        type: bitwarden
        url: http://127.0.0.1:8087
```

The `url` defaults to `http://127.0.0.1:8087`, which works out of the box with the sidecar. Override it if `bw serve` runs elsewhere (e.g. a separate Service).

Multiple instances are supported — just add more entries with different names and ports (e.g. `personal` on 8087, `work` on 8088). Each instance gets its own sidecar container and its own Kubernetes Secret.

### Key values

| Value                          | Default                          | Description                                                       |
| ------------------------------ | -------------------------------- | ----------------------------------------------------------------- |
| `image.registry`               | `ghcr.io`                        | Server image registry                                             |
| `image.repository`             | `thiesgerken/carapace`           | Server image repository                                           |
| `image.tag`                    | `""` (appVersion)                | Server image tag                                                  |
| `frontend.enabled`             | `true`                           | Deploy the Next.js frontend                                       |
| `frontend.image.tag`           | `""` (appVersion)                | Frontend image tag                                                |
| `sandbox.image.tag`            | `""` (appVersion)                | Sandbox base image tag                                            |
| `ingress.enabled`              | `true`                           | Create a Gateway API HTTPRoute                                    |
| `ingress.hostname`             | `carapace.example.com`           | Ingress hostname                                                  |
| `ingress.parentRefs`           | `[{name: default-gateway}]`      | Gateway parent references                                         |
| `ingress.annotations`          | `{}`                             | Extra annotations on the HTTPRoute                                |
| `persistence.storageClassName` | `""` (cluster default)           | StorageClass for the RWX PVC                                      |
| `persistence.size`             | `10Gi`                           | PVC size                                                          |
| `persistence.finalizers`       | `[]`                             | PVC finalizers (e.g. `kubernetes.io/pvc-protection`)              |
| `config`                       | `{}`                             | Application config (mounted as `/data/config.yaml` via ConfigMap) |
| `priorityClassName`            | `""`                             | PriorityClass for all pods (server, frontend, sandbox)            |
| `envFrom`                      | `[]`                             | Secret/ConfigMap refs injected into the server                    |
| `extraEnv`                     | `[]`                             | Extra env vars for the server container                           |
| `resources`                    | requests: 200m/256Mi, limit: 1Gi | Server resource requests/limits                                   |
| `frontend.resources`           | requests: 50m/64Mi, limit: 128Mi | Frontend resource requests/limits                                 |
| `bitwarden.image.tag`          | `""` (appVersion)                | bw-serve sidecar image tag                                        |
| `bitwarden.instances`          | `[]`                             | List of `bw serve` sidecars (see above)                           |

See [values.yaml](values.yaml) for the complete reference.

## Development

```bash
# Lint the chart
helm lint charts/carapace

# Render templates locally (dry-run)
helm template carapace charts/carapace \
  --namespace carapace \
  --set 'envFrom[0].secretRef.name=carapace-secrets'
```
