# Plan: Persistent Shell for the Agent

> Status: planned. Currently every `exec` tool call spawns a fresh process — no shell state persists between calls.

## Problem

Every call to `exec_command` translates to a `docker exec` / `kubectl exec` invocation. Each one is a fresh `bash -c` process with no memory of previous commands. This means:

- `export TOKEN=value` in one `exec` call has no effect on the next
- `cd /some/path` doesn't change the working directory for subsequent commands
- Shell functions, aliases, and sourced files disappear between calls
- Skills that need to export env vars before calling another command must chain them in one semicolon-joined string, which is awkward and fragile

## Design: tmux inside the container

The simplest approach: run a persistent **tmux session** inside the container from startup, and route all agent `exec` calls through it using `send-keys` + `capture-pane`. The container runtime API doesn't need a new IPC mechanism — tmux already handles buffering, multiplexing, and shell state.

```
┌─ Container ─────────────────────────────────────────────────────────┐
│                                                                      │
│  tmux session "agent"                                                │
│  └─ window 0: bash (PID 42, cwd /workspace, env intact)            │
│       $ export TOKEN=abc                                            │
│       $ cd /workspace/skills/my-skill                               │
│       $ python run.py                ← next exec picks up where     │
│                                         the previous left off       │
└──────────────────────────────────────────────────────────────────────┘
        ↑ tmux send-keys "cmd; echo __EXIT:$?__" Enter
        ↑ tmux capture-pane -t agent -p -S -
```

### Sentinel marker protocol

To capture output and exit code reliably without a persistent stream:

```bash
# send to tmux:
tmux send-keys -t agent:0 'YOUR_COMMAND; echo "__DONE__:$?"' Enter

# poll capture-pane until sentinel appears:
tmux capture-pane -t agent:0 -p -S -
```

The `__DONE__:<exit_code>__` sentinel at the end of the pane's scrollback marks completion. The manager polls (with a short sleep) for this marker and returns everything between the start of the command and the sentinel as the output.

To isolate this command's output from previous output, the manager embeds a **command ID** in the sentinel: `__DONE__:<id>:<exit>__`, and records the pane length before sending the command so it can slice only the new lines.

### Two exec paths

The existing split between internal and agent-facing commands is preserved:

| Path                          | Used for                                                    | Shell state                                                      |
| ----------------------------- | ----------------------------------------------------------- | ---------------------------------------------------------------- |
| `_exec()` (raw `docker exec`) | carapace internals: venv builds, file ops, proxy setup, git | Fresh process each time — correct, these are scripted operations |
| `exec_command()` → tmux       | Agent's `exec` tool calls                                   | **Persistent** — env, cwd, functions all survive                 |

This avoids polluting the agent's shell with carapace's internal scaffolding commands.

## What needs to change

### 1. Sandbox image (`sandbox/Dockerfile`)

Add `tmux` to the image:

```dockerfile
RUN apk add --no-cache tmux  # (already Alpine-based)
```

### 2. `ContainerRuntime` protocol (`sandbox/runtime.py`)

Add two new methods:

```python
async def exec_in_shell(
    self,
    container_id: str,
    command: str,
    cmd_id: str,
    timeout: int = 3600,
) -> ExecResult: ...

async def ensure_shell(self, container_id: str) -> None:
    """Start the tmux agent session if it is not already running."""
    ...
```

`exec_in_shell` wraps the send-keys + poll loop. `ensure_shell` is called once after container creation (and after container recreation).

### 3. Docker runtime (`sandbox/docker.py`)

Implement `exec_in_shell` and `ensure_shell`:

```python
async def ensure_shell(self, container_id: str) -> None:
    # Check: tmux has-session -t agent 2>/dev/null
    # If not found: tmux new-session -d -s agent -c /workspace bash
    ...

async def exec_in_shell(self, container_id: str, command: str, cmd_id: str, timeout: int) -> ExecResult:
    # 1. Record current pane line count via `tmux display -p '#{history_size}'`
    # 2. send-keys: f'{command}; echo "__DONE__{cmd_id}__:$?"'
    # 3. Poll capture-pane every 100ms until sentinel appears or timeout
    # 4. Slice output from start line to sentinel line
    # 5. Parse exit code from sentinel
    # 6. Return ExecResult
    ...
```

**Output capture:** `tmux capture-pane -t agent:0 -p -S -` returns the entire scrollback. Slicing by the pre-command line offset gives only the new output. Configure the tmux session with a large scrollback (`tmux set-option -g history-limit 50000`) to avoid losing output for long-running commands.

**Large output concern:** Very large outputs (e.g. the agent running `find /`) still work, but `capture-pane` has to transfer them through the tmux buffer. For outputs over ~1 MB, a better approach is to redirect output to a temp file and read it back — the implementation can detect this case and fall back automatically.

### 4. Kubernetes runtime (`sandbox/kubernetes.py`)

`kubectl exec` is used for the raw path (still correct). For `exec_in_shell`, the same tmux approach applies — `kubectl exec` into the pod to run tmux commands. Identical logic, different transport.

### 5. `SandboxManager` (`sandbox/manager.py`)

- `ensure_session()`: call `runtime.ensure_shell(container_id)` after creating or re-attaching to a container
- `exec_command()`: replace `self._exec(...)` with `self._runtime.exec_in_shell(...)` (still goes through the exec lock)
- On container recreation (`_prepare_session_recreate`): `ensure_shell` is called again as part of `ensure_session`, so the tmux session is automatically re-created — shell state is lost (the container is gone), which is unavoidable and expected

### 6. Credentials (`docs/credentials.md`)

The caveat about `export TOKEN=...` not persisting is removed — with tmux, it works correctly. The credentials skill `SKILL.md` no longer needs to warn about this limitation.

## What does NOT change

- `tools.py` — the `exec` tool interface is unchanged
- The `_exec()` path for carapace-internal commands — still uses raw `docker exec`
- The exec lock — one command at a time per session, same as before
- Container lifecycle, proxy, git, file operations — unaffected

## Failure modes

| Scenario                                                                  | Behaviour                                                                                          |
| ------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| tmux process killed inside container                                      | `ensure_shell` restarts it on the next `exec_command`; shell state is lost but execution continues |
| Container gone mid-command                                                | Existing `ContainerGoneError` path triggers container recreation + `ensure_shell`; same as today   |
| Command produces no `__DONE__` sentinel (e.g. command itself killed tmux) | Timeout fires after `timeout` seconds; `ExecResult(exit_code=-1, output="timed out")`              |
| Very long output                                                          | Redirect stdout to a tempfile, read back after sentinel; automatic fallback                        |

## Alternatives considered

**Named pipe / FIFO**: More complex setup, doesn't survive container restarts well.
**PTY via `docker exec -it`**: The SDK supports it but streaming back to async Python is non-trivial and output capture is messier.
**Stateful sidecar process**: Overkill; tmux is already designed for exactly this.

## Migration

No breaking changes. The tmux session is transparent to the agent — `exec` tool calls behave identically from the LLM's perspective, just with shell state now persisting between calls.
