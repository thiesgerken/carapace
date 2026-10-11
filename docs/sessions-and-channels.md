# Sessions and Channels

Sessions are the core abstraction in carapace. They are decoupled from any specific channel — a session is a conversation context with its own security state. Channels create and interact with sessions, but don't own them.

## Session model

Each session has a `SessionState` stored on disk:

```python
class SessionState(BaseModel):
    session_id: str
    channel_type: str           # "cli" | "matrix" | "web" | ...
    channel_ref: str | None     # channel-specific ID (room_id, etc.)
    title: str | None           # auto-generated after first messages
    agent_model_name: str | None
    sentinel_model_name: str | None
    title_model_name: str | None
  attributes: SessionAttributes  # private / archived / pinned / favorite / unattended / ask_mode / yolo_mode
    approved_operations: list[str]
    activated_skills: list[str]
    context_grants: dict[str, ContextGrant]  # per-skill domain & credential grants
    budget: SessionBudget
    created_at: datetime
    last_active: datetime
  latest_job_run: SessionJobRunContext | None
    knowledge_last_committed_at: datetime | None
    knowledge_last_archive_path: str | None
    knowledge_last_export_hash: str | None
    knowledge_last_commit_trigger: str | None
```

Each session also has an `ActiveSession` in-memory object (when loaded) that holds:

- `SessionSecurity` — action log, audit trail, sentinel evaluation count
- `Sentinel` — LLM sentinel agent with shadow conversation
- `UsageTracker` — token usage with cost tracking
- Subscriber list — connected WebSocket/Matrix clients
- Approval queues — for tool and proxy domain approvals

## Session persistence

Sessions are stored on disk at `$CARAPACE_DATA_DIR/sessions/<session_id>/`:

| File           | Contents                                                                                                  |
| -------------- | --------------------------------------------------------------------------------------------------------- |
| `state.yaml`   | Session metadata (SessionState)                                                                           |
| `history.yaml` | Raw Pydantic AI message history used as model conversation state                                          |
| `events.yaml`  | User-facing session transcript and event stream (messages, tool calls/results, approvals, slash commands) |
| `usage.yaml`   | Token usage breakdown by model                                                                            |
| `audit.yaml`   | Security audit trail (sentinel verdicts, decisions)                                                       |

Sessions persist across server restarts. In-memory state (action log, sentinel conversation) is rebuilt when a session is reactivated.

`history.yaml` and `events.yaml` serve different purposes:

- `history.yaml` stores the full `ModelMessage` sequence that is fed back into Pydantic AI on the next turn. This is the model-side conversation state.
- `events.yaml` stores the normalized session transcript used by the UI and APIs. It includes items that do not belong in model history, such as slash commands, approval requests/responses, and other operational events.
- The REST history endpoint reads `events.yaml` as the user-facing transcript source.
- Retry, reset, fork, and knowledge export align both files by completed turns, but they do not collapse them into a single source of truth.

## Knowledge commits

carapace can optionally commit session histories into the Git-backed knowledge repository. This is a secondary persistence path for long-term recall, not the primary runtime store.

- The canonical committed artifact is `conversation.json`
- Session snapshots are written under `<knowledge_dir>/sessions/YYYY/MM/<session_id>/conversation.json` by default
- The payload is built from the normalized session event log, so it includes user messages, assistant replies, tool calls, tool results, approvals, and event timestamps
- Existing sessions continue to live primarily under `$CARAPACE_DATA_DIR/sessions/<session_id>/`

### Privacy model

- Every session has an `attributes.private` flag in `SessionState`
- New sessions start public unless the caller explicitly sets them private
- Private sessions are excluded from manual commits to knowledge and from autosave commits
- Switching a session from public to private does **not** rewrite Git history; already-committed snapshots remain in the knowledge repo history

### Save triggers

- **Manual**: the web UI exposes a "Commit to knowledge" action for public sessions
- **Automatic**: when `sessions.commit.autosave_enabled` is true, the server periodically checks for inactive public sessions and commits them after `sessions.commit.autosave_inactivity_hours`
- **Deletion**: if `sessions.commit.delete_from_knowledge_on_session_delete` is true, deleting a session also removes its current committed snapshot path from the knowledge repo and records that as a Git commit

## Session lifecycle

- Sessions are **persistent** — they survive carapace restarts
- **Containers** are ephemeral: destroyed after an idle timeout (configurable, default 60 min). When the user sends a new message after containers expire, they are recreated. See [sandbox.md](sandbox.md).
- **Title generation**: After the 1st and 3rd user messages, a title is auto-generated using a lightweight LLM model
- **Privacy**: Sessions start public by default unless the creator explicitly marks them private
- **Deletion**: Sessions can be deleted via the REST API (`DELETE /api/sessions/{id}`), which also cleans up any running sandbox container and may remove the committed `conversation.json` from the knowledge repo

## Session modes and controls

`SessionAttributes` carry more than privacy state:

- `private` excludes the session from knowledge commits
- `archived` hides the session from the default active list and tears down its sandbox when archiving succeeds
- `pinned` and `favorite` are UI-facing organization flags
- `unattended` creates a session without a user approval path
- `ask_mode` keeps sentinel review enabled while restricting the agent to read-only operations outside the sandbox
- `yolo_mode` bypasses sentinel review entirely

Important behavior:

- `ask_mode` and `yolo_mode` are mutually exclusive
- `unattended` cannot be changed in place; fork the session if you want a different approval mode
- archived sessions are hidden from the default session list but can still be listed explicitly through the API and shown in the web UI

The web UI also exposes turn-level controls on completed assistant turns:

- **Retry latest turn** reruns the latest completed turn from its user prompt boundary
- **Reset to turn** rewinds the session to an earlier completed turn boundary
- **Fork** creates a new session from a chosen event boundary

Retry and reset are WebSocket actions; fork is a REST action.

## Jobs and job-linked sessions

Jobs are now a built-in feature. They can create fresh job sessions or reuse a persistent attended session, and the resulting session records the latest job run metadata in `latest_job_run`.

See [jobs.md](jobs.md) for the job definition format, scheduler behavior, and REST API.

## Notifications and presence

carapace also keeps a separate notification state for each session. This state is not part of `SessionState`; it lives in a dedicated notification store plus a runtime presence registry.

See [notifications.md](notifications.md) for the full backend model, config, delivery, and API details.

Short version:

- subscriptions live under `$CARAPACE_DATA_DIR/notifications/subscriptions/`
- delivery is filtered by per-device preferences and suppressed while a session is actively handled
- active handling is driven by shared web, CLI, and Matrix presence
- pending notifications are cleared again when the user returns to the session

---

## Channel system

Channels are adapters that connect external systems to carapace sessions. They implement the `SessionSubscriber` protocol, which defines callbacks for receiving streamed tokens, tool call info, approval requests, and other events.

### Web Frontend (WebSocket)

The primary interactive channel. A Next.js web app connects to the carapace server via WebSocket.

**REST API:**

| Endpoint                              | Method   | Description                                                                    |
| ------------------------------------- | -------- | ------------------------------------------------------------------------------ |
| `/api/sessions`                       | `POST`   | Create a new session                                                           |
| `/api/sessions`                       | `GET`    | List sessions (`include_archived`, `include_message_count`, `limit`, `cursor`) |
| `/api/sessions/{id}`                  | `GET`    | Get session details                                                            |
| `/api/sessions/{id}`                  | `PATCH`  | Update session attributes and model overrides                                  |
| `/api/sessions/{id}/fork`             | `POST`   | Fork a session from a chosen event boundary                                    |
| `/api/sessions/{id}`                  | `DELETE` | Delete session + cleanup sandbox                                               |
| `/api/sessions/{id}/knowledge/commit` | `POST`   | Commit the session snapshot into the knowledge repo                            |
| `/api/sessions/{id}/history`          | `GET`    | Get chat history (optional `limit` param)                                      |
| `/api/sessions/{id}/sandbox`          | `GET`    | Get sandbox status and storage snapshot                                        |
| `/api/sessions/{id}/sandbox/up`       | `POST`   | Start or warm the sandbox                                                      |
| `/api/sessions/{id}/sandbox/down`     | `POST`   | Stop or scale down the sandbox                                                 |
| `/api/sessions/{id}/sandbox/wipe`     | `POST`   | Destroy sandbox workspace state and start fresh later                          |

**Notification API:**

| Endpoint                                            | Method   | Description                                                                      |
| --------------------------------------------------- | -------- | -------------------------------------------------------------------------------- |
| `/api/notifications/subscriptions`                  | `GET`    | List current subscriptions for the authenticated owner key                       |
| `/api/notifications/subscriptions`                  | `POST`   | Create or update a push subscription                                             |
| `/api/notifications/subscriptions/{id}`             | `DELETE` | Remove a push subscription                                                       |
| `/api/notifications/subscriptions/{id}/preferences` | `PATCH`  | Update per-device notification preferences                                       |
| `/api/notifications/subscriptions/{id}/test`        | `POST`   | Send a test notification to one subscription                                     |
| `/api/notifications/subscriptions/{id}/presence`    | `POST`   | Update presence for a subscription-backed client and refresh expiry              |
| `/api/notifications/presence`                       | `POST`   | Update interactive presence for clients that are not tied to a push subscription |

**Other useful REST endpoints:**

| Endpoint        | Method         | Description                                               |
| --------------- | -------------- | --------------------------------------------------------- |
| `/api/commands` | `GET`          | Return the slash-command catalog advertised by the server |
| `/api/models`   | `GET`          | Return the configured model catalog                       |
| `/api/meta`     | `GET`          | Return server metadata such as version                    |
| `/api/jobs`     | `GET` / `POST` | List or create jobs                                       |

**WebSocket protocol** (`/api/chat/{session_id}`):

Message `type` values, JSON fields, authentication, and what the server sends on a **fresh connect** (including replay of pending approvals and escalations) are documented in **[websocket-session.md](websocket-session.md)**.

Authentication uses the `carapace_session` cookie issued by `POST /api/auth/login`. The optional WebSocket query parameter is only `client_id`, used to keep interactive presence stable across reconnects.

For presence tracking, the frontend also posts REST heartbeats and may attach a stable `client_id` query parameter to the WebSocket so reconnects map back to the same interactive client.

### Matrix Channel

Connects carapace to Matrix rooms using [matrix-nio](https://github.com/matrix-nio/matrix-nio). One session per room.

Features:

- Reactions for quick approvals (✅ to approve, ❌ to deny)
- Slash commands for session control (including `/reset`)
- Per-room session mapping
- Configurable allowed rooms and users
- Matrix activity feeds the same active-session presence registry used for notification suppression and clearing

Configuration is per user, under `config.channels.matrix` in the user record:

```yaml
channels:
  matrix:
    enabled: true
    homeserver: https://matrix.example.com
    user_id: "@carapace:example.com"
    device_name: carapace
    allowed_rooms: []
    allowed_users:
      - "@me:example.com"
```

> **Note**: The Matrix channel currently uses plain-text messaging (no E2EE). See [plans/channels.md](plans/channels.md) for E2EE plans.

---

## Slash commands

Slash commands are the user's control interface for managing sessions. Interactive channels share most commands, with a few transport-specific exceptions.

### Common interactive commands

| Command                                         | Effect                                                         |
| ----------------------------------------------- | -------------------------------------------------------------- |
| `/help`                                         | Show available commands                                        |
| `/session`                                      | Show session metadata, context grants, and domain allowlist    |
| `/skills`                                       | List available skills                                          |
| `/retitle`                                      | Regenerate session title, or set it explicitly                 |
| `/budget`                                       | Show or update session budgets, including tool-call caps       |
| `/usage`                                        | Show token usage breakdown with cost estimates                 |
| `/pull`                                         | Pull from external Git remote (if configured)                  |
| `/push`                                         | Push to external Git remote (if configured)                    |
| `/reload`                                       | Reset sandbox — destroy container + workspace, fresh git clone |
| `/models`                                       | View all models (agent, sentinel, title) and available options |
| `/model [NAME\|reset]`                          | View or switch all models together                             |
| `/model [agent\|sentinel\|title] [NAME\|reset]` | View or switch one model role                                  |

### WebSocket-only commands

| Command           | Effect                     |
| ----------------- | -------------------------- |
| `/quit` / `/exit` | Close WebSocket chat       |
| `/quit` / `/exit` | Close WebSocket connection |

The WebSocket protocol also supports non-slash turn controls for retry and reset. See [websocket-session.md](websocket-session.md).

### Matrix-only commands

| Command             | Effect                                                                          |
| ------------------- | ------------------------------------------------------------------------------- |
| `/reset`            | Create a new session for the room (clears history, credentials, security state) |
| `/allow` / `/yes`   | Approve the pending operation (alternative to ✅ reaction)                      |
| `/deny` / `/no`     | Deny the pending operation (alternative to ❌ reaction)                         |
| `/stop` / `/cancel` | Cancel the running agent turn                                                   |
| `/verbose`          | Toggle tool call display in the room                                            |

---

## Approval gate

The approval gate handles security escalations. When the sentinel escalates a tool call, the flow is:

1. Agent loop receives `DeferredToolRequests` (tools that need approval)
2. `ApprovalRequest` is broadcast to all session subscribers (WebSocket clients, Matrix rooms)
3. The request includes the sentinel's explanation, risk level, tool name, and arguments
4. Agent loop blocks waiting on the approval queue
5. User approves or denies via the frontend UI, reaction, or slash command
6. `ApprovalResponse` is routed back through the approval queue
7. Agent resumes with the approved tools (denied tools receive a `ToolDenied` message)

### Proxy domain approvals

A separate approval flow handles domain requests from sandbox containers:

1. Sandbox container makes an outbound request through the proxy
2. Proxy checks the domain against the session's allowlist
3. If unknown, proxy calls the sentinel via the security module
4. If sentinel escalates, a `ProxyApprovalRequest` is sent to subscribers
5. User decides (allow/deny)
6. Decision is applied and the proxy responds

### Unanswered requests

An approval request (tool, domain access, git push, or credential) can only be answered while the turn that raised it is still running. When a turn ends with a request still open (cancelled, failed, or completed while an escalation was pending), carapace closes it before the turn's final assistant message: it appends the regular response event with `decision` `denied` (tool) or `deny` (escalation), `decision_source: "system"`, and the message "Turn ended before a decision was made." Any escalation callback still blocked on the request is released with a denial.

A server restart kills turns without that cleanup, so the server closes such leftover requests in the same way at startup, before any session is activated. Clients therefore never see an actionable request that nothing waits for anymore.
