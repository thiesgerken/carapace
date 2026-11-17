# Debug View

The debug view shows, per session and live, where each turn's time went (the **timeline**) and the
latest **LLM context** of every agent role: exactly what went to the model in its last request, and
what came back. Terms follow [GLOSSARY.md](../GLOSSARY.md).

## Using it

The **Chat | Debug** switch in the session header opens `/?session=<ID>&view=debug`. The tabs come
in two groups: **Turns** opens by default and shows where a turn's time went (see
[Turns tab](#turns-tab)). After it, under **Requests:**, comes one tab per role (on a phone that
group takes its own line). Each role tab shows the role's **Requests** table and its latest request:

- **Requests**: one row per recorded request of the role, newest first, so requests compare side by
  side: time, duration, input, cache hits (cache read ÷ input), cache read, cache write, output and
  reasoning tokens, cost and model. The table stresses exceptions, not the norm:
  - A completed request has no status marker. A failed one gets a red icon, and an interrupted one
    a grey icon.
  - The duration leads, with a bar of the request's phases in the waterfall's colors.
  - Counts are compact (12.3k), with the exact number in the tooltip.
  - A count column that is 0 or unknown in every row is left out. Cache hits go with the cache
    reads: without any (caching off, or prompts too short to cache), every row would be a 0 % miss.
  - Cache hits show as a small pill: its length is the request's input relative to the largest
    input in the table (all turns, so turns compare), its grey part the cache read, the rest the
    uncached input. A miss (0 %) is the one in an accent color, so it stands out where caching
    otherwise works: a cold first request, or a broken prefix.
  - The cost is one cell: the actual cost, or `≈` the equivalent for a subscription request
    (nothing billed). The server prices a request at its list price or, on a subscription, at zero.
  - The model column shows only when the rows differ in model.
  - `–` marks a value the record does not have.

  The row of the request shown below is highlighted, and its time links to it. Only the latest
  request keeps its context, so older rows have numbers only.
- The rows are grouped by turn, newest first. A header row shows when the turn started and its
  prompt, and links to the turn in the Turns tab. That shows per-turn patterns at a glance, such as
  a turn's first request missing the cache. Requests outside a turn (the titler, records from
  before requests were tagged with their turn) form one group, **Outside a turn**, placed by its
  newest request. A turn without recorded timing shows its id only.
- Below it, the latest request. On top: model, start time, duration with its phases, and for
  compaction what was compacted. The status shows only when the request is not completed. Completed
  requests add their usage and cost (see below), and **message text by kind**: the estimated share
  (by tiktoken) of system, user, assistant, tool call and tool return text in the messages sent,
  when the request log measured it. It leaves out tool definitions, so it does not split the input
  token count. Failed and interrupted requests show their error here.
- **Instructions** and the collapsed **tool definitions** with their JSON schemas.
- **Messages**, formatted part by part: system, user, text, thinking, tool call (arguments as JSON),
  tool return, retry prompt. Any other part (provider-specific ones included) renders as its JSON.
  Each kind has its own icon and color (the message text bar uses the same colors), and an arrow
  marks whether the message went to the model or came from it. Tool returns and retry prompts
  longer than 12 lines (or 1,500 characters) start as a preview that expands on request.
- The **response**, or a spinner while the request is running.

Instructions, tool descriptions, system and user prompts, text and thinking render as Markdown.
Parameter descriptions stay inside the highlighted JSON schema, since they are part of it. Tool returns and retry
prompts stay verbatim, since they are mostly command output that Markdown would mangle. JSON is
syntax highlighted.

Every message switches between this formatted view and its raw JSON, which shows it as stored,
field for field.

The view opens its own session WebSocket with `observe=true`: it shows no approvals, so it must not
count as presence that suppresses approval notifications. It refetches the open tab's timeline and context whenever
its role sends a notification and after every (re)connect, so it follows a running turn request by
request. A spinner on a tab marks a role
whose request is running.

### Turns tab

In the URL this tab is `&tab=timeline`, the default. `&tab=<role>` opens a role tab instead; `&turn=<turn_id>` picks the turn the timeline shows first.
In the chat, the bubble that ended a turn with a timeline has a debug icon in its footer that opens
`&view=debug&tab=timeline&turn=<turn_id>`: the answer of a successful turn, or the error box of a
failed, budget-stopped or stopped one.

- **Turns**: a list of the session's turns with timing, newest first, one row each: start time,
  the prompt's first characters, a duration bar scaled to the longest turn in the list, and the
  duration. Finished turns are blue, failed and stopped ones take the red and grey of errors and
  interruptions, and running ones grow live. Past a few rows the list gets its own scrollbar. Clicking a row shows its turn. The
  newest turn is shown by default, and new turns are followed live as long as the newest one is
  picked. Turns from before timing was recorded have no timeline.
- **Summary**: wall time, system time, and the time spent waiting for you (approvals, domain
  access, credential release). A stacked bar splits the wall time by category: preparation
  (`turn.prepare`), the agent's LLM requests (until the first token, thinking, output), sentinel
  (gates, sentinel calls and their LLM requests, proxy domain checks), sandbox, skills, exec and
  files, credentials, compaction (with its LLM requests), other (e.g. a tool's own time outside its
  gate and exec), and **not covered**. Each instant of the turn counts once, for the sequential main path: starting at the
  turn, it steps into the running child that started first, level by level, and the instant
  belongs to where that stops, so parallel work never counts twice. Anything inside a `wait` span
  is waiting for you. Instants that stop at the turn itself are not covered: time no span measured.
- **Waterfall**: one row per span, drawn as a tree with guide lines, with its bar placed within the
  turn (on a phone the label sits above the bar). A chevron collapses or expands a row's children;
  that state lasts while the turn is shown. Running spans grow until they end. Errors are red,
  interrupted spans grey, waits hatched. An LLM bar shows its phases: waiting for the first
  token, thinking, output; a phase without its timestamp collapses into its neighbour.
- A row's icon names its kind (hover for the kind and name) in its summary category's color. Its
  text is what the span did: the command of an `exec`, operation and path of a `file`, the domain,
  the tool or step name. Facts follow: the sentinel's verdict as a colored badge; a denied gate, a
  blocked domain or a non-zero exit code in red. An LLM request's output tokens and tokens per
  second of generation (from the first token on) sit in the row's tooltip and its details, so the
  name and a duration up to minutes keep their room.
- A span whose only child covers at least three quarters of it merges with that child into one
  row, and so on down, once both have ended `ok`; running, failed and interrupted spans keep their
  own rows. A gate, its sentinel call and the sentinel's LLM request become one
  `sentinel` row with the verdict. The row shows the head's duration and every member's bar. It is
  named by its first member that isn't a gate, since a gate's name is its tool's. The turn itself
  never merges.
- Clicking a row opens its details, one block per merged span: start (relative to the turn),
  duration, status and attributes. An LLM span adds model, phase durations, tokens, output speed, cache and
  cost, and a link to its role's tab when it is that role's latest request.

The tab refetches the turn list and the shown timeline after every (re)connect and on `span` and
`llm_activity` notifications: the latter move a running LLM request through its phases. A burst of
notifications causes one refetch once it settles (250 ms), and at least one per second while it
lasts.

## What is captured

`LlmRequestLogCapability` (`src/carapace/usage.py`) is attached to every role's pydantic-ai agent. At
the model request boundary, after history processing and compaction, it records an `LlmContext`:

| Field | Content |
| --- | --- |
| `instructions` | pydantic-ai's `instruction_parts` of the request (static and dynamic parts) |
| `messages` | the messages sent, including tool calls and tool returns |
| `tool_definitions` | function tools and output tools offered to the model |
| `response` | the model's `ModelResponse`, once it completed |
| `status`, `error` | see below |
| `compaction_target` | compaction role only: `agent` (model history) or `sentinel` (shadow conversation) |

Everything is stored in pydantic-ai's own serialization, so provider-specific fields (signatures,
`provider_details`, ids) survive as they are. It is not the provider's wire format: the provider
adapter translates these messages into its own request format.

Model settings are not captured.

## Roles and slots

One slot per session and role: `agent`, `sentinel`, `titler` and `compaction`. Each request
overwrites its role's slot (last write wins). The compaction slot is shared by agent and sentinel
compaction; `compaction_target` says which one wrote it. `memory` is not bound to a session and has
no slot.

Slots live in the `session_llm_contexts` table, so they survive restarts, and go away with their
session. A fork starts with empty slots; a rewind leaves them as they are.

## Status

| Status | Meaning |
| --- | --- |
| `running` | the request was sent, no response yet |
| `completed` | `response` is set |
| `failed` | the request failed, `error` holds `ExceptionType: message` |
| `interrupted` | the request was cancelled, e.g. the user stopped the turn |

Two failures reach the request only as a cancellation, so they first land as `interrupted` and are
then marked `failed` through `fail_llm_context(role, error)`:

- **Sentinel timeout**: one timeout covers the sentinel's compaction and its evaluation. It cancels
  whichever request is running, and the sentinel's timeout handler marks that context failed with
  the timeout explanation: the sentinel's own, or the `compaction` slot (`compaction_target:
  sentinel`) when it hit during compaction.
- **Errors of a streamed request**: every role streams (see [Request phases](#request-phases)), and
  pydantic-ai raises provider errors in the stream consumer while it cancels the request. The
  capability's `on_run_error` hook sees the run's actual error and marks the role's context failed
  with it.

`fail_llm_context` only changes a `running` or `interrupted` context. A `completed` one was not cut
by the failure, e.g. when the sentinel times out while it reads a skill file between two requests.

## Request phases

Every request record (and the running request's state) carries the timestamps that split it into
phases:

| Timestamp | Set when |
| --- | --- |
| `started_at` | the request is sent |
| `first_token_at` | the first streamed part of any kind arrives: thinking, text or a tool call (output tools included) |
| `first_thinking_at`, `last_thinking_at` | the first and the latest thinking chunk with content arrive |
| `first_text_at` | the first text chunk with content arrives |
| `completed_at` | the response is complete |

So a request waits for the model from `started_at` to `first_token_at` (queueing, network and
prefill), thinks from `first_thinking_at` to `last_thinking_at`, and produces its output (text or a
tool call) until `completed_at`. A response that is only a tool call has a `first_token_at` but no
`first_text_at`. Records written before `first_token_at` was kept have it `null`.

Reasoning that streams no visible content gets no thinking phase. OpenAI's encrypted reasoning
(Codex models without reasoning summaries) sends nothing until the reasoning is done, so its
reasoning time counts as waiting for the first token. Anthropic's redacted thinking arrives as one
block, so its thinking phase is near zero.

Only a streamed request shows when its parts arrive, so every role streams: the capability's
`on_event` hook records the timestamps, and pydantic-ai streams every run of an agent with such a
hook, with or without an `event_stream_handler`. Streaming changes nothing about the request itself
(instructions, messages and tool definitions are the same), so prefix caching is unaffected.

The usage footer's time to first token and decode rate still measure from `first_text_at`, i.e. to
the first visible answer text.

## API

`GET /api/sessions/{session_id}/llm-contexts/{role}` returns the role's `LlmContext`, or `null`
before the role's first request. It needs the `history` read scope.

The session WebSocket sends a notification on every status change, without the context itself:

```json
{"type": "llm_context", "role": "agent", "request_id": "3f9c0a1b2d4e5f60", "status": "running"}
```

Clients refetch the role's context over REST when they get one.

`GET /api/sessions/{session_id}/llm-requests?role=<role>` returns the session's request log, which
the **Requests** tables show: one `LlmRequestRecord` per request, oldest first, from the `session_llm_requests` log that also
feeds the usage stats. `role` is optional and takes the same roles as the contexts. It needs the
`history` read scope.

A record keeps the numbers of a request, not its context, so the log grows by one small row
per request instead of one full context. Its `outcome` is `completed`; `interrupted` for a request
that was cancelled, e.g. because the turn stopped; or `failed` for one that a provider error or a
sentinel timeout cut short. An unfinished request is recorded when its context turns `interrupted` or
`failed`, before that notification goes out. A streamed request learns of a provider error only as a
cancellation, so its record turns from `interrupted` to `failed` when the run reports the error
(`fail_llm_context`). Token counts are provider-reported: input, output, cache read,
cache write, and reasoning when the provider reports it. A completed record carries the same `cost`
as its context (see [Usage and cost](#usage-and-cost)). Cache counts and the cost are `null` on
records written before they were kept, and the cost on interrupted and failed records.

A failed record has no error message: the error shows only in the role's LLM context, as long as it is
the latest one.

## Usage and cost

A completed request shows its `response.usage` as the provider reported it: input, output, cache
read and cache write tokens, audio tokens when there are any, and the provider-specific `details`
(e.g. reasoning tokens).

Its cost is priced when the response arrives and stored with the context as `cost`
(`request_cost()` in `src/carapace/usage.py`), the same way the usage tracker prices at record time:
`cost_usd` is the actual cost, `equivalent_cost_usd` the list price (see
[sessions-and-channels.md](sessions-and-channels.md#actual-and-equivalent-cost)). Both are null
when the model has no known pricing and the provider reported no cost. `provider_cost_usd` is the
cost the provider reported itself, if it did. Pricing keys on the carapace model id
(`provider:model`) that `model_name` holds, not on the provider's API model name.

Running, failed and interrupted requests have no response, so they show no usage and no cost.

## Timeline

The timeline shows where a turn's time went: one span per step of the turn, nested, with the
turn's LLM requests joined in as bars of their own. It only measures.

### Data model

A **turn** is identified by `turn_id`, a short random hex id generated when the turn starts. The
user event that started it carries the id (`turn_id` on the `user` event), as does the event that
ended it: the assistant event, or the terminal `error` event of a failed or stopped turn. The
history API's messages carry it too, and so do the WebSocket messages that end a turn (`done`,
`cancelled`, and the `error` with `turn_terminal`), which the chat uses to link the turn's last
bubble to its timeline. So does every LLM
request made during it (`turn_id` and `span_id` on `LlmRequestState` and `LlmRequestRecord`: the turn
and the span the request started in). Turns from before timelines existed have no `turn_id` and no
timeline.

A **span** (`Span` in `src/carapace/spans.py`) has the OpenTelemetry shape: `span_id`, `parent_id`,
`kind`, `name`, `started_at`, `ended_at`, `status` and small `attrs` (strings, numbers, booleans;
never full arguments or outputs). Every turn has one root span of kind `turn`, without a parent,
whose `prompt` attr holds the first 60 characters of the user's prompt.

| Status | Meaning |
| --- | --- |
| `running` | the span has not ended yet |
| `ok` | its block completed |
| `error` | its block raised; attr `error` holds the exception type |
| `interrupted` | it was cancelled, or still open when the turn ended |

The root span ends `ok` when the turn completed, `error` when it failed (including budget stops and
unusable models) and `interrupted` when the user stopped it.

Code times a block with the `span()` context manager:

```python
with span("exec", "exec", command=command) as current:
    result = await run(command)
    current.attrs["exit_code"] = result.exit_code
```

A span caps its name and every string attr it starts with at 200 characters (`SPAN_TEXT_MAX`), so
callers pass values as they are, sandbox-controlled ones included.

Its parent is the current span, carried in a contextvar, so spans nest the way the code calls. Its
status follows how the block exits. Outside a running turn `span()` records nothing, so callers never
check. It works on the event-loop thread only: `asyncio.to_thread` copies the contextvar into its
worker, where a span would change the trace off the loop. Wrap the `await asyncio.to_thread(...)`,
never the function running inside it. Code in another task than the turn does not inherit the
contextvar: calls from inside the sandbox enter `attach_sandbox_call` (see
[Sandbox spans](#sandbox-spans)). Only the turn runner calls `attach(trace, parent_id)` directly.

### Storage

Spans of the running turn live in memory, on the `TurnTrace` of the session's `ActiveSession`. When
the turn ends (success, failure or stop) the spans still open are closed as `interrupted` and all of
them are written in one batch to the `session_spans` table. Measuring adds no database I/O to the
measured path. A server crash loses the running turn's spans.

LLM requests are not stored as spans: the timeline joins them from the `session_llm_requests` log
and the requests in flight (`ActiveSession.llm_requests_in_flight`, which holds parallel and
untracked requests too). Spans go away with their session. A fork starts without any, a rewind
keeps them.

### What is timed

| Kind | Name | Covers | Attrs |
| --- | --- | --- | --- |
| `turn` | `turn` | the whole turn | `prompt` |
| `turn.prepare` | `prepare` | resume, memory snapshot, history for the agent model (compaction after a model switch included) | |
| `tool` | tool name | one tool call of the agent or the sentinel, gate and approval hold included (`ToolSpanCapability`) | `deferred` when it waits for approval |
| `gate` | tool name | the security gate of a tool call: safe-list, sentinel | `denied` |
| `sentinel` | evaluation kind | one sentinel evaluation, its compaction and requests included | `subject`, `verdict` |
| `wait` | `approval`, or the escalation's subject | the user's answer: tool approvals, domain, credential and git push escalations | `reason` (`approval`, `domain`, `credential`), `calls` |
| `credential` | vault path | one credential or metadata fetch | `fetch` |
| `spill` | `spill` | saving oversized exec output to the sandbox | `chars` |
| `compaction` | `agent` or `sentinel` | a compaction that runs during the turn (not the checks that skip it) | |

A deferred tool call (`ApprovalRequired`) is control flow, not a failure: its spans end `ok` with
`deferred: true`, and the call runs again as a new `tool` span once the user answered. A git push
escalation waits with reason `approval`. The title is generated after the turn and has no spans.

### Sandbox spans

| Kind | Name | Where | Attrs |
| --- | --- | --- | --- |
| `exec` | `exec` | the `exec` tool's sandbox call | `command` (≤ 200 chars), `exit_code` |
| `exec` | `mcp:<server>` | a stdio MCP bridge call (list or tool call) | `skill`, `mode`, `tool`, `exit_code` |
| `file` | `read`, `write`, `str_replace`, `send_file` | the file tools' sandbox calls | `path` (≤ 200 chars) |
| `sandbox` | `ensure` | a sandbox start, resume or re-attach before a call can run | |
| `sandbox` | `create`, `resume`, `warm claim`, `wait_for_ready`, `knowledge clone`, `hooks`, `proxy setup`, `git identity` | the steps of a start, under `ensure` | `claimed` on `warm claim`, `ready` on `wait_for_ready` |
| `skill` | `activate` | the sandbox skill activator, also when a restart reruns it | `skill`, `exit_code` |
| `skill` | `mcp prewarm` | `use_skill` connecting the skill's MCP servers | `skill` |
| `domain` | the domain (≤ 200 chars) | a proxy domain check | `domain` (≤ 200 chars), `allowed` |

A sandbox that is already running gets no `ensure` span, so the common case adds no row per call.
Warm pool refills run in a fresh context, so the pool's own startups never land in the turn that
triggered them.
The exec span's command is not the MCP bridge's: that one carries the tool arguments.

Calls from inside the sandbox reach the server outside the turn's task: the proxy's domain checks,
the sandbox API (credentials, git) and the pre-receive hook's push evaluation. They enter
`attach_sandbox_call(trace)` (via `SessionEngine.attach_sandbox_call(session_id)`), which nests their
spans under the session's newest running `exec` or `file` span, else under the turn. A call cannot
tell which of several parallel exec calls made it, so the newest one wins. Outside a running turn
they record nothing. A user decision pending in a domain check shows as a `wait` span under its
`domain` span.

### API

Both endpoints need the `history` read scope.

`GET /api/sessions/{session_id}/turns` returns every turn with a timeline, oldest first, the running
one included:

```json
[{"turn_id": "9c1e0a7f", "started_at": "…", "ended_at": "…", "prompt_preview": "Why is the build red?", "status": "ok"}]
```

`status` is the root span's status, `prompt_preview` its `prompt` attr.

`GET /api/sessions/{session_id}/turns/{turn_id}/timeline` returns `{"turn": TurnSummary, "spans":
[Span]}`, the spans ordered by start, 404 for a turn without a timeline. Every span has an `llm`
field, `null` except on `kind == "llm"` spans, which carry the request's phases and numbers:
`role`, `request_id`, `model_name`, `first_token_at`, `first_thinking_at`, `last_thinking_at`,
`first_text_at`, input, output, cache read and cache write tokens, and `cost`. An LLM span's
`span_id` is its `request_id`, its `name` the role. Its status is `ok` for a completed request,
`interrupted` for an interrupted one, `error` for a failed one and `running` for each request in flight.

### WebSocket

The session WebSocket sends a notification whenever a span of the running turn starts or ends, LLM
bars included (their `span_id` is the `request_id`):

```json
{"type": "span", "turn_id": "9c1e0a7f", "span_id": "3f9c0a1b2d4e5f60", "status": "running"}
```

Clients refetch the timeline, and the turn list on a `turn_id` they don't know yet. LLM bars notify
like spans: `running` when their request starts, then `ok`, `interrupted` or `error` (a failed
request) when it ends. A streamed request cut by a provider error first notifies `interrupted`, then
`error` once the run reports the failure.
