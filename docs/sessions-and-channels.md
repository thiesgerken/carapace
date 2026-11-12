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

Sessions persist across server restarts. The sentinel state (action log and shadow conversation) is persisted too and loaded when a session is reactivated, so the sentinel continues where it stopped (see [security.md](security.md#sentinel-state)).

`history.yaml` and `events.yaml` serve different purposes:

- `history.yaml` stores the full `ModelMessage` sequence that is fed back into Pydantic AI on the next turn. This is the model-side conversation state.
- `events.yaml` stores the normalized session transcript used by the UI and APIs. It includes items that do not belong in model history, such as slash commands, approval requests/responses, and other operational events.
- The REST history endpoint reads `events.yaml` as the user-facing transcript source.
- Retry, reset, fork, and knowledge export align both files by completed turns, but they do not collapse them into a single source of truth.

### Failed turns

A turn that ends early (cancelled, blocked by a session budget, unusable model, or an unexpected error) is closed in both files:

- `history.yaml` gets a synthetic failed return for every tool call still in flight, then the terminal message as the turn's final model response, so the model sees on the next turn that the previous one did not complete.
- `events.yaml` gets a synthetic `tool_result` (`exit_code` 130) for every tool call of this turn still waiting for a result (calls an earlier turn left open are not touched), then a `role: "error"` event with the terminal message. The error event ends the turn like a final assistant answer does: retry, reset, fork, and compaction treat it as the turn boundary, and the web UI renders it as an error both live and after a reload.
- Access decisions (`proxy_domain`, `credential_access`, and `git_push` events, nested under the tool call that triggered them) and denied tool calls never get a `tool_result`, so a failed turn never adds synthetic results for them.

A budget stop names the `/budget` command that raises each reached limit, e.g. `/budget cost N`.

## Knowledge commits

carapace can optionally commit session histories into the Git-backed knowledge repository. This is a secondary persistence path for long-term recall, not the primary runtime store.

- The canonical committed artifact is `conversation.json`
- Session snapshots are written under `<knowledge_dir>/sessions/YYYY/MM/<session_id>/conversation.json` by default
- The payload is built from the normalized session event log, so it includes user messages, assistant replies, tool calls, tool results, approvals, and event timestamps
- A forked session's snapshot has `session.forked_from` (`session_id`, `event_count`): its first `event_count` history entries are copies of the source's, with the source's timestamps. Readers that index archives (e.g. search) skip them so each turn appears once, under the session it was written in. Other snapshots don't have the key.
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
- **Continue** replaces Retry on the error of a turn that stopped with its progress kept (cancelled, or a session budget reached). Its tool calls and results are already in the history, so instead of rerunning the turn it sends a plain "Continue." message. The error event and the live `error` message carry `resumable: true` for these turns; a `cancelled` turn always is
- **Reset to turn** rewinds the session to an earlier completed turn boundary
- **Fork** creates a new session from a chosen event boundary. The copy records its origin in `SessionState.forked_from`: the source session id and how many leading events it inherited. Resetting the copy to before that point lowers the count, since what follows is then the copy's own.

Retry and reset are WebSocket actions; fork is a REST action.

### Session budgets

`SessionBudget` caps a session's totals: input tokens, output tokens, actual and equivalent cost in USD (see below), and tool calls. It also holds the autonomy limit (see below). A new session starts from the user's default budget (**Settings** -> **Account**) if it sets any limit, otherwise from the platform default (**Settings** -> **Admin** -> **Platform**). Once one of the totals is reached, the next LLM call ends the turn with a "Session budget reached" error.

Per session, limits change in two places, which share one parser (`parse_budget_limit`) and one setter (`SessionEngine.update_session_budget`):

- `/budget input N`, `/budget output N`, `/budget cost N`, `/budget equivalent_cost N`, `/budget tools N`, `/budget autonomy N`. `N` accepts `k`/`M` suffixes for counts; `0` clears a limit.
- The **Budget** section of the session drawer in the web UI: click a limit, enter a value (same syntax), leave it empty for no limit. It sends `PATCH /api/sessions/{id}` with `{"budget": {"input_tokens": "100k"}}`; `null` clears a limit, omitted fields stay unchanged, and an invalid value is rejected with `400` before anything in the request is applied.

Both paths broadcast a `status` message with the new `budget` to every connected WebSocket client, so the budget gauges and the drawer refresh in every tab. `GET`/`PATCH /api/sessions/{id}` return the current limits as `budget`.

### Actual and equivalent cost

Cost is tracked twice, because subscription models are not billed per token:

- **Cost** (actual, `cost_usd`, `/budget cost N`): what the session costs in real money. Pay-per-token models count with the provider-reported cost or, without one, their list price. Subscription models add nothing.
- **Equivalent cost** (`equivalent_cost_usd`, `/budget equivalent_cost N`): the list price of everything, subscription usage included, i.e. what the session would have cost on the API. It is always at least the actual cost, and the same as it for sessions without subscription usage.

A model counts as a subscription model by its provider (`SUBSCRIPTION_PROVIDERS` in `models/config.py`, today only `openai-codex`, see [chatgpt-subscription.md](chatgpt-subscription.md)). In a mixed session, e.g. the agent on a ChatGPT subscription and the sentinel on a pay-per-token API, only the API part is actual cost.

Both are limited independently, and reaching either one blocks the next LLM call with a message naming the limit and its `/budget` key. The cost gauge shows with a limit, as the other gauges do; the equivalent cost gauge shows with a limit or as soon as the session used a subscription model, then without a limit. `/usage` shows one cost per model, marking subscription models ("$0.42 · subscription"), and the actual cost per category and in total, with "(≈ $X equivalent)" added where subscription usage makes it differ (for the total: whenever the equivalent cost gauge shows). The session drawer shows the equivalent total under the same rule.

Migration 0010 renamed every stored cost limit (platform default, user defaults, sessions) to an equivalent cost limit, since the old limit already priced subscription usage at list price. The actual cost limit starts unset.

### Autonomy limit

The **autonomous streak** is the tool calls the agent attempted since the last human interaction. The **autonomy limit** (`SessionBudget.autonomous_tool_calls`, `/budget autonomy N`) caps it. It is loop protection, not security: it applies in YOLO mode too, where nobody watches the agent.

What counts: every tool call attempt, including calls the sentinel denies and skill-blocked calls, since a model looping on denied calls is exactly the case to catch. Output tools (`task_done`, `task_failed`), access decisions nested under a tool call (`proxy_domain`, `credential_access`, `git_push`), and the re-run of a call the user approved don't count. The total `tool_calls` budget is separate and counts allowed calls only.

What resets the streak:

- a new user message,
- any approval or escalation the user resolves, allow or deny, except a deny of an autonomy-limit approval.

Sentinel approvals and safe-listed or skill-declared auto-approvals never reset it. Once the limit stopped the agent (see below), only the next user message lifts the stop; changing the limit lifts it too.

On reaching the limit:

- **Attended sessions** pause. Every call over the limit asks for approval with "Autonomy limit reached (N tool calls without you)", through the normal approval cards (web, CLI, Matrix). Allowing at least one card of a batch resets the streak, and the allowed calls continue to the security gate (safe-list, sentinel, possibly another escalation) exactly as if the limit had not been hit: "continue" is no verdict on the call itself, so it is not recorded as a user decision in the sentinel's action log either. A denied card tells the model "Autonomy limit reached. Stop calling tools and report what you have." If the user allowed none of the autonomy cards of a batch, the next tool call ends the turn with a budget stop (`/budget autonomy N`), whatever else the user decided in that batch.
- **Unattended sessions** (`attributes.unattended`, the default for jobs) have no one to ask: every call of the batch that crosses the limit is denied with the same wrap-up instruction, so a job still ends with a report. The next tool call ends the turn with a budget stop. Jobs with `persistent_session_id` and Matrix sessions are attended and pause instead.

There is no timeout on the pause, and a pending autonomy approval is closed like any other approval when the server restarts. The streak lives in memory on the active session; a restart resets it. The chat input shows it as the "Autonomy" gauge.

The platform default is 100 (`default_session_budget.autonomous_tool_calls`), overridable per user and per session like the other limits. A user default budget with any limit replaces the platform one as a whole, so **Settings** -> **Account** starts a new user default from the platform's autonomy limit, and migration 0009 added 100 to every stored user default that had a limit.

As a stopgap for model loops the per-tool-call streak doesn't see (e.g. calls that fail argument validation and never reach a tool), one agent run may make at most three times the autonomy limit in model requests. Hitting it ends the turn with an error like any other budget stop. Without an autonomy limit there is no request limit either: the user turned loop protection off.

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
| `/api/sessions/search`                | `GET`    | Search titles, or with `fulltext=true` also chat messages (`q`, `fulltext`)    |
| `/api/sessions/{id}`                  | `GET`    | Get session details                                                            |
| `/api/sessions/{id}`                  | `PATCH`  | Update session attributes, model overrides, and budget limits                  |
| `/api/sessions/{id}/fork`             | `POST`   | Fork a session from a chosen event boundary                                    |
| `/api/sessions/{id}`                  | `DELETE` | Delete session + cleanup sandbox                                               |
| `/api/sessions/{id}/knowledge/commit` | `POST`   | Commit the session snapshot into the knowledge repo                            |
| `/api/sessions/{id}/history`          | `GET`    | Get chat history (optional `limit` param)                                      |
| `/api/sessions/{id}/sandbox`          | `GET`    | Get sandbox status and storage snapshot                                        |
| `/api/sessions/{id}/sandbox/up`       | `POST`   | Start or warm the sandbox                                                      |
| `/api/sessions/{id}/sandbox/down`     | `POST`   | Stop or scale down the sandbox                                                 |
| `/api/sessions/{id}/sandbox/wipe`     | `POST`   | Destroy sandbox workspace state and start fresh later                          |

`GET /api/sessions` pages in a fixed order: active sessions before archived ones, pinned first within each, then most recently active.

`GET /api/sessions/search` returns at most 50 of the user's sessions, active and archived alike, most recently active first. It matches `q` as a case-insensitive substring of the title; `fulltext=true` also matches the text of user and assistant messages (no tool calls, tool output or slash commands) and returns a snippet around the first matching message. It scans the event rows without a full-text index. A blank `q` is a 422.

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

Authentication uses the `carapace_session` cookie issued by `POST /api/auth/login`. The optional WebSocket query parameters are `client_id`, used to keep interactive presence stable across reconnects, and `observe=true` for a connection that only watches the session and registers no presence (the debug view).

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

At server startup, a channel that fails to start (unreachable homeserver, failed login or initial sync) does not stop the server. carapace logs the error, keeps that channel stopped, and retries in the background with exponential backoff (5 seconds, doubling up to 5 minutes) until it starts. **Settings** -> **Account** -> **Matrix** shows the channel's state (running, or failed with the last error), so a broken channel can be fixed or disabled there. Saving the Matrix settings stays strict: if the channel does not start with the new settings, the save fails and the previous settings stay in place. If the previous settings do not start either (for example during a homeserver outage), they get the same background retry.

If the homeserver invalidates the channel's access token while it runs (`M_UNKNOWN_TOKEN`), the channel logs in again with the configured password and keeps syncing. Without a password it stops syncing until the Matrix settings are saved with one.

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
| `/budget`                                       | Show or update session budgets: tokens, actual and equivalent cost, tool calls, autonomy |
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

An approval request (tool, domain access, git push, or credential) can only be answered while the turn that raised it is still running. When a turn ends with a request still open (cancelled, failed, or completed while an escalation was pending), carapace closes it before the turn's terminal event (final assistant answer or error): it appends the regular response event with `decision` `denied` (tool) or `deny` (escalation), `decision_source: "system"`, and the message "Turn ended before a decision was made." Any escalation callback still blocked on the request is released with a denial.

A server restart kills turns without that cleanup, so the server closes such leftover requests in the same way at startup, before any session is activated. Clients therefore never see an actionable request that nothing waits for anymore.
