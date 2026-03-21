# Sandbox Architecture

All agent tool invocations — script execution, shell commands, file operations — run inside a sandboxed container. Carapace itself (the server) runs on the host (or in its own container/pod), but every agent action runs inside an isolated container.

## Execution model

Each session gets a single sandbox container. The container provides the agent with a workspace where it can read files, run commands, and interact with skills.

```mermaid
flowchart LR
    subgraph carapace [Carapace Server]
        Agent[Agent Tools]
        Proxy[HTTP Forward Proxy]
    end

    subgraph container ["Session Container (Alpine + Python + uv)"]
        Workspace["/workspace/"]
        Skills["/workspace/skills/"]
        Memory["/workspace/memory/ (read-only)"]
        Tmp["/workspace/tmp/"]
    end

    subgraph external [Internet]
        APIs[Web / APIs]
    end

    Agent <-->|exec, file ops| container
    container -->|outbound traffic via HTTP_PROXY| Proxy
    Proxy -->|allowed domains only| APIs
```

### Container capabilities

- **Shell access**: The agent runs commands via `exec` (equivalent to `docker exec` / `kubectl exec`)
- **File operations**: `read`, `write`, `edit`, `apply_patch` work directly on the container filesystem
- **Network access**: All outbound traffic goes through the HTTP forward proxy, which enforces per-session domain allowlisting
- **Skills**: Activated skills are copied into the container with their venvs built via `uv sync`
- **Workspace files**: `AGENTS.md`, `SOUL.md`, `USER.md`, and `SECURITY.md` are working copies the agent can edit. Changes are made permanent via `save_workspace_file`.

## Mounts

When a session container is created, the following mounts are configured:

| Host source | Container path | Mode | Purpose |
| --- | --- | --- | --- |
| `sessions/{sid}/workspace/AGENTS.md` | `/workspace/AGENTS.md` | read-write | Working copy of behavioral guide |
| `sessions/{sid}/workspace/SOUL.md` | `/workspace/SOUL.md` | read-write | Working copy of personality |
| `sessions/{sid}/workspace/USER.md` | `/workspace/USER.md` | read-write | Working copy of user context |
| `sessions/{sid}/workspace/SECURITY.md` | `/workspace/SECURITY.md` | read-write | Working copy of security policy |
| `memory/` | `/workspace/memory/` | **read-only** | Memory files (agent uses `write_memory` tool instead) |
| `sessions/{sid}/workspace/skills/` | `/workspace/skills/` | read-write | Activated skills |
| `sessions/{sid}/workspace/tmp/` | `/workspace/tmp/` | read-write | Scratch space |

Workspace files (`AGENTS.md`, `SOUL.md`, `USER.md`, `SECURITY.md`) are **copied** into the session workspace on container creation. The agent can freely edit these working copies. To apply changes permanently (to the master copy in `$CARAPACE_DATA_DIR/`), the agent uses the `save_workspace_file` tool, which is gated by the security sentinel.

## Network policy

All outbound traffic from sandbox containers is routed through the Carapace server's HTTP forward proxy:

- Containers receive only `HTTP_PROXY` / `HTTPS_PROXY` environment variables pointing to the proxy
- No direct internet access — enforced by Docker network isolation or Kubernetes NetworkPolicy
- The proxy uses per-session token-based authentication (injected as `Proxy-Authorization` via environment setup script)

### Domain allowlisting

Each session maintains a domain allowlist. Domains are added when:

1. **Skill activation**: Domains declared in a skill's `carapace.yaml` (`network.domains`) are automatically added when the skill is activated
2. **Sentinel approval**: Unknown domains are evaluated by the sentinel. If allowed, they're added for the current exec call. If escalated, the user decides.
3. **Proxy bypass**: During skill venv builds (`uv sync`), the proxy is temporarily bypassed to allow package downloads

The proxy supports exact domain matching (`example.com`) and wildcard matching (`*.example.com`).

## Container lifecycle

- **Creation**: A container is created (or ensured running) when a session needs it — typically on the first tool call
- **Reuse**: The container stays running for the session's duration. Multiple tool calls reuse the same container.
- **Idle timeout**: Configurable (default: 15 min). After timeout, containers are destroyed. Sessions themselves persist (history, state) — only containers are ephemeral.
- **Re-warming**: When the user sends a new message after containers expired, a new container is created with the same mounts. Activated skill venvs are rebuilt automatically.

## Runtimes

Carapace supports two sandbox runtimes, configured via `CARAPACE_SANDBOX_RUNTIME`:

### Docker

The default runtime. Uses the Docker socket (`/var/run/docker.sock`) to manage containers. Sandbox containers run on an internal Docker network (`carapace-sandbox`) with no direct internet access.

### Kubernetes

For cluster deployments. Sandbox sessions run as Kubernetes pods with commands executed via the Kubernetes exec API. See [kubernetes.md](kubernetes.md) for full details.

Both runtimes implement the same `SandboxRuntime` interface, so the rest of Carapace doesn't need to know which backend is in use.

## Docker socket

In Docker mode, Carapace needs access to the Docker socket:

```yaml
services:
  carapace:
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
```

The server uses the Docker SDK for Python to manage container lifecycle, and `docker exec` for command execution.
