---
name: example
description: A template skill showing provider-based activation, a Python entrypoint, a Node entrypoint, post-activation setup, and an exec-scoped TCP tunnel.
---

# Example Skill

This is a template skill that demonstrates the [AgentSkills](https://agentskills.io/) format
with a Python package, a pnpm-managed Node entrypoint, provider-based activation, post-activation setup,
and an exec-scoped TCP tunnel declared in `carapace.yaml`.

## Instructions

When this skill is activated, run the example commands to verify the sandbox environment and tunnel support:

```text
uv run --directory /workspace/skills/example hello
pnpm --dir /workspace/skills/example run hello:node
```

The Python command performs an unauthenticated IMAP `CAPABILITY` request against `imap.gmail.com`
through a Carapace-managed tunnel. That demonstrates the important path for non-HTTP protocols:

- `carapace.yaml` declares `network.tunnels`
- `setup.sh` materializes a tiny local config file consumed by the Python command
- `hello` connects to the real hostname on the declared local port so TLS/SNI still work

No mailbox credentials are required for this demo because `CAPABILITY` works before login.

## Reference

Implementation details, provider file layout, and notes for using this as a template live in [REFERENCE.md](REFERENCE.md).
