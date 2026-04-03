---
name: credentials
description: Documents the credential system — how to list, fetch, and use secrets from the vault.
---

# Credentials

Carapace provides a pull-based credential system. Credentials live in an
external vault (password manager or file) and are fetched on demand. **You
never see the raw secret values** — they are injected directly into the
sandbox environment.

## Auto-injection via `carapace.yaml`

Skills that need credentials declare them in their `carapace.yaml`:

```yaml
credentials:
  - vault_path: <backend>/9742101e-...
    description: Gmail app password
    env_var: GMAIL_APP_PASSWORD
  - vault_path: <backend>/ssh-deploy-key
    description: SSH deploy key
    file: ~/.ssh/id_ed25519
```

When you activate the skill with `use_skill`, Carapace:

1. Sends all declared credentials through the security sentinel
2. Asks the user for approval (one prompt for the whole bundle)
3. Fetches the values from the vault
4. Injects `env_var` entries as environment variables (available in all
   subsequent `exec` calls for the session)
5. Writes `file` entries to the specified path with mode `0400`

You don't need to do anything — just call `use_skill` and the credentials
are ready.

## Listing available credentials

```bash
ccred list              # show all available credentials
ccred search gmail      # filter by name or description
```

The list shows metadata only (name, vault path, description) — never values.

## Fetching a credential on demand

For credentials not declared in `carapace.yaml`, use `ccred get`:

```bash
# Print value to stdout (for piping or subshell capture; blocks until approved)
ccred get <backend>/<id>

# Write to a file with restrictive permissions (0400; -o is also subject to approval)
ccred get <backend>/<id> -o ~/.ssh/id_ed25519

# Use as an env var for a single command
API_KEY=$(ccred get <backend>/api-key) ./my-script.sh
```

`<backend>` is the vault backend name from server config; `<id>` is the
credential identifier (often a UUID). The `get` command blocks until approval in
the UI — you do not need to manage that flow. Only request credentials that are
actually needed for the task.

## Important rules

- Only request credentials that are needed; **never** echo, print, log, or
  return secret values as command output
- **Never** include credential values in tool call arguments or responses
- **Never** store credentials in files that will be committed to git
- If a credential is already approved for the session, `ccred get` returns
  it immediately without re-prompting
- After `/reset`, all approvals are revoked
