self.addEventListener("install", (event) => {
  event.waitUntil(self.skipWaiting());
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

function parsePushPayload(event) {
  if (!event.data) return null;

  try {
    return event.data.json();
  } catch {
    try {
      return JSON.parse(event.data.text());
    } catch {
      return null;
    }
  }
}

function targetUrl(sessionId, eventIndex) {
  const url = new URL("/", self.location.origin);
  if (sessionId) {
    url.searchParams.set("session", sessionId);
    if (typeof eventIndex === "number") {
      url.searchParams.set("event", String(eventIndex));
    }
  }
  return url.toString();
}

async function focusOrOpenSession(sessionId, eventIndex) {
  const destination = targetUrl(sessionId, eventIndex);
  const windowClients = await self.clients.matchAll({
    type: "window",
    includeUncontrolled: true,
  });

  for (const client of windowClients) {
    const url = new URL(client.url);
    if (url.origin !== self.location.origin) continue;
    if (!sessionId || url.searchParams.get("session") === sessionId) {
      if (typeof client.focus === "function") {
        await client.focus();
      }
      if (
        url.toString() !== destination &&
        typeof client.navigate === "function"
      ) {
        await client.navigate(destination);
      }
      return;
    }
  }

  if (windowClients.length > 0) {
    const client = windowClients[0];
    if (typeof client.focus === "function") {
      await client.focus();
    }
    if (typeof client.navigate === "function") {
      await client.navigate(destination);
    }
    return;
  }

  await self.clients.openWindow(destination);
}

async function closeNotificationsByTag(tag) {
  if (!tag) return;
  const notifications = await self.registration.getNotifications({ tag });
  for (const notification of notifications) {
    notification.close();
  }
}

self.addEventListener("push", (event) => {
  event.waitUntil(
    (async () => {
      const payload = parsePushPayload(event);
      if (!payload || typeof payload !== "object") {
        console.debug("[carapace-sw] push ignored: invalid payload");
        return;
      }

      const tag =
        payload.kind === "notification_test"
          ? undefined
          : payload.tag || payload.notif_id;
      const requireInteraction =
        payload.kind === "escalation_pending" ||
        payload.kind === "notification_test";
      if (payload.kind === "notification_clear") {
        console.debug("[carapace-sw] clear notification", {
          tag: tag || null,
        });
        await closeNotificationsByTag(tag);
        return;
      }

      console.debug("[carapace-sw] show notification", {
        kind: payload.kind || null,
        notifId: payload.notif_id || null,
        title: payload.title || "carapace",
        tag: tag || null,
        sessionId: payload.session_id || null,
        requireInteraction,
      });
      await self.registration.showNotification(payload.title || "carapace", {
        body: payload.body || "",
        tag,
        icon: payload.icon || "/pwa-192x192.png",
        badge:
          payload.badge && payload.badge !== "/badge-icon.png"
            ? payload.badge
            : "/pwa-192x192.png",
        actions: Array.isArray(payload.actions) ? payload.actions : [],
        requireInteraction,
        data: {
          sessionId: payload.session_id || null,
          eventIndex: payload.event_index ?? null,
          notifId: payload.notif_id || null,
        },
      });
    })(),
  );
});

self.addEventListener("notificationclick", (event) => {
  console.debug("[carapace-sw] click notification", {
    sessionId: event.notification.data?.sessionId || null,
    notifId: event.notification.data?.notifId || null,
  });
  event.notification.close();
  event.waitUntil(
    focusOrOpenSession(
      event.notification.data?.sessionId || null,
      event.notification.data?.eventIndex ?? null,
    ),
  );
});
