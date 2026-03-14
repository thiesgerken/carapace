# Kubernetes Deployment

Carapace supports Kubernetes as a sandbox runtime. Instead of Docker containers, sandbox sessions run as Kubernetes pods that share a single RWX PersistentVolumeClaim for data.

## Prerequisites

- **Kubernetes cluster** — tested with k3s, works with any conformant cluster
- **RWX StorageClass** — CephFS, NFS, or another ReadWriteMany-capable provisioner. The server pod and all sandbox pods mount the same PVC.
- **Container images** pushed to a registry accessible by the cluster (GHCR by default)
- **kubectl** configured for your cluster

## Quick start

```bash
# 1. Create the secret with your API keys
kubectl create namespace carapace
kubectl create secret generic carapace-secrets -n carapace \
  --from-literal=ANTHROPIC_API_KEY=sk-...

# 2. Review and adjust manifests
#    - k8s/pvc.yaml: set storageClassName for your cluster
#    - k8s/ingress.yaml: set your hostname
#    - k8s/deployment-server.yaml: pin image tags

# 3. Apply
kubectl apply -k k8s/
```

## Architecture

```text
Namespace: carapace
├── Deployment/carapace (server + proxy)
│   └── mounts PVC at /data
│   └── creates sandbox pods via K8s API
├── Deployment/frontend
├── Service/carapace (ports 8321 + 3128)
├── Service/frontend (port 80)
├── PVC/carapace-data (RWX)
├── NetworkPolicy/sandbox-isolation
├── IngressRoute (Traefik)
└── RBAC (ServiceAccount + Role + RoleBinding)
```

The server pod manages sandbox pods directly via the Kubernetes API. Each session gets its own pod running `sleep infinity`, with commands executed via `kubectl exec`. Sandbox pods are owned by the server Deployment (via `ownerReferences`), so they:

- Appear as children in ArgoCD's resource tree
- Are garbage-collected when the Deployment is deleted
- Don't cause OutOfSync warnings

## Configuration

Set `sandbox.runtime` to `kubernetes` in your `data/config.yaml`:

```yaml
sandbox:
  runtime: kubernetes
  base_image: ghcr.io/thiesgerken/carapace-sandbox:latest
  k8s_namespace: carapace # namespace for sandbox pods
  k8s_pvc_claim: carapace-data # shared PVC claim name
  # k8s_service_account: null    # optional SA for sandbox pods
```

When `runtime` is `docker` (the default), nothing changes — the server uses the Docker socket as before.

### Auto-detection

When the server runs inside Kubernetes (the `KUBERNETES_SERVICE_HOST` env var is set), it loads in-cluster credentials automatically. No kubeconfig needed.

### Config reference

| Field                          | Default                      | Description                          |
| ------------------------------ | ---------------------------- | ------------------------------------ |
| `sandbox.runtime`              | `docker`                     | `docker` or `kubernetes`             |
| `sandbox.base_image`           | `carapace-sandbox:<version>` | Sandbox container image              |
| `sandbox.idle_timeout_minutes` | `15`                         | Idle sandbox cleanup interval        |
| `sandbox.proxy_port`           | `3128`                       | HTTP proxy port for domain filtering |
| `sandbox.k8s_namespace`        | `carapace`                   | Namespace for sandbox pods           |
| `sandbox.k8s_pvc_claim`        | `carapace-data`              | Shared PVC claim name                |
| `sandbox.k8s_service_account`  | `null`                       | ServiceAccount for sandbox pods      |

## Storage

A single RWX PVC (`carapace-data`) is shared between the server and all sandbox pods:

| Consumer    | Mount path             | subPath                           | Mode |
| ----------- | ---------------------- | --------------------------------- | ---- |
| Server      | `/data`                | (root)                            | RW   |
| Sandbox pod | `/workspace/AGENTS.md` | `AGENTS.md`                       | RO   |
| Sandbox pod | `/workspace/SOUL.md`   | `SOUL.md`                         | RO   |
| Sandbox pod | `/workspace/memory`    | `memory/`                         | RO   |
| Sandbox pod | `/workspace/skills`    | `sessions/{sid}/workspace/skills` | RW   |
| Sandbox pod | `/workspace/tmp`       | `sessions/{sid}/workspace/tmp`    | RW   |

The `KubernetesRuntime` automatically translates the `SandboxManager`'s host-path mounts into PVC subPath references — no configuration needed.

## Networking

### Proxy

Sandbox pods reach the internet exclusively through the HTTP proxy running inside the server pod (port 3128). The proxy enforces per-session domain allowlisting with token-based auth. Sandbox pods receive **only** `HTTP_PROXY` / `HTTPS_PROXY` env vars pointing to the Carapace service.

### NetworkPolicy

The included `networkpolicy.yaml` restricts sandbox pods:

- **Egress**: only to the server on port 3128 (proxy) + DNS
- **Ingress**: only from the server pod (for exec)

This mirrors the Docker setup where sandbox containers are on an internal network with no direct internet access.

## RBAC

The server needs a ServiceAccount with permissions to manage pods in its namespace:

```yaml
rules:
  - apiGroups: [""]
    resources: ["pods", "pods/exec"]
    verbs: ["create", "get", "list", "delete"]
  - apiGroups: ["apps"]
    resources: ["deployments"]
    verbs: ["get"] # for ownerReference lookup
```

## ArgoCD

Sandbox pods are created at runtime and don't exist in Git. They appear in ArgoCD's resource tree as children of the server Deployment (via `ownerReferences`):

```text
Application: carapace
├── Deployment/carapace              ✅ Synced
│   ├── ReplicaSet/carapace-xxx      ✅
│   │   └── Pod/carapace-xxx-abc     ✅ Running (server)
│   ├── Pod/carapace-session-aaa     ✅ Running (sandbox)
│   └── Pod/carapace-session-bbb     ✅ Running (sandbox)
├── Deployment/frontend              ✅ Synced
├── Service/carapace                 ✅
└── PVC/carapace-data                ✅
```

No special ArgoCD configuration is needed — the standard annotation-based tracking handles it.

## Manifests

All manifests live in `k8s/` and are wired together via `kustomization.yaml`:

| File                       | Purpose                                    |
| -------------------------- | ------------------------------------------ |
| `namespace.yaml`           | `carapace` namespace                       |
| `pvc.yaml`                 | Shared RWX PVC                             |
| `rbac.yaml`                | ServiceAccount + Role + RoleBinding        |
| `deployment-server.yaml`   | Server + proxy                             |
| `service-server.yaml`      | ClusterIP for API (8321) and proxy (3128)  |
| `deployment-frontend.yaml` | Next.js frontend                           |
| `service-frontend.yaml`    | ClusterIP for frontend (80)                |
| `ingress.yaml`             | Traefik IngressRoute                       |
| `networkpolicy.yaml`       | Sandbox pod isolation                      |
| `secret.yaml.example`      | Secret template (don't commit real values) |

## Customization

- **StorageClass**: edit `pvc.yaml` to match your cluster's RWX provisioner
- **Ingress**: the included `ingress.yaml` uses Traefik `IngressRoute` (k3s default). Replace with a standard `Ingress` resource if using a different controller.
- **Image tags**: pin to specific versions in the Deployment manifests rather than using `:latest`
- **Resources**: add resource requests/limits to the Deployment specs for production use
