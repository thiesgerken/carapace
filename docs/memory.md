# Long-Term Memory

carapace archives every session, and long-term memory distills those archives into something you can read and the agent can use: one structured extraction per session, rolled up into weekly and monthly digests of what was on your mind and what was learned about you.

Memory is built for inspection. Every record says which model, prompt version, input and carapace version produced it and what it cost. All LLM work runs as **tasks** in a per-user queue that you control, with estimates and a budget.

---

## Overview

```
month 2026-09          memory_high, input = current weekly digests of that month
 ├── week 2026-W36     memory_high, input = current session extractions of that week
 │    ├── session A    memory_low,  input = the session's rendered events
 │    └── session B
 └── week 2026-W37
```

- **Session extraction**: one LLM call per session (`memory_low` model) turns its transcript into an abstract, outcomes, open loops, what was on your mind, friction, tags and facts.
- **Week and month digests** (`memory_high` model): each level reads only the level directly below it. A monthly digest never sees a transcript.
- **Tasks**: every extraction and digest is a task in your queue. Creating a task is free and automatic. Running one costs money, so it needs you (manual mode) or auto mode plus budget headroom.
- **Source of truth** is carapace's database. A one-way **mirror** writes Markdown into your knowledge repo under `memory/`, so the agent can read and grep it. The mirror is never read back.
- **Everything is per user**: tasks, records, budgets, auto mode, models and timezone.

Manage it all in the **Memory** area of the web UI (the brain icon next to Knowledge).

---

## Session extraction

### Input

The model never sees the raw session. A pure, versioned renderer (`memory/input.py`) turns a session's events into text:

- It starts at the first user message.
- User and assistant text are included in full.
- Slash commands, approvals, command results, thinking and other non-conversational events are dropped.
- A tool call becomes its name plus JSON arguments. Tool calls and results are clamped to 1,000 characters (the first 600 and the last 400, with an `[… 12,345 chars elided …]` marker), because errors and exit codes live at the end of outputs.
- A non-zero exit code goes into the result label (`[#7 tool_result exec exit=1]`), so failures stay visible.
- Each attachment becomes one placeholder line (`[attachment: image/png, screenshot.png]`).
- Every block is prefixed with its event number (`[#42 user]`, `[#43 tool_call exec]`). The model cites these numbers as fact sources, and the UI links them back to the chat.

The renderer also produces an `input_hash` (sha256 of the rendered text) and a token estimate. `INPUT_FORMAT_VERSION` is bumped whenever rendering changes.

Sessions without an event transcript (legacy sessions from before events were stored) are not eligible. The status endpoint reports how many were skipped.

### Schema

| Field | Content |
| --- | --- |
| `abstract` | 2 to 5 sentences: what the session was about |
| `outcomes` | decisions made, things accomplished |
| `open_loops` | unfinished work, follow-ups the user or agent mentioned |
| `on_my_mind` | topics, projects, worries the user was occupied with |
| `facts` | list of facts (below) |
| `friction` | where the agent lacked a skill, credential, context or permission |
| `tags` | short topic tags |

Each fact:

| Field | Content |
| --- | --- |
| `category` | `user` (you and your life), `social` (people and relationships), `surroundings` (home, places, devices, infrastructure, tools, services) |
| `statement` | one self-contained sentence |
| `subject` | the person or thing the fact is about (required for `social`) |
| `source_seqs` | event numbers that support it |
| `source_kind` | `user_said`, or `observed` (derived from tool output or agent work) |
| `confidence` | `low`, `medium`, `high` |
| `durability` | `durable` or `dated` |
| `valid_until` | optional end date for dated facts |

Output is always English, whatever language the conversation was in.

### Guards

Memory output lands in your knowledge repo and is meant to feed a generated system prompt later, so the prompts are strict about what may become a fact:

- Facts about you and your social connections must come from what you said (`user_said`). Tool output may only yield `surroundings` facts. This is the main guard against tool output injecting "facts" about you.
- Passwords, keys and tokens are never recorded.
- The transcript sits inside delimiters, followed by a restated instruction tail. A closing delimiter inside the transcript is escaped, so tool output cannot break out of the data region.
- Each memory LLM call is single-shot (one request, no output retries), so a task is exactly one billed call and its estimate is an honest upper bound. Invalid output fails the task.

---

## Provenance

Every extraction, every digest and every finished task records:

| Field | Meaning |
| --- | --- |
| `carapace_version` | carapace version at run time |
| `model` | resolved model name |
| `prompt_version` | 12-character sha256 prefix over system prompt, context line, tail and output JSON schema |
| `input_format_version` | version of the input or digest renderer |
| `input_hash` | hash of the exact text sent to the model |
| `input_tokens`, `output_tokens`, `cost_usd` | usage and provider cost (`cost_usd` is empty for models without known pricing) |
| `duration_ms` | wall clock of the LLM call |
| `task_id` | the task that produced it |
| `created_at` | timestamp |

`prompt_version` is computed, not maintained by hand: editing a prompt or the output schema changes it.

A record's **identity** is `(kind, target, input_hash, prompt_version, model)`. The carapace version is recorded but never part of the identity; otherwise every release would re-bill the whole archive.

Earlier versions are kept. When a session is re-extracted (new input, another model, a new prompt), the old extraction stays in its version history, and the same holds for digests. This is how you compare models: respawn with a model override, then look at both results.

---

## The pyramid

### Periods

- Weeks are ISO weeks (Monday start) in **your timezone** (a user setting, default `Europe/Berlin`).
- A session belongs to the week of its **first user message**. This is stable under re-extraction: a session revived two weeks later still counts towards its original week.
- An ISO week belongs to the month of its **Thursday**. 2026-W36 (Aug 31 to Sep 6) belongs to 2026-09. Each week is in exactly one month, so the timeline tree stays consistent. A session's month follows from its week, not from its calendar date.

### Digests

Week and month digests share one shape:

- `summary`: a narrative of the period
- `on_my_mind`: themes, each with refs to the sessions (or weeks) it came from
- `highlights`: notable outcomes and decisions
- `open_loops`: still open at the end of the period
- `learned`: deduplicated facts grouped by category, with refs

`learned` is built only from the facts of the level below and keeps each fact's `category` and `source_kind`. It is never derived from prose, so tool output cannot turn into a fact about you one level up.

### Coverage and staleness

A digest records which source records it consumed (`source_id`, `source_hash`) and a `coverage_hash` over that list. A digest is **stale** when the coverage computed from the period's *current* sources differs, for example because a new session was extracted, a session was re-extracted or a session was deleted. Stale weeks make their month stale by the same rule.

Partial runs are allowed: a weekly digest over 12 of 14 sessions is fine. The UI shows `12/14`, and the digest turns stale when the rest arrive.

A record is **outdated** when it was produced with an older prompt version, another model or an older input format than the current one. Outdated records are never re-run automatically (see [Spawning rules](#spawning-rules)).

---

## Tasks

| Kind | Target | Model | Output |
| --- | --- | --- | --- |
| `session_extract` | session id | `memory_low` | session extraction + facts |
| `week_digest` | `2026-W36` | `memory_high` | week digest |
| `month_digest` | `2026-09` | `memory_high` | month digest |
| `mirror` | user | none | files + one commit in the knowledge repo |

### Lifecycle

```
pending ──run──▶ queued ──claim──▶ running ──▶ done
   │                │                  └─────▶ failed ──retry──▶ queued
   └──cancel──▶ cancelled ◀──cancel──┘
```

- There is at most one open task (`pending`, `queued` or `running`) per user, kind and target. A newer spawn for the same target replaces a `pending` one.
- Retry reuses the task (`attempts` goes up). Nothing is retried automatically; transient HTTP errors are already retried by the model transport.
- On server start, tasks left `running` return to `queued`.
- A failed call that was billed still counts: tasks accumulate billed tokens and cost over all attempts, and spend includes failed tasks.
- Right before a session task runs, its eligibility is checked again. A session that turned private or was deleted cancels the task (and purges its extractions). A session with an agent turn in progress stays queued and is tried again on a later tick.
- `mirror` tasks are free and run automatically, in manual mode too. Auto mode governs LLM spend only.

### Spawning rules

The spawner polls the session table every five minutes. It is not hooked into the session engine.

A `session_extract` task is spawned when all of these hold:

- the session is not private
- the session is not a job session, or its job has `memory_enabled: true` (see [jobs.md](jobs.md))
- the session is archived, or idle for `sessions.commit.autosave_inactivity_hours`
- no agent turn is running
- the rendered input differs from the current extraction, or none exists

A `week_digest` or `month_digest` task is spawned when all of these hold:

- the period has ended (in your timezone)
- at least one current source exists
- the period is **settled**: no open `session_extract` (for weeks) or `week_digest` (for months) task remains for it
- the coverage differs from the current digest, or none exists

The settled rule keeps a backfill from re-spawning the same weekly digest after every single extraction.

**Only input changes spawn automatically.** A continued session (new input) gets a new task. A done, failed or cancelled task for unchanged input is never repeated by the spawner: retrying or respawning it is your call. A changed prompt, model or input format never does: the affected records show as outdated, and you respawn them in bulk from the Sessions tab. Otherwise a prompt tweak plus auto mode would re-bill the whole archive.

Manual spawns are always possible: any session, and any digest including the running week. Manual spawns go through the same eligibility checks; skipped targets are reported with their reason. A respawn can carry a model override.

If a single session fails during a sweep (for example, unreadable events), the spawner records a `failed` task with the error instead of stopping the sweep, so it shows up in the Tasks tab with Retry.

---

## Budget and auto mode

Per user, in the user settings:

```yaml
timezone: Europe/Berlin
memory:
  auto_mode: false
  budget:
    cost_usd_per_day: 1.00
    cost_usd_per_month: 10.00
    input_tokens_per_day: null      # for local models without pricing
    input_tokens_per_month: null
default_models:
  memory_low: null                  # null: platform default
  memory_high: null
```

- `null` disables a limit. `0` is a real limit that allows no spend.
- **Spend** is the sum over your tasks in the current day and month window, in your timezone, including failed but billed attempts. Running tasks count with their estimate.
- **Gate**: before a task runs, every configured limit must hold: `spend + estimate <= limit`. The gate applies to manual runs too. Tasks that do not fit stay `queued` with `blocked_reason = "budget"`, and the UI marks them. Raising the budget, or the next window, unblocks them.
- **Auto mode** (off by default): the worker queues `pending` tasks itself, as far as the remaining budget covers after the tasks already queued, in this order: session extractions, then week digests, then month digests, each newest period first.
- **Estimates** are exact on the input side (the input is deterministic) and capped on the output side (a per-kind output token ceiling, also enforced on the call). Cost uses the per-model pricing carapace already uses for session budgets. Models without known pricing show tokens only, which is what the token limits are for.
- An input larger than the model's context fails the task with `input too large`.

## Model roles

| Role | Used for | User setting | Platform default | Fallback |
| --- | --- | --- | --- | --- |
| `memory_low` | session extraction | `default_models.memory_low` | `agent.memory_low_model` | compaction model, then title model |
| `memory_high` | week and month digests | `default_models.memory_high` | `agent.memory_high_model` | agent model |

A cheap, haiku-class or local model is enough for `memory_low`. Digests benefit from a stronger `memory_high` model. Memory roles are not session roles: `/model` and per-session overrides do not affect them. A run can override the model per task (run dialog, respawn).

---

## Mirror

The mirror renders your current records into your knowledge repo:

```
memory/README.md                          # explains the layout; edits are overwritten
memory/sessions/2026/09/<session_id>.md
memory/weeks/2026-W36.md
memory/months/2026-09.md
```

- Each file starts with YAML front matter (provenance, and coverage for digests), followed by a Markdown body. In session files, `#42` refers to event 42 of that session.
- The mirror owns `memory/` completely. Each run writes exactly the files for the current records and deletes everything else there, so deleted or purged records lose their files, and pushed edits under `memory/` are reverted. Everything outside `memory/` is untouched.
- Runs are debounced: a pending mirror runs once no LLM task of yours is queued or running, or after two minutes at the latest. A batch of tasks therefore produces **one commit** (`🧠 memory: update mirror (N records)`), not one per task. Unchanged records produce no diff and no commit.
- The mirror uses the same commit, push and per-repo locking path as the session archive.

See [persistent-context.md](persistent-context.md) for how the knowledge repo reaches the agent.

---

## Deletion and privacy

- **Private sessions** never get tasks. A session that turns private after extraction has its extractions purged on the next sweep (or when a queued task for it is dispatched).
- **Deleted sessions**: their extractions and facts are deleted with them. Digests covering them turn stale, and the mirror removes their files.
- Digests can still contain text derived from a deleted or private session until they are regenerated. Stale digests are flagged in the Timeline, and regenerating takes one click.
- **Job sessions** are excluded unless the job opts in with `memory_enabled`.

---

## Web UI

The Memory area lives at `/memory`, with four tabs. A **status strip** on top of every tab shows auto mode (it links to the settings), today's and this month's spend against the budget, queue counts (pending, queued, running, failed, held by budget) and the effective `memory_low` and `memory_high` models. While tasks are queued or running, the strip and the open tab refresh every few seconds.

### Timeline

The pyramid as a tree of years, months and weeks. Each node shows its coverage (`12/14` sessions, or weeks for a month) and a badge: `✓` current, `⚠` stale or outdated (hover for the reason), `—` not run yet.

Selecting a period shows its digest: summary, on my mind, highlights, open loops and learned (You, People, Surroundings), each with refs. Week refs open the session's extraction, month refs open the week. Below the digest are a provenance line, **Regenerate** (spawns the digest task and opens the run dialog with its estimate), the period's sources and a collapsed list of earlier versions with their provenance.

`/memory/timeline?period=2026-W36` links straight to a period.

### Sessions

All eligible sessions with their extraction state: date, title and abstract, fact counts (You · People · Surroundings), model, status and cost. Filter by week, extraction state (not extracted, current, outdated), outdated reason (prompt, model, input format), task status, model and channel.

Select rows, or **select all N matching** a filter, then:

- **Run selected** runs the selected sessions' tasks, after the estimate.
- **Respawn selected** creates fresh tasks (for example, after a prompt change: filter outdated by prompt, select all matching, respawn) and opens the run dialog for them.

Clicking a session opens the **extraction drawer**: all schema fields, facts by category, provenance and earlier versions. Fact sources (`#42`) open the chat at that event (`/?session=<id>&event=42`). Only the current extraction links its sources: rewinding a session reuses event numbers, so sources of older versions are shown as plain text.

Sessions with a current extraction show a **Memory** chip in the chat header that opens the same drawer. `/memory/sessions?session=<id>` opens the drawer directly.

### Facts

The facts of all current extractions, as **You**, **People** (grouped by subject) and **Surroundings**. Filter by confidence, durability, source kind and month, plus a free-text filter over statement, subject and session title.

The same fact from several sessions (same statement and subject, ignoring case, spacing and trailing punctuation) appears once, with when it was first and last seen and links to every source session and event. Dated facts whose `valid_until` has passed are greyed out.

### Tasks

The queue. Filter by status, kind, month and model; the header shows the number of matching tasks and their estimated cost. "Run all of September" is: filter month 2026-09, select all matching, run. The month filter places session tasks by their session's week, not by when the task was created.

- **Run newest 50**, **Run selected**, **Cancel selected**, and **Retry** on failed rows.
- The **run dialog** shows the task count, input tokens, estimated cost, remaining budget (and a warning when the run exceeds it) and lets you override the model for this run.
- Clicking a task's target shows its details: attempts, timings, estimate, provenance and usage, the error, and a link to the record it produced.

### Settings

- **Settings → Account → Memory** (`/settings/account#memory`): auto mode, the four budget limits, timezone, and the `memory_low` and `memory_high` models.
- **Settings → Admin → Models**: platform defaults for `memory_low` and `memory_high`.
- **Settings → Jobs**: "Include in memory" per job (`memory_enabled`).

---

## API

All endpoints live under `/api/memory`, are scoped to the authenticated user and use the `knowledge` API key scope (read for queries, write for actions).

| Method + path | Purpose |
| --- | --- |
| `GET /status` | auto mode, budget gauges, queue counts, effective models |
| `GET /tasks` | filter by status, kind, period, model; cursor pagination; total and estimate |
| `POST /tasks/estimate` | estimate for task ids or a filter |
| `POST /tasks/run` | run task ids, a filter, or the newest N of a filter; optional model override |
| `POST /tasks/cancel` | cancel task ids or a filter |
| `POST /tasks/retry` | retry failed task ids |
| `POST /tasks/spawn` | spawn or respawn for explicit targets or a session filter; optional model override |
| `GET /sessions` | sessions with extraction state; filters as in the Sessions tab |
| `GET /sessions/{id}` | current extraction and version history |
| `GET /periods` | tree of months and weeks with coverage and stale flags |
| `GET /periods/{level}/{key}` | digest (current and history) and its sources |
| `GET /facts` | facts of current extractions; filter by category, subject, confidence, durability, source kind, period |

Memory settings use the existing user-settings and platform-settings endpoints.

## Related docs

- [persistent-context.md](persistent-context.md) for the knowledge repo and the `memory/` mirror
- [jobs.md](jobs.md) for `memory_enabled`
- [architecture.md](architecture.md) for the `memory` package and its boundaries
