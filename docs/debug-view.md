# Debug View

The debug view shows, per session and live, the latest **LLM context** of every agent role: exactly
what went to the model in its last request, and what came back. Terms follow
[GLOSSARY.md](../GLOSSARY.md).

## Using it

The **Chat | Debug** switch in the session header opens `/?session=<ID>&view=debug`. One tab per role
shows its request timeline and its latest request:

- **Requests**: one row per recorded request of the role, newest first, so requests compare side by
  side: time, status, input, cache read, cache write, output and reasoning tokens, cache hits (cache
  read ÷ input), actual and equivalent cost, duration and model. `–` marks a value the record does
  not have. The row of the request shown below is highlighted, and its time links to it. Only the
  latest request keeps its context, so older rows have numbers only.
- Below it, the latest request. On top: status, model, start time, and for compaction what was compacted. Completed requests add
  their usage and cost (see below). Failed and interrupted requests show their error here.
- **Instructions** and the collapsed **tool definitions** with their JSON schemas.
- **Messages**, formatted part by part: system, user, text, thinking, tool call (arguments as JSON),
  tool return, retry prompt. Any other part (provider-specific ones included) renders as its JSON.
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
- **Agent errors mid-stream**: the agent streams, and pydantic-ai raises provider errors in the
  stream consumer while it cancels the request; the turn's error path marks the agent's context
  failed with that error.

`fail_llm_context` only changes a `running` or `interrupted` context. A `completed` one was not cut
by the failure, e.g. when the sentinel times out while it reads a skill file between two requests.

## API

`GET /api/sessions/{session_id}/llm-contexts/{role}` returns the role's `LlmContext`, or `null`
before the role's first request. It needs the `history` read scope.

The session WebSocket sends a notification on every status change, without the context itself:

```json
{"type": "llm_context", "role": "agent", "request_id": "3f9c0a1b2d4e5f60", "status": "running"}
```

Clients refetch the role's context over REST when they get one.

`GET /api/sessions/{session_id}/llm-requests?role=<role>` returns the session's request timeline:
one `LlmRequestRecord` per request, oldest first, from the `session_llm_requests` log that also
feeds the usage stats. `role` is optional and takes the same roles as the contexts. It needs the
`history` read scope.

A record keeps the numbers of a request, not its context, so the timeline grows by one small row
per request instead of one full context. Its `outcome` is `completed`, or `interrupted` for a request
cut short when the turn stopped. Token counts are provider-reported: input, output, cache read,
cache write, and reasoning when the provider reports it. A completed record carries the same `cost`
as its context (see [Usage and cost](#usage-and-cost)). Cache counts and the cost are `null` on
records written before they were kept, and the cost on interrupted records.

A stopped turn saves its interrupted record after the context's notification went out, so the view
also refetches the timeline when the session's LLM activity ends.

Failed requests leave no record, so the timeline has no row for them. Their error shows only in the
role's LLM context, as long as it is the latest one.

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
