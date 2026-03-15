# Carapace Helm Chart

Helm chart for deploying [Carapace](https://github.com/thiesgerken/carapace) on Kubernetes.

## Prerequisites

- Kubernetes 1.27+
- Helm 3
- A **ReadWriteMany** (RWX) StorageClass (e.g. CephFS, NFS)
- Container images pushed to a registry (GHCR by default)

## Install

```bash
# Create the namespace and an API-key secret
kubectl create namespace carapace
kubectl create secret generic carapace-secrets -n carapace \
  --from-literal=ANTHROPIC_API_KEY=sk-ant-...

# Install the chart
helm install carapace ./charts/carapace \
  --namespace carapace \
  --set ingress.hostname=carapace.example.com \
  --set 'envFrom[0].secretRef.name=carapace-secrets'
```

## Upgrade

```bash
helm upgrade carapace ./charts/carapace -n carapace
```

## Uninstall

```bash
helm uninstall carapace -n carapace
```

> The PVC is **not** deleted on uninstall to protect your data. Remove it manually with `kubectl delete pvc carapace-data -n carapace` if desired.

## Configuration

All images default to the chart's `appVersion` tag, which is kept in sync with the project version by semantic-release.

### Required configuration

| What | How |
|------|-----|
| **Anthropic API key** | Create a Secret containing `ANTHROPIC_API_KEY` and reference it via `envFrom` (see above). Works with any secret management solution (kubectl, ExternalSecrets, SealedSecrets, …). |
| **Ingress hostname** | `--set ingress.hostname=carapace.example.com` |

### Injecting secrets and environment variables

The chart does **not** create Secret resources — manage them externally and reference them:

```yaml
# values.yaml
envFrom:
  - secretRef:
      name: carapace-secrets       # your externally managed Secret
  - configMapRef:
      name: carapace-config        # optional ConfigMap for non-sensitive settings

extraEnv:
  - name: CARAPACE_LOG_LEVEL
    value: debug
```

### Key values

| Value | Default | Description |
|-------|---------|-------------|
| `image.registry` | `ghcr.io` | Server image registry |
| `image.repository` | `thiesgerken/carapace` | Server image repository |
| `image.tag` | `""` (appVersion) | Server image tag |
| `frontend.enabled` | `true` | Deploy the Next.js frontend |
| `frontend.image.tag` | `""` (appVersion) | Frontend image tag |
| `sandbox.image.tag` | `""` (appVersion) | Sandbox base image tag |
| `ingress.enabled` | `true` | Create a Traefik IngressRoute |
| `ingress.hostname` | `carapace.example.com` | Ingress hostname |
| `ingress.tls.certResolver` | `letsencrypt` | Traefik cert resolver |
| `persistence.storageClassName` | `""` (cluster default) | StorageClass for the RWX PVC |
| `persistence.size` | `10Gi` | PVC size |
| `priorityClassName` | `""` | PriorityClass for all pods (server, frontend, sandbox) |
| `envFrom` | `[]` | Secret/ConfigMap refs injected into the server |
| `extraEnv` | `[]` | Extra env vars for the server container |
| `resources` | `{}` | Server resource requests/limits |
| `frontend.resources` | `{}` | Frontend resource requests/limits |

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
