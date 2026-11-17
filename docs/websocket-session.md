# WebSocket chat protocol (per session)

This document describes JSON messages on the session chat WebSocket. The canonical Pydantic definitions live in [`src/carapace/ws_models.py`](../src/carapace/ws_models.py).

For the broader notification backend, including presence, suppression, and push delivery, see [notifications.md](notifications.md).

## Endpoint and authentication

- **URL:** `ws://<host>/api/chat/{session_id}` or `wss://…` for HTTPS deployments.
- Optional query parameter: `client_id=<stable-client-id>` to let reconnects map to the same interactive presence source.
- Optional query parameter: `observe=true` for a connection that only watches the session (the [debug view](debug-view.md)). It registers no presence, so it never suppresses notifications.
- **Auth:** the same `carapace_session` HttpOnly cookie issued by `POST /api/auth/login` for the web UI and CLI.

If the cookie is missing, expired, revoked, or belongs to a different user than the session owner, the server closes the socket with policy violation (`1008`) before accepting.

If `session_id` does not exist on disk, the server closes with code **4004** and reason `Session not found` before completing the handshake.

## What the web UI does besides WebSocket

The Next.js client loads transcript rows from **REST** (`GET /api/sessions/{session_id}/history`) when opening a session. The WebSocket does **not** replay full history on connect; it only delivers live updates and the handshake described below.

For notification suppression and clearing, the web client also updates the shared presence registry:

- `POST /api/notifications/presence` with `session_id`, `source_id`, `client_type`, and `focus_state`
- periodic keepalive heartbeats while the session stays open
- websocket connect and disconnect also mark presence active/inactive using the same `client_id` when provided, except for `observe=true` connections

There is currently no separate WebSocket `presence_update` message type. Presence is tracked out-of-band through the notification REST API plus websocket lifecycle hooks.

## Fresh connect (server → client, in order)

After `subscribe` succeeds:

1. **`status`** — `StatusUpdate`
   - `agent_running`: whether an agent turn task is still running (e.g. after reconnect).
   - `usage`: last **agent** LLM request stats from the session log (input/output tokens, optional breakdown %, model id, context cap), or `null` if none yet.
   - `llm_activity`: current in-flight LLM activity metadata, if a request is active.
   - `budget`: the session's budget limits (`input_tokens`, `output_tokens`, `cost_usd`, `equivalent_cost_usd`, `tool_calls`, `autonomous_tool_calls`; `null` means no limit). The same message is broadcast after every budget change.

2. **Pending tool approvals (zero or more)** — for each entry in `active.pending_approval_requests`:
   - `approval_request`

3. **Pending escalations (zero or more)** — for each entry in `active.pending_escalations`:
   - `git_push_approval_request` if `kind == "git_push"`
   - `credential_approval_request` if `kind == "credential_access"`
   - otherwise `domain_access_approval_request` (domain / proxy escalation)

Then the server waits for **client** JSON messages. If an agent turn was already in progress, new subscribers keep receiving **broadcast** events (`token`, `tool_call`, etc.) as they occur.

## Client → server messages

All messages are JSON objects with a `type` field. Invalid types or bodies yield an `error` response and the read loop continues.

| `type`                | Purpose                                                | Fields                                           |
| --------------------- | ------------------------------------------------------ | ------------------------------------------------ |
| `message`             | User text; starts an agent turn if not a slash command | `content` (string)                               |
| `approval_response`   | Answer to `approval_request`                           | `tool_call_id`, `approved` (bool)                |
| `escalation_response` | Answer to domain / git-push / credential escalation    | `request_id`, `decision` (`"allow"` \| `"deny"`) |
| `cancel`              | Cancel the in-flight agent turn                        | (none)                                           |
| `retry_latest_turn`   | Rewind the latest completed turn and run it again      | (none)                                           |
| `reset_to_turn`       | Rewind the session to a completed turn boundary        | `event_index`                                    |

Empty `content` after trim is ignored. Slash commands (see below) are handled in the WebSocket handler without starting a full agent turn, except `/quit` / `/exit` which close the socket.

## Server → client messages

Each message is one JSON object with a `type` field.

| `type`                           | When                                                | Main fields                                                                                      |
| -------------------------------- | --------------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| `status`                         | On connect and after a session budget change        | `agent_running`, `usage`, `llm_activity`, `budget`                                               |
| `llm_activity`                   | LLM request phase changed, or its output grew       | `activity` or `null`                                                                             |
| `token`                          | Streaming assistant text                            | `content`                                                                                        |
| `thinking`                       | Streaming reasoning text                            | `content`                                                                                        |
| `tool_call_start`                | Agent model started writing a tool call             | `tool_call_id`, `tool` (see [Streaming tool calls](#streaming-tool-calls))                       |
| `tool_call_delta`                | Next piece of that call's args                      | `tool_call_id`, `args_delta` (raw JSON text, append in order)                                    |
| `tool_call_end`                  | Model stopped writing the call                      | `tool_call_id`, `aborted`                                                                        |
| `tool_call`                      | Tool started / security notification                | `tool`, `args`, `detail`; optional `approval_source`, `approval_verdict`, `approval_explanation` |
| `tool_result`                    | Tool finished                                       | `tool`, `result`, `exit_code`                                                                    |
| `approval_request`               | Sentinel escalated a **tool** to the user           | `tool_call_id`, `tool`, `args`, `explanation`, `risk_level`                                      |
| `domain_access_approval_request` | Sentinel escalated **proxy domain** access          | `request_id`, `domain`, `command`                                                                |
| `git_push_approval_request`      | Sentinel escalated **git push**                     | `request_id`, `ref`, `explanation`, `changed_files`                                              |
| `credential_approval_request`    | Sentinel escalated **credential** access            | `request_id`, `vault_paths`, `names`, `descriptions`, optional `skill_name`, `explanation`       |
| `done`                           | Agent turn finished                                 | `content` (final assistant text), `turn_id`, optional `usage`, optional `final_status`           |
| `command_result`                 | Slash command or turn-control acknowledgement       | `command`, `data` (arbitrary)                                                                    |
| `error`                          | Parse error, unknown command, busy agent, etc.      | `detail`, `turn_terminal`; on the error that ended a turn also its `turn_id`                     |
| `cancelled`                      | Turn cancelled after `cancel`                       | `detail` (default explains cancellation), `turn_id`                                              |
| `session_title`                  | Title changed                                       | `title`                                                                                          |
| `span`                           | A span of the running turn started or ended         | `turn_id`, `span_id`, `status`; LLM bars included (see [debug-view.md](debug-view.md#websocket)) |
| `user_message`                   | Echo: user line from this client or another channel | `content`                                                                                        |

### `llm_activity`

`activity` describes the session's current LLM request (`null` once it ends):

- `phase`: `processing_prompt` until the first token, then `thinking`, `generating` (answer text) or
  `tool_call` (the model is writing a tool call's arguments, `tool_name` names the tool).
- `started_at` and the phase timestamps (`first_thinking_at`, `last_thinking_at`, `first_text_at`).
- `streamed_chars`: characters of thinking, text and tool-call arguments streamed so far. The web UI
  shows a quarter of it as approximate output tokens; the provider's count only arrives with the
  request's record once the response is complete.

A phase change is sent right away. Growth of `streamed_chars` alone is sent at most every 0.3 s, so a
long tool call streams a live counter without one message per chunk. Clients tick the elapsed time
themselves from `started_at`.

### `tool_call` variants

The same envelope is used for normal agent tools and for security-side notifications. Examples:

- Regular tools: `tool` matches the agent tool name (`read`, `exec`, `use_skill`, …).
- Domain decisions: `tool` is `proxy_domain`, `args` includes `domain`.
- Git push summary: `tool` is `git_push`.
- Credential decision summary: `tool` is `credential_access`, `args` includes `vault_path`.

Exact args depend on the producer; see `WebSocketSubscriber` in [`src/carapace/server/websocket.py`](../src/carapace/server/websocket.py).

`tool_call` and `tool_result` may also include stable `tool_id` values, and nested tool calls include `parent_tool_id` so the frontend can render tool trees. Calls the agent model made also carry the model's `tool_call_id` (the one the streaming messages below use); it is `null` for calls the model did not make, such as `proxy_domain`.

### Streaming tool calls

While the agent model writes a tool call, the client sees it before it runs:

1. `tool_call_start` as soon as the model starts the call.
2. `tool_call_delta` with the args text written since the previous delta, at most about ten per second and call. Concatenated, the deltas are the call's JSON args; parsing the partial JSON is up to the client. Providers that hand over args as an object send them as one delta at the end.
3. `tool_call_end`. `aborted: false` means the args are complete: the call goes to the security gate and shows up as `tool_call` (later `tool_result`) with the same `tool_call_id`, or as an `approval_request`, whose `tool_call_id` is that id too. `aborted: true` means the request was cancelled or failed while the call was still being written; the turn's `cancelled` or `error` follows.

Parallel calls in one response each stream under their own `tool_call_id`. Some OpenAI-compatible servers reuse ids (`call_0`) across responses, so a `tool_call_start` with an id the client has already seen starts a new card, and later messages with that id belong to the newest one. A provider that sends a call's id only after its name streams it under a stand-in id the executed call does not carry; the server logs a warning, and the card ends up "not run" next to the real call. A finished call can still never run, for instance when its args fail validation, so a client should drop a card still waiting for its `tool_call` when the turn ends. `list_skills` sends no `tool_call`, only its `tool_result`. Only the agent role streams calls; sentinel, titler and compaction requests do not. Nothing of this is persisted: history only has the executed call, and a client that connects mid-call sees it from its `tool_call` on.

### `approval_source` / `approval_verdict` (on `tool_call`)

When present:

- `approval_source`: `safe-list` \| `sentinel` \| `user` \| `skill` \| `bypass` \| `unknown`
- `approval_verdict`: `allow` \| `revise` \| `deny` \| `escalate`

**`skill`** — the action was allowed because it's covered by a context grant from an activated skill (e.g., domain access or credential fetch within a matching `contexts` exec).

**`bypass`** — the action was silently allowed without sentinel evaluation (e.g., proxy bypass during sandbox-provided skill activation).

## Turn-control messages

Two client message types are not slash commands but explicit UI controls:

- `retry_latest_turn` rewinds to the latest completed user-turn boundary and reruns it.
- `reset_to_turn` rewinds the session to a specific completed turn boundary identified by `event_index`.

Both controls operate on the normalized event log used by `/api/sessions/{session_id}/history`.

## Typical turn flow (server → client)

1. Optional: `user_message` (if echoed).
2. `llm_activity` and optional `thinking` chunks while the model is working.
3. Many `token` chunks (streaming).
4. `tool_call_start` / `tool_call_delta` / `tool_call_end` while the model writes a tool call, then interleaved `tool_call` / `tool_result` pairs while tools run.
5. Possible: `approval_request` or escalation requests — client must respond; turn stays blocked until then. If the turn ends first (cancel, failure, restart), the server records a system denial for the request instead (see [sessions-and-channels.md](sessions-and-channels.md#unanswered-requests)).
6. `done` with final text and optional `usage`.

## Reconnect behaviour

- Pending **tool** approvals and **escalations** are **re-sent** on every new subscription so a refreshed browser can answer them.
- Ongoing streaming and tool events only arrive while connected; there is no backfill of missed `token` chunks over the socket (rely on history API for past transcript).
- A reconnect with the same `client_id` marks the session active again in the presence registry, which can clear any pending push notifications for that session.

## Related code

| Piece                          | Location                                                              |
| ------------------------------ | --------------------------------------------------------------------- |
| Message models & parser        | `src/carapace/ws_models.py`                                           |
| WebSocket route & handshake    | `src/carapace/server/websocket.py` (`chat_ws`, `WebSocketSubscriber`) |
| Broadcasts from session engine | `src/carapace/session/engine.py`                                      |
| Frontend types                 | `frontend/src/lib/types.ts`                                           |
