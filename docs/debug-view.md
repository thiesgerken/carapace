# Debug View

The debug view shows, per session and live, the latest **LLM context** of every agent role: exactly
what went to the model in its last request, and what came back. Terms follow
[GLOSSARY.md](../GLOSSARY.md).

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

- **Sentinel timeout**: the timeout cancels the evaluation; the sentinel's timeout handler marks its
  context failed with the timeout explanation.
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

## Input tokens

The total input tokens of a request are the provider-reported `response.usage.input_tokens`. Running,
failed and interrupted requests have no response, so they show no total.
