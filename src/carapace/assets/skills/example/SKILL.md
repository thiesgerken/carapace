---
name: example
description: A template skill showing provider-based activation, a Python entrypoint, a Node entrypoint, post-activation setup, and an exec-scoped TCP tunnel.
metadata:
  carapace:
    network:
      tunnels:
        - host: imap.gmail.com
          remote_port: 993
          local_port: 1993
          description: Unauthenticated IMAP CAPABILITY probe over a Carapace-managed tunnel
    commands:
      - name: example-hello
        command: uv run --directory /workspace/skills/example hello
      - name: example-node
        command: pnpm --dir /workspace/skills/example run hello:node
---

# Example Skill

This is a template skill that demonstrates the [AgentSkills](https://agentskills.io/) format
with a Python package, a pnpm-managed Node entrypoint, provider-based activation, post-activation setup,
and an exec-scoped TCP tunnel declared in `metadata.carapace`.

## Exposed Commands

- `example-hello`: Run the Python demo command that probes IMAP `CAPABILITY` through the Carapace-managed tunnel.
- `example-node`: Run the Node demo command from the pnpm-managed entrypoint.

## Instructions

When this skill is activated, run the exposed commands to verify the sandbox environment and tunnel support:

```text
example-hello
example-node
```

The Python command performs an unauthenticated IMAP `CAPABILITY` request against `imap.gmail.com`
through a Carapace-managed tunnel. That demonstrates the important path for non-HTTP protocols:

- `metadata.carapace` declares `network.tunnels`
- `setup.sh` materializes a tiny local config file consumed by the Python command
- `hello` connects to the real hostname on the declared local port so TLS/SNI still work

No mailbox credentials are required for this demo because `CAPABILITY` works before login.

## Reference

Implementation details, provider file layout, and notes for using this as a template live in [REFERENCE.md](REFERENCE.md).
