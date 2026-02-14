# Sessions and Channels

Sessions are the core abstraction in Carapace. They are decoupled from any specific channel -- a session is a conversation context with its own rule state. Channels create and interact with sessions, but don't own them.

## Session model

```python
class Session(BaseModel):
    session_id: str
    channel_type: str          # "matrix" | "cron" | "webhook" | "web" | ...
    channel_ref: str           # channel-specific ID (room_id, cron job name, etc.)
    activated_rules: list[str] # rule IDs that have been triggered
    disabled_rules: list[str]  # rules the user disabled via /disable
    approved_credentials: list[str]  # credential names approved this session
    approved_operations: list[str]   # operation hashes (for caching)
    history: Path              # path to history.jsonl
    created_at: datetime
    last_active: datetime
```

## Session lifecycle

- Sessions are **persistent** -- they survive Carapace restarts. History and state are stored on disk.
- `/reset` creates a **new session ID** and links the chat to it. The old session's history remains on disk for auditing.
- **Activated rules and approved credentials** persist with the session state. They survive container restarts but are cleared on `/reset`.
- **Containers** are ephemeral: destroyed after an idle timeout (configurable, default 15 min). When the user sends a new message after containers expired, they are pre-warmed again.

## Session triggers

| Channel               | Session behavior                                                          |
| --------------------- | ------------------------------------------------------------------------- |
| Matrix                | One session per room by default. DMs get a persistent session.            |
| Cron                  | A scheduled job creates a session, runs agent instructions, session ends. |
| Webhook / Email       | An inbound event triggers a session with the event payload as context.    |
| Web frontend (future) | A browser UI for creating, inspecting, and interacting with sessions.     |

Each channel adapter decides how to map its concept of "conversation" to sessions. The Session Manager doesn't care about the channel -- it just manages lifecycle and state.

## Error handling

The agent decides how to handle errors (retries, alternatives, reporting to the user) based on its `AGENTS.md` instructions. Carapace surfaces errors to the agent as tool return values, not as crashes.

---

## Channel system

Channels are pluggable adapters that connect external systems to Carapace sessions.

### Channel interface

```python
class Channel(ABC):
    async def start(self) -> None: ...
    async def send_message(self, session_id: str, content: str) -> None: ...
    async def send_approval_request(self, session_id: str, request: ApprovalRequest) -> None: ...
    async def wait_for_approval(self, session_id: str, request_id: str) -> ApprovalResult: ...
```

### Matrix channel

The initial (and primary) channel, using [matrix-nio](https://github.com/matrix-nio/matrix-nio) with E2EE support.

Features:

- End-to-end encrypted messaging
- Reactions for quick approvals
- Threads for long outputs
- Slash commands for session control

Configuration:

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

### Cron channel

Triggers sessions on a schedule. Since cron sessions are non-interactive, they need an approval target for rule-gated operations.

```yaml
channels:
  cron:
    enabled: false
    jobs:
      - id: daily-email-check
        schedule: "0 9 * * *"
        instructions: "Check my inbox for urgent emails and summarize."
        approval_target:
          channel: matrix
          dm: "@me:example.com"
```

### Future channels

- **Webhook / Email**: An inbound HTTP request or email triggers a session
- **Web UI**: Browser-based interface for session management and interaction

## Cross-channel approvals

Non-interactive sessions (cron, webhook) need to route approval requests to an interactive channel. Each cron job or webhook config specifies an `approval_target` -- a Matrix DM or room where approvals are sent.

To avoid interference with that room's own conversational session, approval messages are sent as **tagged system messages** with the originating session ID. The channel adapter recognizes these tags and routes approval responses back to the correct session, not the room's own session.

---

## Slash commands

Slash commands are the user's control interface for managing sessions and rules. They are channel-agnostic -- any channel that supports text input can process them.

| Command              | Effect                                                               |
| -------------------- | -------------------------------------------------------------------- |
| `/rules`             | List all rules and their status (active/inactive/disabled)           |
| `/disable <rule-id>` | Disable a rule for this session (with warning)                       |
| `/enable <rule-id>`  | Re-enable a previously disabled rule                                 |
| `/reset`             | Reset: create new session, clear activated rules, revoke credentials |
| `/session`           | Show current session state (activated rules, approved creds)         |
| `/skills`            | List available skills                                                |
| `/memory`            | Show memory summary                                                  |
| `/approve`           | Approve the pending operation (alternative to reaction)              |
| `/deny`              | Deny the pending operation                                           |
| `/help`              | Show available commands                                              |

---

## Approval Gate

The Approval Gate sends approval requests through the session's channel and waits for a response.

### Approval UX (example via Matrix)

```
Approval Required [rule: no-exfil-after-sensitive]

The agent wants to send an email (write_external).
Active rule: "no-exfil-after-sensitive" -- the agent previously
accessed your financial data in this session.

Operation: email_sender.send_email(to="accountant@...", subject="Q4 Summary")

/approve or /deny
```

For plan-based approval (consolidated), the prompt shows the full plan with all applicable rules. See [rules.md](rules.md) for details.
