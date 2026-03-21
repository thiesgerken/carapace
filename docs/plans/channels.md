# Plan: Additional Channels & Scheduling

> Status: planned. Currently only the WebSocket (web frontend) and Matrix channels are implemented.

## Task scheduling (cron / heartbeat)

A scheduling system that triggers agent sessions on a schedule, tied to `HEARTBEAT.md`:

- **`HEARTBEAT.md`**: A workspace file the agent can edit to define periodic checks and scheduled tasks. Lives alongside `AGENTS.md`, `SOUL.md`, and `USER.md` in `$CARAPACE_DATA_DIR/`.
- **Cron-style execution**: Jobs defined in `HEARTBEAT.md` (or `config.yaml`) run on a schedule, creating sessions with predefined instructions.
- **Non-interactive sessions**: Since scheduled sessions have no user present, operations that require approval must be routed to an interactive channel.

### Cross-channel approvals

Non-interactive sessions (cron, heartbeat) need to route approval requests to an interactive channel. Each job would specify an `approval_target` — a Matrix DM or room where approvals are sent.

To avoid interference with that room's own conversational session, approval messages would be sent as tagged system messages with the originating session ID. The channel adapter recognizes these tags and routes approval responses back to the correct session.

### Config model (already exists)

The config model already includes `CronChannelConfig` and `CronJobConfig`:

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

## Matrix E2EE

Add end-to-end encryption support to the Matrix channel via matrix-nio's E2EE capabilities. Currently the Matrix channel uses plain-text messaging only.

Requirements:
- Device key management and verification
- Encrypted room support
- Key backup and recovery
