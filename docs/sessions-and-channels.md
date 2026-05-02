# Sessions and Channels

Sessions are the core abstraction in Carapace. They are decoupled from any specific channel — a session is a conversation context with its own security state. Channels create and interact with sessions, but don't own them.

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
    attributes: SessionAttributes  # private / archived / pinned / favourite
    approved_operations: list[str]
    activated_skills: list[str]
    context_grants: dict[str, ContextGrant]  # per-skill domain & credential grants
    budget: SessionBudget
    created_at: datetime
    last_active: datetime
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
- The REST history endpoint prefers `events.yaml` and only falls back to rebuilding a simplified transcript from `history.yaml` for legacy sessions.
- Retry, reset, fork, and knowledge export align both files by completed turns, but they do not collapse them into a single source of truth.

## Knowledge commits

Carapace can optionally commit session histories into the Git-backed knowledge repository. This is a secondary persistence path for long-term recall, not the primary runtime store.

- The canonical committed artifact is `conversation.json`
- Session snapshots are written under `<knowledge_dir>/sessions/YYYY/MM/<session_id>/conversation.json` by default
- The payload is built from the normalized session event log, so it includes user messages, assistant replies, tool calls, tool results, approvals, and event timestamps
- Existing sessions continue to live primarily under `$CARAPACE_DATA_DIR/sessions/<session_id>/`

### Privacy model

- Every session has an `attributes.private` flag in `SessionState`
- New sessions inherit `sessions.default_private` from `config.yaml`
- Private sessions are excluded from manual commits to knowledge and from autosave commits
- Switching a session from public to private does **not** rewrite Git history; already-committed snapshots remain in the knowledge repo history

### Save triggers

- **Manual**: the web UI exposes a "Commit to knowledge" action for public sessions
- **Automatic**: when `sessions.commit.autosave_enabled` is true, the server periodically checks for inactive public sessions and commits them after `sessions.commit.autosave_inactivity_hours`
- **Deletion**: if `sessions.commit.delete_from_knowledge_on_session_delete` is true, deleting a session also removes its current committed snapshot path from the knowledge repo and records that as a Git commit

## Session lifecycle

- Sessions are **persistent** — they survive Carapace restarts
- **Containers** are ephemeral: destroyed after an idle timeout (configurable, default 15 min). When the user sends a new message after containers expire, they are recreated. See [sandbox.md](sandbox.md).
- **Title generation**: After the 1st and 3rd user messages, a title is auto-generated using a lightweight LLM model
- **Privacy**: Sessions start public by default, unless `sessions.default_private` is set to `true`
- **Deletion**: Sessions can be deleted via the REST API (`DELETE /api/sessions/{id}`), which also cleans up any running sandbox container and may remove the committed `conversation.json` from the knowledge repo

---

## Channel system

Channels are adapters that connect external systems to Carapace sessions. They implement the `SessionSubscriber` protocol, which defines callbacks for receiving streamed tokens, tool call info, approval requests, and other events.

### Web Frontend (WebSocket)

The primary interactive channel. A Next.js web app connects to the Carapace server via WebSocket.

**REST API:**

| Endpoint                              | Method   | Description                                         |
| ------------------------------------- | -------- | --------------------------------------------------- |
| `/api/sessions`                       | `POST`   | Create a new session                                |
| `/api/sessions`                       | `GET`    | List all sessions                                   |
| `/api/sessions/{id}`                  | `GET`    | Get session details                                 |
| `/api/sessions/{id}`                  | `PATCH`  | Update session metadata (currently `private`)       |
| `/api/sessions/{id}`                  | `DELETE` | Delete session + cleanup sandbox                    |
| `/api/sessions/{id}/knowledge/commit` | `POST`   | Commit the session snapshot into the knowledge repo |
| `/api/sessions/{id}/history`          | `GET`    | Get chat history (optional `limit` param)           |

**WebSocket protocol** (`/api/chat/{session_id}`):

Message `type` values, JSON fields, authentication, and what the server sends on a **fresh connect** (including replay of pending approvals and escalations) are documented in **[websocket-session.md](websocket-session.md)**.

Authentication uses a bearer token (`CARAPACE_TOKEN` env var) passed as a query parameter or `Authorization: Bearer` header.

### Matrix Channel

Connects Carapace to Matrix rooms using [matrix-nio](https://github.com/matrix-nio/matrix-nio). One session per room.

Features:

- Reactions for quick approvals (✅ to approve, ❌ to deny)
- Slash commands for session control (including `/reset`)
- Per-room session mapping
- Configurable allowed rooms and users

Configuration in `config.yaml`:

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

> **Future plans**: Task scheduling via cron/heartbeat, with cross-channel approval routing for non-interactive sessions. See [plans/channels.md](plans/channels.md).

---

## Slash commands

Slash commands are the user's control interface for managing sessions and security. Both the WebSocket and Matrix channels support them.

### Common commands (both channels)

| Command            | Effect                                                                         |
| ------------------ | ------------------------------------------------------------------------------ |
| `/help`            | Show available commands                                                        |
| `/security`        | Show security policy preview and action log summary                            |
| `/approve-context` | Vouch for the current context (records trust signal for the sentinel)          |
| `/session`         | Show session metadata and domain allowlist                                     |
| `/skills`          | List available skills                                                          |
| `/memory`          | List memory files                                                              |
| `/usage`           | Show token usage breakdown with cost estimates                                 |
| `/pull`            | Pull from external Git remote (if configured)                                  |
| `/push`            | Push to external Git remote (if configured)                                    |
| `/reload`          | Reset sandbox — destroy container + workspace, fresh git clone on next command |

### WebSocket-only commands

| Command                         | Effect                                                         |
| ------------------------------- | -------------------------------------------------------------- |
| `/verbose`                      | Toggle tool call display                                       |
| `/models`                       | View all models (agent, sentinel, title) and available options |
| `/model [NAME\|reset]`          | View or switch the agent model                                 |
| `/model-sentinel [NAME\|reset]` | View or switch the sentinel model                              |
| `/model-title [NAME\|reset]`    | View or switch the title model                                 |
| `/quit` / `/exit`               | Close WebSocket connection                                     |

### Matrix-only commands

| Command    | Effect                                                                          |
| ---------- | ------------------------------------------------------------------------------- |
| `/reset`   | Create a new session for the room (clears history, credentials, security state) |
| `/approve` | Approve the pending operation (alternative to ✅ reaction)                      |
| `/deny`    | Deny the pending operation (alternative to ❌ reaction)                         |

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
