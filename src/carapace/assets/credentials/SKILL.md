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
  - vault_path: personal/9742101e-...
    description: Gmail app password
    env_var: GMAIL_APP_PASSWORD
  - vault_path: dev/ssh-deploy-key
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
ccred list -q gmail     # filter by name or description
```

The list shows metadata only (name, vault path, description) — never values.

## Fetching a credential on demand

For credentials not declared in `carapace.yaml`, use `ccred get`:

```bash
# Print value to stdout (for piping or subshell capture)
ccred get personal/9742101e-...

# Write to a file with restrictive permissions (0400)
ccred get dev/ssh-deploy-key -o ~/.ssh/id_ed25519

# Use as an env var for a single command
API_KEY=$(ccred get dev/api-key) ./my-script.sh
```

The `get` command **blocks** until the user approves the credential. Always
explain to the user what you need and why **before** running `ccred get`.

## Important rules

- **Never** echo, print, log, or return credential values as command output
- **Never** include credential values in tool call arguments or responses
- **Never** store credentials in files that will be committed to git
- If a credential is already approved for the session, `ccred get` returns
  it immediately without re-prompting
- After `/reset`, all approvals are revoked
