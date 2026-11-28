# Credentials

carapace provides a pull-based credential system. Credentials live in an
external vault (password manager or file) and are fetched on demand, so they
pass through the sandbox shell: wire them into commands via `-o`, a pipe or
subshell capture so that tools consume the values without exposing them.

## Credentials of skill commands

A skill command that needs a credential declares a credential slot in the skill's
`flake.nix`, bound to an entry in `skills/config.json` (see the `create-skill` skill). When you run
the command, its wrapper asks for everything it declared at once, fetches the
credentials and exports them as environment variables for that command only.
You do not need to do anything but run the command.
**Never read, echo or return those values.**

## Listing available credentials

```bash
ccred list              # show all available credentials
ccred search gmail      # filter by name or description
```

The list shows metadata only (name, vault path, description) — never values.
It still enumerates the vault, so it is reviewed like `ccred get`.

## Fetching a credential on demand

For credentials no skill command declares, use `ccred get`:

```bash
# Write to a file with restrictive permissions (0400; -o is also subject to approval)
ccred get <backend>/<id> -o ~/.ssh/id_ed25519

# Pass a provider login name or complete provider-specific item to a consumer
LOGIN=$(ccred get <backend>/<id> --login) ./some-tool
ccred get <backend>/<id> --json | ./provider-aware-tool

# Use as an env var for a single command (value never visible in output)
API_KEY=$(ccred get <backend>/api-key) ./my-script.sh

# Pipe directly into a tool
ccred get <backend>/<id> | some-tool --token-stdin
```

`<backend>` is the vault backend name from server config; `<id>` is the
credential identifier (often a UUID). By default, `get` returns the credential's
password/value. `--login` returns the provider login name when supported and exits
non-zero otherwise. `--json` returns the complete provider-specific item for every
backend. Alternate representations always require the normal approval flow. The
`get` command blocks until approval in the UI — you
do not need to manage that flow. Only request credentials that are actually needed
for the task.

## Important rules

- Only request credentials that are needed; **never** echo, print, log, or
  return secret values as command output
- **Never** include credential values in tool call arguments or responses
- **Never** store credentials in files that will be committed to git
- If a credential was already approved earlier in the same `exec` (in the same
  form: password, `--login` or `--json`), `ccred get` returns it immediately
  without re-prompting; the next `exec` asks again
- A denial makes `ccred` exit with status 1 and print the reason on stderr;
  do not retry the same request unchanged
