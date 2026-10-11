# Jobs

carapace can run saved jobs on demand or on a cron schedule. Jobs are a first-class server feature with REST endpoints, a web UI, and persistent definitions stored on disk.

## Overview

Jobs let you save a prompt plus execution mode and optional model overrides, then run it:

- manually from the web UI or REST API
- automatically from cron triggers in `jobs.yaml`
- either in a fresh unattended session or in a reused attended session

Definitions live in `$CARAPACE_DATA_DIR/jobs.yaml`.

Each execution records lightweight run context in the target session so the UI can show which job triggered it, when it ran, and any invocation payload that was supplied.

## Storage model

Jobs are stored in YAML as:

```yaml
jobs:
  - id: morning-briefing
    name: Morning briefing
    enabled: true
    triggers:
      - type: cron
        expression: "0 7 * * 1-5"
        timezone: Europe/Berlin
    prompt: >
      Summarize overnight alerts, yesterday's failed jobs, and anything that
      still needs manual attention.
    private: false
    unattended: true
    ask_mode: false
    yolo_mode: false
    archive_previous_sessions: false
    persistent_session_id: null
    agent_model_name: null
    sentinel_model_name: null
    title_model_name: null
    memory_enabled: false
```

## Job fields

| Field                   | Meaning                                                                                                    |
| ----------------------- | ---------------------------------------------------------------------------------------------------------- |
| `id`                    | Stable identifier used in the API and UI                                                                   |
| `name`                  | Human-readable label                                                                                       |
| `enabled`               | Whether cron scheduling should consider the job                                                            |
| `triggers`              | Zero or more cron triggers                                                                                 |
| `prompt`                | Instructions sent to the agent when the job runs                                                           |
| `private`               | Whether a fresh session created for this job starts private                                                |
| `unattended`            | Whether a fresh session created for this job runs without a user approval path                             |
| `ask_mode`              | Restrict a fresh session to read-only operations outside the sandbox while keeping sentinel review enabled |
| `yolo_mode`             | Bypass sentinel review for a fresh session                                                                 |
| `archive_previous_sessions` | When a fresh session is created, archive earlier still-open sessions from this job (fresh-session jobs only) |
| `persistent_session_id` | Reuse an existing attended session instead of creating a fresh one                                         |
| `agent_model_name`      | Optional agent model override for fresh sessions                                                           |
| `sentinel_model_name`   | Optional sentinel model override for fresh sessions                                                        |
| `title_model_name`      | Optional title-model override for fresh sessions                                                           |
| `memory_enabled`        | Include this job's sessions in [long-term memory](memory.md) (default `false`)                             |

## Trigger model

Each trigger currently has type `cron`:

```yaml
triggers:
  - type: cron
    expression: "*/15 * * * *"
    timezone: UTC
```

Notes:

- `expression` must be a valid cron expression.
- `timezone` is optional. If omitted, UTC is used.
- The scheduler tracks the last sweep time and backfills missed cron ticks up to an internal limit, so short outages do not necessarily drop every run.
- Setting `enabled: false` disables scheduling without deleting the job definition.

## Fresh session vs persistent session

Jobs support two execution patterns.

### Fresh session job

If `persistent_session_id` is not set, each run creates a new session with:

- `channel_type: "job"`
- `channel_ref: "job:<job-id>"`
- the configured `private`, `unattended`, `ask_mode`, and `yolo_mode` flags
- optional per-job model overrides

This is the usual pattern for unattended automation.

If `archive_previous_sessions` is set, the run archives any earlier sessions created by this job (`channel_ref: "job:<job-id>"`) that are not already archived: each is committed to knowledge, marked archived, and has its sandbox torn down. Sessions with an agent turn still running are skipped. This keeps a recurring job (e.g. a daily digest) from accumulating idle sessions and sandboxes. It only applies to fresh-session jobs and is rejected together with `persistent_session_id`.

### Persistent session job

If `persistent_session_id` is set, the run reuses an existing session instead of creating a new one.

Restrictions enforced by validation:

- the referenced session must exist
- it must be attended, not unattended
- it must not be archived
- job-level session mode overrides are not allowed
- job-level model overrides are not allowed
- `archive_previous_sessions` is not allowed

Use this when you want recurring work to accumulate in one long-lived session thread.

## Run context in the session

Each execution stores lightweight metadata in `SessionState.latest_job_run`, including:

- `job_id`
- `trigger_kind`: `api`, `cron`, or `manual`
- `triggered_at`
- optional invocation `data`
- optional `cron_expression`

The web UI uses this to label job-driven sessions and show the most recent run details.

## Invocation payloads

Manual and API-triggered runs may include an optional free-form payload string. carapace appends that payload to the generated job-run message so the agent sees both the saved job prompt and the invocation-specific data.

## Web UI

The web app exposes jobs in Settings:

- create, edit, and delete jobs
- enable or disable scheduled execution
- run a job immediately
- choose cron expressions and time zones
- switch between fresh-session and persistent-session modes
- override agent, sentinel, and title models for fresh-session jobs
- include the job's sessions in long-term memory ("Include in memory")

Job-linked sessions also show recent job metadata in the chat view.

## REST API

| Endpoint                 | Method   | Purpose               |
| ------------------------ | -------- | --------------------- |
| `/api/jobs`              | `GET`    | List all jobs         |
| `/api/jobs`              | `POST`   | Create a job          |
| `/api/jobs/{job_id}`     | `GET`    | Fetch one job         |
| `/api/jobs/{job_id}`     | `PUT`    | Replace a job         |
| `/api/jobs/{job_id}`     | `DELETE` | Delete a job          |
| `/api/jobs/{job_id}/run` | `POST`   | Run a job immediately |

Example manual run:

```bash
curl -c carapace-cookie.jar \
  -H "Content-Type: application/json" \
  http://localhost:8321/api/auth/login \
  -d '{"username":"alice","password":"change-me"}'

curl -X POST \
  -b carapace-cookie.jar \
  -H "Content-Type: application/json" \
  http://localhost:8321/api/jobs/morning-briefing/run \
  -d '{"data":"Focus on production incidents only."}'
```

## Scheduling lifecycle

The server runs an internal scheduler loop that:

- wakes periodically
- loads `jobs.yaml`
- computes due cron runs
- starts job executions one by one

Cron-triggered runs use `trigger_kind="cron"`. Manual API-triggered runs use `trigger_kind="api"`.

## Operational notes

- Jobs target normal carapace sessions, so sandbox lifecycle, credential approval rules, knowledge commits, and notifications still apply.
- Unattended job sessions can emit `unattended_turn_completed` and `unattended_turn_failed` notifications.
- If a target session is already busy when a job tries to run, the run is rejected.
- Job sessions stay out of long-term memory unless `memory_enabled` is set, so a recurring job does not flood the weekly digests with near-identical runs.

## Related docs

- [sessions-and-channels.md](sessions-and-channels.md) for session lifecycle and controls
- [memory.md](memory.md) for long-term memory and which sessions it includes
- [notifications.md](notifications.md) for unattended completion notifications
- [quickstart.md](quickstart.md) for deployment and basic configuration
