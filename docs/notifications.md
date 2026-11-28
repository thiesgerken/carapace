# Notifications

This document describes carapace's notification backend as it exists today.

Current status:

- Subscription storage, presence tracking, routing, suppression, clearing, and Web Push delivery are implemented on the backend.
- The web frontend reports interactive presence for active sessions.
- The web frontend registers a service worker, can create browser push subscriptions from Preferences, and can receive `notification_clear` payloads to close matching notifications.

## Overview

The notification system has two separate concerns:

- subscription and delivery state: subscriptions in the `notification_subscriptions` database table, the generated VAPID key under `$CARAPACE_DATA_DIR/notifications/`
- interactive presence, tracked in memory so the server can suppress or clear notifications when a session is already being handled

The backend currently emits notifications for:

- `escalation_pending`
- `attended_turn_completed`
- `unattended_turn_completed`
- `unattended_turn_failed`
- `notification_clear`

## Subscription model

Push subscriptions are stored in the `notification_subscriptions` database table, one row per subscription, unique per user and endpoint.

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

The Web Push sender uses `pywebpush` with the VAPID settings from the notifications config. Browser subscriptions and per-user notification ownership are managed through the web UI and notification APIs.

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
- `event_index` (turn outcomes only: where the chat opens, see below)
- `tag` (defaults to `notif_id`)
- `badge`
- `icon`
- `actions`

Current payload actions use a single `open` action with title `Open session`.

Clicking a turn-outcome notification opens `/?session=<id>&event=<event_index>` with that event at the top, so the reader scrolls down through every agent message of the turn instead of starting below the last one. For an attended turn the event is the user's own message, which they want as context. For a job turn it is the agent's first event: the job's invocation prompt is boilerplate, so the link skips it.

## Configuration

Notification config comes from environment variables with the `CARAPACE_NOTIFICATIONS_` prefix (nested fields use `__`). The defaults work for local deployments; carapace can generate and persist a VAPID keypair automatically.

```bash
CARAPACE_NOTIFICATIONS_ENABLED=true
CARAPACE_NOTIFICATIONS_PRESENCE_TTL_SECONDS=60
CARAPACE_NOTIFICATIONS_SUBSCRIPTION_TTL_DAYS=30
# Optional. If omitted, carapace generates and persists a private key automatically.
# CARAPACE_NOTIFICATIONS_VAPID_PRIVATE_KEY="<private-key-pem>"
# Optional. Defaults to "mailto:carapace@localhost".
# CARAPACE_NOTIFICATIONS_VAPID_SUBJECT="mailto:you@example.com"
CARAPACE_NOTIFICATIONS_SEND_TIMEOUT_SECONDS=10
CARAPACE_NOTIFICATIONS_RETRY_ATTEMPTS=2
CARAPACE_NOTIFICATIONS_RETRY_BACKOFF_SECONDS=1.0
CARAPACE_NOTIFICATIONS_MAX_PAYLOAD_BYTES=4096
CARAPACE_NOTIFICATIONS_DELIVERY_TTL_SECONDS=600
CARAPACE_NOTIFICATIONS_DEFAULT_PREFERENCES__ESCALATION_PENDING=true
CARAPACE_NOTIFICATIONS_DEFAULT_PREFERENCES__ATTENDED_TURN_COMPLETED=true
CARAPACE_NOTIFICATIONS_DEFAULT_PREFERENCES__UNATTENDED_TURN_COMPLETED=false
CARAPACE_NOTIFICATIONS_DEFAULT_PREFERENCES__UNATTENDED_TURN_FAILED=true
```

VAPID behavior:

- If `vapid_private_key` is omitted, carapace generates one on startup.
- Generated private keys are persisted at `$CARAPACE_DATA_DIR/notifications/vapid_private_key.pem` and reused on later restarts.
- If `vapid_subject` is omitted, carapace uses `mailto:carapace@localhost`.
- The public key is derived from the private key and exposed through `/api/config/vapid-public-key`.

## API

Notification subscription and presence endpoints use the same auth as the rest of the server: the `carapace_session` cookie, or an API key with the `notifications` scope (`read` to list subscriptions, `write` otherwise). The VAPID public key endpoint needs no auth.

### Public config

| Endpoint                       | Method | Purpose                                                                                       |
| ------------------------------ | ------ | --------------------------------------------------------------------------------------------- |
| `/api/config/vapid-public-key` | `GET`  | Expose the configured VAPID public key to browsers so they can call `PushManager.subscribe()` |

### Subscription lifecycle

| Endpoint                                                         | Method   | Purpose                                      |
| ---------------------------------------------------------------- | -------- | -------------------------------------------- |
| `/api/notifications/subscriptions`                               | `GET`    | List subscriptions of the current user       |
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
- Notification clicks currently route back into the session view, but there is no richer in-app notification center or foreground toast layer yet.

## Related docs

- [quickstart.md](quickstart.md) for deployment and config setup
- [sessions-and-channels.md](sessions-and-channels.md) for session semantics and channel behavior
- [websocket-session.md](websocket-session.md) for WebSocket transport details
