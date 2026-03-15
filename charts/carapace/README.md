# Carapace Helm Chart

Helm chart for deploying [Carapace](https://github.com/thiesgerken/carapace) on Kubernetes.

## Prerequisites

- Kubernetes 1.27+ with [Gateway API](https://gateway-api.sigs.k8s.io/) CRDs installed
- Helm 3
- A **ReadWriteMany** (RWX) StorageClass (e.g. CephFS, NFS)
- Container images pushed to a registry (GHCR by default)

## Install

The chart is published to GHCR as an OCI artifact on every release:

```bash
# Create the namespace and an API-key secret
kubectl create namespace carapace
kubectl create secret generic carapace-secrets -n carapace \
  --from-literal=ANTHROPIC_API_KEY=sk-ant-...

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
    version: 0.25.3  # pin to a specific version
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

| What | How |
|------|-----|
| **Anthropic API key** | Create a Secret containing `ANTHROPIC_API_KEY` and reference it via `envFrom` (see above). Works with any secret management solution (kubectl, ExternalSecrets, SealedSecrets, …). |
| **Ingress hostname** | `--set ingress.hostname=carapace.example.com` |
| **Gateway parent ref** | `--set ingress.parentRefs[0].name=my-gateway` (defaults to `default-gateway`) |

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
| `ingress.enabled` | `true` | Create a Gateway API HTTPRoute |
| `ingress.hostname` | `carapace.example.com` | Ingress hostname |
| `ingress.parentRefs` | `[{name: default-gateway}]` | Gateway parent references |
| `ingress.annotations` | `{}` | Extra annotations on the HTTPRoute |
| `persistence.storageClassName` | `""` (cluster default) | StorageClass for the RWX PVC |
| `persistence.size` | `10Gi` | PVC size |
| `persistence.finalizers` | `[]` | PVC finalizers (e.g. `kubernetes.io/pvc-protection`) |
| `priorityClassName` | `""` | PriorityClass for all pods (server, frontend, sandbox) |
| `envFrom` | `[]` | Secret/ConfigMap refs injected into the server |
| `extraEnv` | `[]` | Extra env vars for the server container |
| `resources` | requests: 200m/256Mi, limit: 1Gi | Server resource requests/limits |
| `frontend.resources` | requests: 50m/64Mi, limit: 128Mi | Frontend resource requests/limits |

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
