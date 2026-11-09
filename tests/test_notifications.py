from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

from py_vapid import Vapid01
from pywebpush import WebPushException

from carapace.notifications.models import NotificationPreferences, NotificationsConfig, NotificationSubscription
from carapace.notifications.presence import NotificationPresenceRegistry
from carapace.notifications.router import NotificationDeliveryResult, NotificationPayload, NotificationRouter
from carapace.notifications.sender import WebPushSender
from carapace.notifications.store import NotificationStore
from carapace.notifications.vapid import derive_vapid_public_key, ensure_vapid_config


def _generated_private_key_pem() -> str:
    vapid = Vapid01()
    vapid.generate_keys()
    return vapid.private_pem().decode("utf-8").strip()


def test_notification_subscription_defaults_last_heartbeat() -> None:
    subscribed_at = datetime(2026, 5, 12, tzinfo=UTC)
    subscription = NotificationSubscription.model_validate(
        {
            "id": "sub-1",
            "user": "thies",
            "endpoint": "https://push.example.test/sub-1",
            "p256dh": "p256dh",
            "auth": "auth",
            "subscribed_at": subscribed_at,
            "expires_at": subscribed_at + timedelta(days=30),
        }
    )

    assert subscription.last_heartbeat == subscribed_at


def test_notification_store_upsert_and_list_by_user(db_factory) -> None:
    store = NotificationStore(db_factory)
    now = datetime(2026, 5, 12, tzinfo=UTC)
    prefs = NotificationPreferences(attended_turn_completed=False)

    created = store.upsert_subscription(
        user="thies",
        endpoint="https://push.example.test/sub-1",
        p256dh="key-1",
        auth="auth-1",
        device_name="Phone",
        notification_prefs=prefs,
        ttl=timedelta(days=30),
        now=now,
    )

    updated = store.upsert_subscription(
        user="thies",
        endpoint="https://push.example.test/sub-1",
        p256dh="key-2",
        auth="auth-2",
        device_name="Phone 2",
        notification_prefs=NotificationPreferences(unattended_turn_completed=True),
        ttl=timedelta(days=30),
        now=now + timedelta(hours=1),
    )

    assert updated.id == created.id
    assert updated.device_name == "Phone 2"
    assert updated.p256dh == "key-2"
    assert updated.notification_prefs.unattended_turn_completed is True
    assert [subscription.id for subscription in store.list_subscriptions(user="thies")] == [created.id]


def test_notification_store_find_by_endpoint_requires_owner_scope(db_factory) -> None:
    store = NotificationStore(db_factory)
    now = datetime(2026, 5, 12, tzinfo=UTC)
    endpoint = "https://push.example.test/shared"
    created = store.upsert_subscription(
        user="thies",
        endpoint=endpoint,
        p256dh="key-1",
        auth="auth-1",
        device_name="Desktop",
        notification_prefs=NotificationPreferences(),
        ttl=timedelta(days=30),
        now=now,
    )

    assert store.find_by_endpoint(user="ada", endpoint=endpoint) is None

    other_user = store.upsert_subscription(
        user="ada",
        endpoint=endpoint,
        p256dh="key-2",
        auth="auth-2",
        device_name="Desktop 2",
        notification_prefs=NotificationPreferences(),
        ttl=timedelta(days=30),
        now=now + timedelta(hours=1),
    )

    assert other_user.id != created.id


def test_notification_store_cleanup_expired(db_factory) -> None:
    store = NotificationStore(db_factory)
    now = datetime(2026, 5, 12, tzinfo=UTC)
    subscription = store.upsert_subscription(
        user="thies",
        endpoint="https://push.example.test/sub-1",
        p256dh="key-1",
        auth="auth-1",
        device_name="Desktop",
        notification_prefs=NotificationPreferences(),
        ttl=timedelta(days=1),
        now=now,
    )

    deleted = store.cleanup_expired(now=now + timedelta(days=2))

    assert deleted == [subscription.id]
    assert store.get_subscription(subscription.id) is None


def test_presence_registry_tracks_visible_web_session() -> None:
    registry = NotificationPresenceRegistry(ttl=timedelta(seconds=60))
    now = datetime(2026, 5, 12, tzinfo=UTC)

    registry.update_presence(
        session_id="session-1",
        source_id="sub-1",
        client_type="web",
        focus_state="visible",
        now=now,
    )

    assert registry.is_session_actively_handled("session-1", now=now + timedelta(seconds=30)) is True
    assert registry.is_session_actively_handled("session-1", now=now + timedelta(seconds=61)) is False


def test_presence_registry_hidden_web_is_not_active() -> None:
    registry = NotificationPresenceRegistry(ttl=timedelta(seconds=60))
    now = datetime(2026, 5, 12, tzinfo=UTC)

    registry.update_presence(
        session_id="session-1",
        source_id="sub-1",
        client_type="web",
        focus_state="hidden",
        now=now,
    )

    assert registry.is_session_actively_handled("session-1", now=now) is False


def test_presence_registry_cli_entry_is_active_until_stale() -> None:
    registry = NotificationPresenceRegistry(ttl=timedelta(seconds=60))
    now = datetime(2026, 5, 12, tzinfo=UTC)

    registry.update_presence(
        session_id="session-1",
        source_id="cli-1",
        client_type="cli",
        focus_state="visible",
        now=now,
    )

    assert registry.is_session_actively_handled("session-1", now=now + timedelta(seconds=30)) is True
    assert registry.is_session_actively_handled("session-1", now=now + timedelta(seconds=70)) is False


async def test_notification_router_dispatch_turn_outcome_filters_by_preference_and_presence(db_factory) -> None:
    store = NotificationStore(db_factory)
    sender = AsyncMock()
    now = datetime.now(tz=UTC)
    matching_subscription = store.upsert_subscription(
        user="thies",
        endpoint="https://push.example.test/sub-1",
        p256dh="key-1",
        auth="auth-1",
        device_name="Phone",
        notification_prefs=NotificationPreferences(attended_turn_completed=True),
        ttl=timedelta(days=30),
        now=now,
    )
    store.upsert_subscription(
        user="thies",
        endpoint="https://push.example.test/sub-2",
        p256dh="key-2",
        auth="auth-2",
        device_name="Laptop",
        notification_prefs=NotificationPreferences(attended_turn_completed=False),
        ttl=timedelta(days=30),
        now=now,
    )
    sender.send_batch = AsyncMock(return_value={matching_subscription.id: True})
    presence = NotificationPresenceRegistry(ttl=timedelta(seconds=60))
    router = NotificationRouter(
        store=store,
        presence=presence,
        sender=sender,
        owner_for_session=lambda _session_id: "thies",
    )

    delivery = await router.dispatch_turn_outcome(
        session_id="session-1",
        assistant_event_index=3,
        turn_event_start=1,
        kind="attended_turn_completed",
        title="Session Update",
        body="Assistant turn completed",
    )

    assert delivery == NotificationDeliveryResult(
        attempted_subscription_ids={matching_subscription.id},
        delivered_subscription_ids={matching_subscription.id},
    )
    payload = sender.send_batch.await_args.args[1]
    assert isinstance(payload, NotificationPayload)
    assert payload.notif_id == "done:session-1:3:attended_turn_completed"
    assert payload.event_index == 1

    sender.send_batch.reset_mock()
    presence.update_presence(
        session_id="session-1",
        source_id="web-tab-1",
        client_type="web",
        focus_state="visible",
        now=now,
    )

    suppressed = await router.dispatch_turn_outcome(
        session_id="session-1",
        assistant_event_index=4,
        turn_event_start=1,
        kind="attended_turn_completed",
        title="Session Update",
        body="Assistant turn completed",
    )

    assert suppressed == NotificationDeliveryResult(attempted_subscription_ids=set(), delivered_subscription_ids=set())
    sender.send_batch.assert_not_awaited()


async def test_notification_router_filters_by_session_owner(db_factory) -> None:
    store = NotificationStore(db_factory)
    now = datetime.now(tz=UTC)
    store.upsert_subscription(
        user="alice",
        endpoint="https://push.example.test/alice",
        p256dh="key-1",
        auth="auth-1",
        device_name="Alice Phone",
        notification_prefs=NotificationPreferences(attended_turn_completed=True),
        ttl=timedelta(days=30),
        now=now,
    )
    store.upsert_subscription(
        user="bob",
        endpoint="https://push.example.test/bob",
        p256dh="key-2",
        auth="auth-2",
        device_name="Bob Laptop",
        notification_prefs=NotificationPreferences(attended_turn_completed=True),
        ttl=timedelta(days=30),
        now=now,
    )
    sender = AsyncMock()
    sender.send_batch = AsyncMock(return_value={})
    router = NotificationRouter(
        store=store,
        presence=NotificationPresenceRegistry(ttl=timedelta(seconds=60)),
        sender=sender,
        owner_for_session=lambda _session_id: "alice",
    )

    delivery = await router.dispatch_turn_outcome(
        session_id="alice-session",
        assistant_event_index=3,
        turn_event_start=1,
        kind="attended_turn_completed",
        title="Session Update",
        body="Assistant turn completed",
    )

    assert delivery.attempted_subscription_ids == {store.list_subscriptions(user="alice")[0].id}
    sender.send_batch.assert_awaited_once()


async def test_notification_router_dispatch_test_targets_single_subscription(db_factory) -> None:
    store = NotificationStore(db_factory)
    sender = AsyncMock()
    now = datetime.now(tz=UTC)
    subscription = store.upsert_subscription(
        user="thies",
        endpoint="https://push.example.test/sub-1",
        p256dh="key-1",
        auth="auth-1",
        device_name="Phone",
        notification_prefs=NotificationPreferences(
            escalation_pending=False,
            attended_turn_completed=False,
            unattended_turn_completed=False,
            unattended_turn_failed=False,
        ),
        ttl=timedelta(days=30),
        now=now,
    )
    sender.send_batch = AsyncMock(return_value={subscription.id: True})
    presence = NotificationPresenceRegistry(ttl=timedelta(seconds=60))
    router = NotificationRouter(
        store=store,
        presence=presence,
        sender=sender,
        owner_for_session=lambda _session_id: "thies",
    )

    delivered = await router.dispatch_test(subscription=subscription)

    assert delivered is True
    sender.send_batch.assert_awaited_once()
    payload = sender.send_batch.await_args.args[1]
    assert isinstance(payload, NotificationPayload)
    assert payload.kind == "notification_test"
    assert payload.notif_id == f"test:{subscription.id}"


async def test_web_push_sender_deletes_expired_subscription(db_factory) -> None:
    store = NotificationStore(db_factory)
    now = datetime.now(tz=UTC)
    subscription = store.upsert_subscription(
        user="thies",
        endpoint="https://push.example.test/sub-1",
        p256dh="key-1",
        auth="auth-1",
        device_name="Phone",
        notification_prefs=NotificationPreferences(),
        ttl=timedelta(days=30),
        now=now,
    )

    def _raise_gone(**_kwargs: object) -> object:
        exc = WebPushException("gone")
        exc.response = MagicMock(status_code=410)
        raise exc

    sender = WebPushSender(
        store=store,
        vapid_private_key=_generated_private_key_pem(),
        vapid_subject="mailto:test@example.com",
        timeout_seconds=10,
        retry_attempts=0,
        retry_backoff_seconds=0,
        max_payload_bytes=4096,
        delivery_ttl_seconds=600,
        push_func=_raise_gone,
    )

    sent = await sender.send(
        subscription,
        NotificationPayload(
            kind="attended_turn_completed",
            notif_id="done:session-1:1:attended_turn_completed",
            title="Done",
            body="Completed",
            session_id="session-1",
        ),
    )

    assert sent is False
    assert store.get_subscription(subscription.id) is None


async def test_web_push_sender_skips_oversized_payload(db_factory) -> None:
    store = NotificationStore(db_factory)
    subscription = store.upsert_subscription(
        user="thies",
        endpoint="https://push.example.test/sub-1",
        p256dh="key-1",
        auth="auth-1",
        device_name="Phone",
        notification_prefs=NotificationPreferences(),
        ttl=timedelta(days=30),
        now=datetime.now(tz=UTC),
    )

    sender = WebPushSender(
        store=store,
        vapid_private_key=_generated_private_key_pem(),
        vapid_subject="mailto:test@example.com",
        timeout_seconds=10,
        retry_attempts=0,
        retry_backoff_seconds=0,
        max_payload_bytes=32,
        delivery_ttl_seconds=600,
    )

    sent = await sender.send(
        subscription,
        NotificationPayload(
            kind="attended_turn_completed",
            notif_id="done:session-1:1:attended_turn_completed",
            title="Done",
            body="x" * 128,
            session_id="session-1",
        ),
    )

    assert sent is False
    assert store.get_subscription(subscription.id) is not None


def test_ensure_vapid_config_generates_and_reuses_persisted_keys(tmp_path) -> None:
    config = NotificationsConfig()

    generated = ensure_vapid_config(config, tmp_path)
    reused = ensure_vapid_config(NotificationsConfig(), tmp_path)

    assert generated.vapid_private_key is not None
    assert generated.vapid_subject == "mailto:carapace@localhost"
    assert (tmp_path / "notifications" / "vapid_private_key.pem").exists()
    assert reused.vapid_private_key == generated.vapid_private_key
    assert derive_vapid_public_key(reused.vapid_private_key) == derive_vapid_public_key(generated.vapid_private_key)


def test_ensure_vapid_config_keeps_explicit_private_key_and_defaults_subject(tmp_path) -> None:
    vapid = Vapid01()
    vapid.generate_keys()
    private_key = vapid.private_pem().decode("utf-8")

    config = NotificationsConfig(vapid_private_key=private_key)

    resolved = ensure_vapid_config(config, tmp_path)

    assert resolved.vapid_private_key == private_key.strip()
    assert resolved.vapid_subject == "mailto:carapace@localhost"
    assert derive_vapid_public_key(resolved.vapid_private_key) == derive_vapid_public_key(private_key)


def test_ensure_vapid_config_accepts_legacy_raw_private_key(tmp_path) -> None:
    vapid = Vapid01()
    vapid.generate_keys()
    raw_private_key = vapid.private_key.private_numbers().private_value.to_bytes(32, "big")
    encoded_private_key = base64.urlsafe_b64encode(raw_private_key).rstrip(b"=").decode("ascii")

    resolved = ensure_vapid_config(NotificationsConfig(vapid_private_key=encoded_private_key), tmp_path)

    assert resolved.vapid_private_key.startswith("-----BEGIN PRIVATE KEY-----")
    assert derive_vapid_public_key(resolved.vapid_private_key) == derive_vapid_public_key(encoded_private_key)


async def test_web_push_sender_passes_parsed_vapid_key_to_pywebpush(db_factory) -> None:
    store = NotificationStore(db_factory)
    subscription = store.upsert_subscription(
        user="thies",
        endpoint="https://push.example.test/sub-1",
        p256dh="key-1",
        auth="auth-1",
        device_name="Phone",
        notification_prefs=NotificationPreferences(),
        ttl=timedelta(days=30),
        now=datetime.now(tz=UTC),
    )
    captured_private_key: object | None = None

    def _capture_push(**kwargs: object) -> object:
        nonlocal captured_private_key
        captured_private_key = kwargs["vapid_private_key"]
        return object()

    sender = WebPushSender(
        store=store,
        vapid_private_key=_generated_private_key_pem(),
        vapid_subject="mailto:test@example.com",
        timeout_seconds=10,
        retry_attempts=0,
        retry_backoff_seconds=0,
        max_payload_bytes=4096,
        delivery_ttl_seconds=600,
        push_func=_capture_push,
    )

    sent = await sender.send(
        subscription,
        NotificationPayload(
            kind="attended_turn_completed",
            notif_id="done:session-1:1:attended_turn_completed",
            title="Done",
            body="Completed",
            session_id="session-1",
        ),
    )

    assert sent is True
    assert isinstance(captured_private_key, Vapid01)
