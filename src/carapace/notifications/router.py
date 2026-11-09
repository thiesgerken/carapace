from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Literal, Protocol

from loguru import logger

from .models import NotificationPreferences, NotificationSubscription
from .presence import NotificationPresenceRegistry
from .store import NotificationStore

NotificationKind = Literal[
    "escalation_pending",
    "attended_turn_completed",
    "unattended_turn_completed",
    "unattended_turn_failed",
    "notification_test",
    "notification_clear",
]

TurnOutcomeKind = Literal[
    "attended_turn_completed",
    "unattended_turn_completed",
    "unattended_turn_failed",
]


def build_escalation_notification_id(session_id: str, request_id: str) -> str:
    return f"esc:{session_id}:{request_id}"


def build_turn_outcome_notification_id(
    session_id: str,
    assistant_event_index: int,
    kind: TurnOutcomeKind,
) -> str:
    return f"done:{session_id}:{assistant_event_index}:{kind}"


@dataclass(frozen=True, slots=True)
class NotificationPayload:
    kind: NotificationKind
    notif_id: str
    title: str
    body: str
    session_id: str
    # Deep-link target for the click: the turn's first event (its user or trigger message), so the
    # reader starts above the agent's answer instead of below a long one.
    event_index: int | None = None
    tag: str | None = None
    badge: str = "/badge-icon.png"
    icon: str = "/pwa-192x192.png"
    actions: list[dict[str, str]] | None = None

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["tag"] = self.tag or self.notif_id
        return payload


@dataclass(frozen=True, slots=True)
class NotificationDeliveryResult:
    attempted_subscription_ids: set[str]
    delivered_subscription_ids: set[str]


class NotificationSender(Protocol):
    async def send_batch(
        self,
        subscriptions: list[NotificationSubscription],
        payload: NotificationPayload,
    ) -> dict[str, bool]: ...


class NotificationRouter:
    def __init__(
        self,
        *,
        store: NotificationStore,
        presence: NotificationPresenceRegistry,
        sender: NotificationSender,
        owner_for_session: Callable[[str], str],
    ) -> None:
        self._store = store
        self._presence = presence
        self._sender = sender
        self._owner_for_session = owner_for_session

    async def dispatch_escalation(
        self,
        *,
        session_id: str,
        request_id: str,
        title: str,
        body: str,
    ) -> NotificationDeliveryResult:
        notif_id = build_escalation_notification_id(session_id, request_id)
        return await self._dispatch(
            session_id=session_id,
            kind="escalation_pending",
            payload=NotificationPayload(
                kind="escalation_pending",
                notif_id=notif_id,
                title=title,
                body=body,
                session_id=session_id,
                actions=[{"action": "open", "title": "Open session"}],
            ),
            suppress_when_active=True,
        )

    async def dispatch_turn_outcome(
        self,
        *,
        session_id: str,
        assistant_event_index: int,
        turn_event_start: int,
        kind: TurnOutcomeKind,
        title: str,
        body: str,
    ) -> NotificationDeliveryResult:
        notif_id = build_turn_outcome_notification_id(session_id, assistant_event_index, kind)
        return await self._dispatch(
            session_id=session_id,
            kind=kind,
            payload=NotificationPayload(
                kind=kind,
                notif_id=notif_id,
                title=title,
                body=body,
                session_id=session_id,
                event_index=turn_event_start,
                actions=[{"action": "open", "title": "Open session"}],
            ),
            suppress_when_active=True,
        )

    async def clear_notifications(
        self,
        *,
        session_id: str,
        notif_id: str,
        subscription_ids: set[str] | None = None,
    ) -> NotificationDeliveryResult:
        subscriptions = self._subscriptions_for_session(session_id)
        if subscription_ids is not None:
            subscriptions = [subscription for subscription in subscriptions if subscription.id in subscription_ids]
        if not subscriptions:
            return NotificationDeliveryResult(attempted_subscription_ids=set(), delivered_subscription_ids=set())
        results = await self._sender.send_batch(
            subscriptions,
            NotificationPayload(
                kind="notification_clear",
                notif_id=notif_id,
                title="",
                body="",
                session_id=session_id,
            ),
        )
        delivery = _delivery_result(subscriptions, results)
        logger.info(
            f"Notification clear session={session_id} notif_id={notif_id}"
            + f" delivered={len(delivery.delivered_subscription_ids)}"
            + f" subscriptions={len(delivery.attempted_subscription_ids)}"
        )
        return delivery

    async def dispatch_test(self, *, subscription: NotificationSubscription) -> bool:
        device_name = subscription.device_name or "this browser"
        payload = NotificationPayload(
            kind="notification_test",
            notif_id=f"test:{subscription.id}",
            title="Test notification",
            body=f"Push notifications are configured for {device_name}.",
            session_id="",
            actions=[{"action": "open", "title": "Open app"}],
        )
        results = await self._sender.send_batch([subscription], payload)
        delivered = results.get(subscription.id, False)
        logger.info(f"Notification test subscription={subscription.id} delivered={delivered}")
        return delivered

    async def _dispatch(
        self,
        *,
        session_id: str,
        kind: Literal[
            "escalation_pending",
            "attended_turn_completed",
            "unattended_turn_completed",
            "unattended_turn_failed",
        ],
        payload: NotificationPayload,
        suppress_when_active: bool,
    ) -> NotificationDeliveryResult:
        self._store.cleanup_expired()
        if suppress_when_active and self._presence.is_session_actively_handled(session_id):
            logger.info(
                f"Notification suppressed session={session_id} kind={kind}"
                + f" reason=active_presence notif_id={payload.notif_id}"
            )
            return NotificationDeliveryResult(attempted_subscription_ids=set(), delivered_subscription_ids=set())

        all_subscriptions = self._subscriptions_for_session(session_id)
        subscriptions = [
            subscription
            for subscription in all_subscriptions
            if _preferences_allow(subscription.notification_prefs, kind)
        ]
        if not subscriptions:
            return NotificationDeliveryResult(attempted_subscription_ids=set(), delivered_subscription_ids=set())

        results = await self._sender.send_batch(subscriptions, payload)
        delivery = _delivery_result(subscriptions, results)
        logger.info(
            f"Notification dispatch session={session_id} kind={kind}"
            + f" notif_id={payload.notif_id} delivered={len(delivery.delivered_subscription_ids)}"
            + f" subscriptions={len(delivery.attempted_subscription_ids)}"
        )
        return delivery

    def _subscriptions_for_session(self, session_id: str) -> list[NotificationSubscription]:
        owner = self._owner_for_session(session_id)
        return self._store.list_subscriptions(user=owner)


def _delivery_result(
    subscriptions: list[NotificationSubscription],
    results: dict[str, bool],
) -> NotificationDeliveryResult:
    attempted_subscription_ids = {subscription.id for subscription in subscriptions}
    delivered_subscription_ids = {
        subscription_id
        for subscription_id, sent in results.items()
        if sent and subscription_id in attempted_subscription_ids
    }
    return NotificationDeliveryResult(
        attempted_subscription_ids=attempted_subscription_ids,
        delivered_subscription_ids=delivered_subscription_ids,
    )


def _preferences_allow(
    prefs: NotificationPreferences,
    kind: Literal[
        "escalation_pending",
        "attended_turn_completed",
        "unattended_turn_completed",
        "unattended_turn_failed",
    ],
) -> bool:
    return getattr(prefs, kind)
