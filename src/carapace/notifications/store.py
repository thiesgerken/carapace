from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select

from ..database.engine import SessionFactory, affected_rows
from ..database.models import NotificationSubscriptionRow
from .models import NotificationPreferences, NotificationSubscription


def _to_row(subscription: NotificationSubscription) -> NotificationSubscriptionRow:
    return NotificationSubscriptionRow(
        id=subscription.id,
        user=subscription.user,
        endpoint=subscription.endpoint,
        expires_at=subscription.expires_at,
        data=subscription,
    )


def _to_model(row: NotificationSubscriptionRow) -> NotificationSubscription:
    return row.data


class NotificationStore:
    def __init__(self, session_factory: SessionFactory):
        self._session_factory = session_factory

    def get_subscription(self, subscription_id: str) -> NotificationSubscription | None:
        with self._session_factory() as db:
            row = db.get(NotificationSubscriptionRow, subscription_id)
            return _to_model(row) if row is not None else None

    def list_subscriptions(
        self,
        *,
        user: str | None = None,
    ) -> list[NotificationSubscription]:
        stmt = select(NotificationSubscriptionRow).order_by(NotificationSubscriptionRow.id)
        if user is not None:
            stmt = stmt.where(NotificationSubscriptionRow.user == user)
        with self._session_factory() as db:
            rows = db.scalars(stmt).all()
        return [_to_model(row) for row in rows]

    def find_by_endpoint(self, *, user: str, endpoint: str) -> NotificationSubscription | None:
        normalized_endpoint = endpoint.strip()
        with self._session_factory() as db:
            row = db.scalars(
                select(NotificationSubscriptionRow).where(
                    NotificationSubscriptionRow.user == user,
                    NotificationSubscriptionRow.endpoint == normalized_endpoint,
                )
            ).first()
        return _to_model(row) if row is not None else None

    def save_subscription(self, subscription: NotificationSubscription) -> NotificationSubscription:
        with self._session_factory.begin() as db:
            db.merge(_to_row(subscription))
        return subscription

    def delete_subscription(self, subscription_id: str) -> bool:
        with self._session_factory.begin() as db:
            result = db.execute(
                delete(NotificationSubscriptionRow).where(NotificationSubscriptionRow.id == subscription_id)
            )
            return affected_rows(result) > 0

    def cleanup_expired(self, *, now: datetime | None = None) -> list[str]:
        current = now or datetime.now(tz=UTC)
        with self._session_factory.begin() as db:
            rows = db.scalars(
                select(NotificationSubscriptionRow).where(NotificationSubscriptionRow.expires_at <= current)
            ).all()
            deleted = [row.id for row in rows]
            for row in rows:
                db.delete(row)
        return deleted

    def upsert_subscription(
        self,
        *,
        user: str,
        endpoint: str,
        p256dh: str,
        auth: str,
        device_name: str,
        notification_prefs: NotificationPreferences,
        ttl: timedelta,
        now: datetime | None = None,
    ) -> NotificationSubscription:
        current = now or datetime.now(tz=UTC)
        existing = self.find_by_endpoint(user=user, endpoint=endpoint)
        if existing is None:
            subscription = NotificationSubscription(
                id=uuid.uuid4().hex,
                user=user,
                device_name=device_name,
                endpoint=endpoint,
                p256dh=p256dh,
                auth=auth,
                notification_prefs=notification_prefs,
                subscribed_at=current,
                last_heartbeat=current,
                expires_at=current + ttl,
            )
        else:
            subscription = existing.model_copy(
                update={
                    "device_name": device_name,
                    "p256dh": p256dh,
                    "auth": auth,
                    "notification_prefs": notification_prefs,
                    "last_heartbeat": current,
                    "expires_at": current + ttl,
                }
            )
        return self.save_subscription(subscription)
