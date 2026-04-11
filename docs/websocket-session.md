# WebSocket chat protocol (per session)

This document describes JSON messages on the session chat WebSocket. The canonical Pydantic definitions live in [`src/carapace/ws_models.py`](../src/carapace/ws_models.py).

## Endpoint and authentication

- **URL:** `ws://<host>/api/chat/{session_id}` or `wss://…` for HTTPS deployments.
- **Auth** (either works):
  - Query: `?token=<server bearer token>`
  - Header: `Authorization: Bearer <server bearer token>`

If the token is wrong, the server closes the socket with policy violation (`1008`) before accepting.

If `session_id` does not exist on disk, the server closes with code **4004** and reason `Session not found` before completing the handshake.

## What the web UI does besides WebSocket

The Next.js client loads transcript rows from **REST** (`GET /api/sessions/{session_id}/history`) when opening a session. The WebSocket does **not** replay full history on connect; it only delivers live updates and the handshake described below.

## Fresh connect (server → client, in order)

After `subscribe` succeeds:

1. **`status`** — `StatusUpdate`
   - `agent_running`: whether an agent turn task is still running (e.g. after reconnect).
   - `usage`: last **agent** LLM request stats from the session log (input/output tokens, optional breakdown %, model id, context cap), or `null` if none yet.

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

Empty `content` after trim is ignored. Slash commands (see below) are handled in the WebSocket handler without starting a full agent turn, except `/quit` / `/exit` which close the socket.

## Server → client messages

Each message is one JSON object with a `type` field.

| `type`                           | When                                                | Main fields                                                                                      |
| -------------------------------- | --------------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| `status`                         | On connect                                          | `agent_running`, `usage`                                                                         |
| `token`                          | Streaming assistant text                            | `content`                                                                                        |
| `tool_call`                      | Tool started / security notification                | `tool`, `args`, `detail`; optional `approval_source`, `approval_verdict`, `approval_explanation` |
| `tool_result`                    | Tool finished                                       | `tool`, `result`, `exit_code`                                                                    |
| `approval_request`               | Sentinel escalated a **tool** to the user           | `tool_call_id`, `tool`, `args`, `explanation`, `risk_level`                                      |
| `domain_access_approval_request` | Sentinel escalated **proxy domain** access          | `request_id`, `domain`, `command`                                                                |
| `git_push_approval_request`      | Sentinel escalated **git push**                     | `request_id`, `ref`, `explanation`, `changed_files`                                              |
| `credential_approval_request`    | Sentinel escalated **credential** access            | `request_id`, `vault_paths`, `names`, `descriptions`, optional `skill_name`, `explanation`       |
| `done`                           | Agent turn finished                                 | `content` (final assistant text), optional `usage`                                               |
| `command_result`                 | Slash command or `/verbose` handled                 | `command`, `data` (arbitrary)                                                                    |
| `error`                          | Parse error, unknown command, busy agent, etc.      | `detail`                                                                                         |
| `cancelled`                      | Turn cancelled after `cancel`                       | `detail` (default explains cancellation)                                                         |
| `session_title`                  | Title changed                                       | `title`                                                                                          |
| `user_message`                   | Echo: user line from this client or another channel | `content`                                                                                        |

### `tool_call` variants

The same envelope is used for normal agent tools and for security-side notifications. Examples:

- Regular tools: `tool` matches the agent tool name (`read`, `exec`, `use_skill`, …).
- Domain decisions: `tool` is `proxy_domain`, `args` includes `domain`.
- Git push summary: `tool` is `git_push`.
- Credential decision summary: `tool` is `credential_access`, `args` includes `vault_path`.

Exact args depend on the producer; see `WebSocketSubscriber` in [`src/carapace/server.py`](../src/carapace/server.py).

### `approval_source` / `approval_verdict` (on `tool_call`)

When present:

- `approval_source`: `safe-list` \| `sentinel` \| `user` \| `unknown`
- `approval_verdict`: `allow` \| `deny` \| `escalate`

## Typical turn flow (server → client)

1. Optional: `user_message` (if echoed).
2. Many `token` chunks (streaming).
3. Interleaved `tool_call` / `tool_result` pairs while tools run.
4. Possible: `approval_request` or escalation requests — client must respond; turn stays blocked until then.
5. `done` with final text and optional `usage`.

## Reconnect behaviour

- Pending **tool** approvals and **escalations** are **re-sent** on every new subscription so a refreshed browser can answer them.
- Ongoing streaming and tool events only arrive while connected; there is no backfill of missed `token` chunks over the socket (rely on history API for past transcript).

## Related code

| Piece                          | Location                                                    |
| ------------------------------ | ----------------------------------------------------------- |
| Message models & parser        | `src/carapace/ws_models.py`                                 |
| WebSocket route & handshake    | `src/carapace/server.py` (`chat_ws`, `WebSocketSubscriber`) |
| Broadcasts from session engine | `src/carapace/session/engine.py`                            |
| Frontend types                 | `frontend/src/lib/types.ts`                                 |
