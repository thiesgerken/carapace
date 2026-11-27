# carapace CLI Skill — Reference

Maintainer/operator notes. Runtime instructions for the agent live in `SKILL.md`.

## What this skill does

Bundles the carapace CLI inside the sandbox so an agent can drive a carapace server
non-interactively: manage sessions, send messages, resolve approvals, and manage jobs
(see `SKILL.md` for the command surface). It is a thin packaging layer — the actual CLI
is the `carapace` console script installed from the carapace package itself.

## Required setup (per deployment)

This skill ships with **placeholders** and will not work until an operator fills them in.

### 1. Create a scoped API key

In the carapace UI, create a scoped API key with the minimum scopes the agent needs
(typically `sessions:read`, `sessions:write`, and `jobs:*` depending on the task).

### 2. Store the key in the vault and configure the skill

Put the API key in your credential vault and note its `<backend>/<id>` path. The sandbox
refuses loopback and internal hosts (`localhost`, `127.0.0.1`, cluster services, …), so the
CLI must reach the deployment's **public** API domain. Both go into `skills/config.json`,
under the skill's attribute `carapace-cli`; a new knowledge repo has it turned off until then:

```json
{
  "carapace-cli": {
    "settings": { "CARAPACE_HOST": "carapace.example.com" },
    "credentials": { "CARAPACE_API_KEY": "<backend>/<your-carapace-api-key-id>" }
  }
}
```

`CARAPACE_HOST` is the public API domain, without `https://`. Remove `"enable": false` if it is
still there. The command asks for that domain and the credential when it runs, gets the key as
`CARAPACE_API_KEY` (the CLI reads it from there, never from a command line), and points the CLI
at `https://$CARAPACE_HOST`. Commit and push; the builder re-evaluates the skill.

## Which CLI

`carapace.lib.carapaceCli` builds the CLI client of the Carapace commit `flake.lock` pins:
the base `carapace` package, about 16 dependencies, without the `server` extra and its
heavy stack. Updating that pin (`nix flake lock --override-input carapace
github:thiesgerken/carapace/<rev>?dir=nix/skills`) updates the CLI and the skill helpers
together.

## File layout

```text
skills/carapace/
  SKILL.md         # agent instructions
  REFERENCE.md     # this file
  flake.nix        # the CARAPACE_HOST setting, the CARAPACE_API_KEY slot, the `carapace` command
  flake.lock       # pins nixpkgs and the Carapace commit
```

## The command

The `carapace` wrapper runs
`env CARAPACE_SERVER=https://<server> <cli>/bin/carapace "$@"`, after asking for the
declared domain and credential. `CARAPACE_SERVER` is fixed in the build, so the agent never
passes `--server`. Nothing is installed at run time.
