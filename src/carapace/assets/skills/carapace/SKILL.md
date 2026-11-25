---
name: carapace
description: >-
  Drive a carapace server non-interactively from inside the sandbox: list/inspect/create/update
  sessions, send messages and wait for turns, resolve pending approvals by id, and manage jobs
  (list/get/create/update/delete/run). Use this to let the agent configure, read, start, and
  interact with carapace sessions and jobs over the JSON CLI. Requires a scoped API key in the vault.
---

# carapace CLI

Drive a carapace server over its non-interactive JSON CLI. Authentication is automatic:
`CARAPACE_API_KEY` (from the vault) and `CARAPACE_SERVER` (baked into the `carapace` command)
are set by the `carapace` command itself — never pass `--api-key` on the command line.

## Exposed Commands

- `carapace`: the carapace CLI, pre-authenticated against the configured server.

All sub-commands emit JSON to stdout and never render markdown/LaTeX (agent text passes through
verbatim). **Do not use `carapace chat`** — it is the interactive human REPL and refuses on a
non-TTY. Use the sub-commands below instead.

## Exit codes

- `0` ok
- `1` error (details in the JSON `error` field)
- `2` needs_approval — a turn paused on an approval/escalation request
- `3` timeout — `--wait` timed out; the turn keeps running server-side

## Sessions

```bash
carapace session list [--archived] [--limit N]
carapace session get <session_id>
carapace session create [--ask|--yolo|--unattended] [--model M] [--sentinel-model M] [--channel cli]
carapace session update <session_id> [--ask|--yolo|--unattended] [--model M] \
    [--archive|--unarchive] [--pin|--unpin] [--favorite|--unfavorite]
carapace session history <session_id> [--limit N]   # messages + pending approvals
carapace session pending <session_id>               # just pending approval/escalation requests
carapace session send <session_id> "<message>" [--wait/--no-wait] [--timeout S] [--stream]
carapace session cancel <session_id>                # cancel the running turn
```

`session send --wait` (default) drives one turn over the WebSocket and returns when it ends.
If the turn pauses on an approval/escalation it **aborts without cancelling**, exits `2`, and
returns the request's `id` plus ready-to-run `allow_command` / `deny_command`. With `--stream`,
token/thinking/tool events go to **stderr** while stdout carries the final JSON.

## Approvals

Resolve one specific pending request by its unique `id` (from `session pending`/`history` or a
`needs_approval` result):

```bash
carapace approval allow <session_id> <request_id> [-m "note"] [--wait] [--timeout S]
carapace approval deny  <session_id> <request_id> [-m "note"] [--wait] [--timeout S]
```

Unknown ids return `{"status":"not_found"}` and exit `1`. With `--wait`, the resumed turn is
read and returned like `session send`.

## Jobs

```bash
carapace job list
carapace job get <job_id>
carapace job create -f <file|->          # JobDefinition JSON ('-' reads stdin)
carapace job update <job_id> -f <file|->  # replace
carapace job delete <job_id>
carapace job run <job_id> [--input PAYLOAD] [--wait/--no-wait] [--timeout S]
```

## Typical loop (drive a session to completion)

```bash
sid=$(carapace session create --unattended | jq -r .session_id)
carapace session send "$sid" "do the thing" --wait
# exit 2 -> read the JSON, then:
carapace approval allow "$sid" "<request_id>" --wait
# repeat until exit 0 (status "done")
```
