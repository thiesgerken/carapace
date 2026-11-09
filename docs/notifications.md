# Notifications

This document describes carapace's notification backend as it exists today.

Current status:

- Subscription storage, presence tracking, routing, suppression, clearing, and Web Push delivery are implemented on the backend.
- The web frontend already reports interactive presence for active sessions.
- The web frontend now registers a service worker, can create browser push subscriptions from Preferences, and can receive `notification_clear` payloads to close matching notifications.

## Overview

The notification system has two separate concerns:

- subscription and delivery state, stored under `$CARAPACE_DATA_DIR/notifications/`
- interactive presence, tracked in memory so the server can suppress or clear notifications when a session is already being handled

The backend currently emits notifications for:

- `escalation_pending`
- `attended_turn_completed`
- `unattended_turn_completed`
- `unattended_turn_failed`
- `notification_clear`

## Subscription model

Push subscriptions are stored as YAML files at `$CARAPACE_DATA_DIR/notifications/subscriptions/<subscription_id>.yaml`.

Each subscription records:

- `id`
- `user`
- `device_name`
- `endpoint`
- `p256dh`
- `auth`
- `notification_prefs`
- `subscribed_at`
- `last_heartbeat`
- `expires_at`

`user` is the normalized authenticated username. Notification APIs list and update subscriptions owned by the current user.

Default per-device preferences:

| Kind                        | Default |
| --------------------------- | ------- |
| `escalation_pending`        | on      |
| `attended_turn_completed`   | on      |
| `unattended_turn_completed` | off     |
| `unattended_turn_failed`    | on      |

## Notification ids

Notification ids are stable so clients can deduplicate, replace, and clear them across devices.

- Escalations: `esc:{session_id}:{request_id}`
- Turn outcomes: `done:{session_id}:{assistant_event_index}:{kind}`

The router sends `notification_clear` with the original notification id so clients can close matching notifications by tag.

## Presence model

Presence is runtime-only and is not stored in `SessionState`.

Each presence entry includes:

- `session_id`
- `source_id`
- `client_type`: `web`, `matrix`, or `cli`
- `focus_state`: `visible`, `hidden`, or `inactive`
- `last_activity`

A session is considered actively handled when at least one presence entry is active:

- web: `focus_state == visible`
- cli: any state other than `inactive`
- matrix: any recent room activity

Presence uses a TTL (`notifications.presence_ttl_seconds`, default `60`). Stale entries are ignored.

## Suppression and clear behavior

The router suppresses notification delivery when `is_session_actively_handled(session_id)` is true.

This affects escalation and turn-outcome notifications. Clear notifications are still delivered so already-shown notifications can be removed across devices.

Pending notification ids are cleared when the session becomes active again, including:

- a new user message in the session
- a web presence heartbeat that marks the session active
- a websocket reconnect that marks the session active
- Matrix activity that marks the session active again
- escalation resolution

## Delivery behavior

The Web Push sender uses `pywebpush` with VAPID configuration from the platform config. Browser subscriptions and per-user notification ownership are managed through the web UI and notification APIs.

Behavior:

- auto-generates and persists a VAPID keypair when none is configured
- deletes subscriptions on `404` or `410`
- retries `429` and transient transport errors with exponential backoff
- rejects payloads larger than `notifications.max_payload_bytes`
- uses `notifications.delivery_ttl_seconds` as push TTL

Payload shape includes:

- `kind`
- `notif_id`
- `title`
- `body`
- `session_id`
- `event_index` (turn outcomes only: the turn's first event)
- `tag` (defaults to `notif_id`)
- `badge`
- `icon`
- `actions`

Current payload actions use a single `open` action with title `Open session`.

Clicking a turn-outcome notification opens `/?session=<id>&event=<event_index>`, so the chat lands at the top of the turn (its user or trigger message) and the reader scrolls down through every agent message of that turn instead of starting below the last one.

## Configuration

Notification config lives under `notifications:` in the platform backing config. The defaults work for local deployments; carapace can generate and persist a VAPID keypair automatically.

```yaml
notifications:
  enabled: true
  presence_ttl_seconds: 60
  subscription_ttl_days: 30
  # Optional. If omitted, carapace generates and persists a private key automatically.
  # vapid_private_key: "<private-key-pem>"
  # Optional. Defaults to "mailto:carapace@localhost".
  # vapid_subject: "mailto:you@example.com"
  send_timeout_seconds: 10
  retry_attempts: 2
  retry_backoff_seconds: 1.0
  max_payload_bytes: 4096
  delivery_ttl_seconds: 600
  default_preferences:
    escalation_pending: true
    attended_turn_completed: true
    unattended_turn_completed: false
    unattended_turn_failed: true
```

VAPID behavior:

- If `vapid_private_key` is omitted, carapace generates one on startup.
- Generated private keys are persisted at `$CARAPACE_DATA_DIR/notifications/vapid_private_key.pem` and reused on later restarts.
- If `vapid_subject` is omitted, carapace uses `mailto:carapace@localhost`.
- The public key is derived from the private key and exposed through `/api/config/vapid-public-key`.

## API

Notification subscription and presence endpoints use the same `carapace_session` cookie auth as the rest of the server.

### Public config

| Endpoint                       | Method | Purpose                                                                                       |
| ------------------------------ | ------ | --------------------------------------------------------------------------------------------- |
| `/api/config/vapid-public-key` | `GET`  | Expose the configured VAPID public key to browsers so they can call `PushManager.subscribe()` |

### Subscription lifecycle

| Endpoint                                                         | Method   | Purpose                                      |
| ---------------------------------------------------------------- | -------- | -------------------------------------------- |
| `/api/notifications/subscriptions`                               | `GET`    | List subscriptions for the current owner key |
| `/api/notifications/subscriptions`                               | `POST`   | Create or update a push subscription         |
| `/api/notifications/subscriptions/{subscription_id}`             | `DELETE` | Delete a subscription                        |
| `/api/notifications/subscriptions/{subscription_id}/preferences` | `PATCH`  | Update per-device preferences                |
| `/api/notifications/subscriptions/{subscription_id}/test`        | `POST`   | Send a test notification to one subscription |

### Presence updates

| Endpoint                                                      | Method | Purpose                                                                    |
| ------------------------------------------------------------- | ------ | -------------------------------------------------------------------------- |
| `/api/notifications/subscriptions/{subscription_id}/presence` | `POST` | Heartbeat for subscription-backed presence and subscription expiry refresh |
| `/api/notifications/presence`                                 | `POST` | Heartbeat for interactive presence not tied to a push subscription         |

Presence request fields:

- `session_id`
- `client_type`
- `focus_state`
- `source_id` for `/api/notifications/presence`

## WebSocket interaction

The session WebSocket does not carry a dedicated notification protocol.

It participates in notification state in two ways:

- the client may supply `client_id=<stable-id>` on `/api/chat/{session_id}`
- websocket connect and disconnect update the same shared presence registry used by the notification router, unless the client connects with `observe=true` (the debug view)

The web client also posts REST presence heartbeats alongside the WebSocket connection. See [websocket-session.md](websocket-session.md) for transport details.

## Current limitations

- Browser push still depends on secure-context support in the current browser or installed PWA.
- If VAPID keys are not configured on the server, the frontend can render the subscription controls but cannot complete Web Push registration.
- Notification clicks currently route back into the session view, but there is no richer in-app notification center or foreground toast layer yet.

## Related docs

- [quickstart.md](quickstart.md) for deployment and config setup
- [sessions-and-channels.md](sessions-and-channels.md) for session semantics and channel behavior
- [websocket-session.md](websocket-session.md) for WebSocket transport details
