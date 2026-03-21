# Plan: Kubernetes Enhancements

> Status: planned. The current Kubernetes runtime works with a shared RWX PVC and ephemeral pods. See [../kubernetes.md](../kubernetes.md) for what exists today.

## Per-session PVCs

Instead of a single shared RWX PVC for all sessions, each session would get its own PVC. This provides:

- Better isolation between sessions
- Independent lifecycle management
- No need for a ReadWriteMany storage class for session data

The server pod would still need access to shared data (config, skills, memory), but session workspaces would be isolated.

## StatefulSets for session pods

Convert session pods from standalone pods to StatefulSets that can be scaled down on idle instead of being deleted:

- **Scale to 0** on idle timeout instead of pod deletion
- **Scale back to 1** when the session is resumed
- Preserves pod identity and any attached storage
- Cleaner lifecycle management via Kubernetes primitives

## Git-backed storage

Store memory and skills as git repositories that the agent commits to. Benefits:

- Full change history with diffs
- Easy rollback
- Multi-agent collaboration (merge workflows)
- Natural backup mechanism

This would apply to both Docker and Kubernetes deployments, but is especially useful in Kubernetes where the data lives on persistent volumes.
