"use client";

import { FlaskConical, Loader2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import {
  deleteNotificationSubscription,
  getVapidPublicKey,
  listNotificationSubscriptions,
  sendTestNotification,
  updateNotificationSubscriptionPreferences,
  upsertNotificationSubscription,
} from "@/lib/api";
import {
  buildNotificationDeviceName,
  decodeVapidPublicKey,
  registerNotificationServiceWorker,
  supportsPushNotifications,
} from "@/lib/notifications";
import {
  clearNotificationSubscriptionId,
  getNotificationDeviceName,
  getNotificationSubscriptionId,
  saveNotificationDeviceName,
  saveNotificationSubscriptionId,
} from "@/lib/storage";
import type {
  NotificationPreferences,
  NotificationSubscriptionRecord,
} from "@/lib/types";
import { SwitchRow } from "@/components/switch-row";

type NotificationPreferenceKey = keyof NotificationPreferences;
type NotificationTranslator = (
  key: string,
  values?: Record<string, string>,
) => string;

const PREFERENCE_KEYS: NotificationPreferenceKey[] = [
  "escalation_pending",
  "attended_turn_completed",
  "unattended_turn_completed",
  "unattended_turn_failed",
];

function resolveErrorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

function formatTimestamp(value: string | null | undefined): string | null {
  if (!value) return null;
  const parsed = Date.parse(value);
  if (Number.isNaN(parsed)) return null;
  return new Date(parsed).toLocaleString();
}

function readPushKeys(pushSubscription: PushSubscription): { p256dh: string; auth: string } | null {
  const json = pushSubscription.toJSON() as {
    keys?: {
      p256dh?: string;
      auth?: string;
    };
  };
  const p256dh = json.keys?.p256dh?.trim();
  const auth = json.keys?.auth?.trim();
  if (!p256dh || !auth) return null;
  return { p256dh, auth };
}

function toUint8Array(value: BufferSource | null | undefined): Uint8Array | null {
  if (!value) return null;
  if (value instanceof ArrayBuffer) {
    return new Uint8Array(value);
  }
  if (ArrayBuffer.isView(value)) {
    return new Uint8Array(value.buffer, value.byteOffset, value.byteLength);
  }
  return null;
}

export function pushServerKeysMatch(
  existingKey: BufferSource | null | undefined,
  nextKey: ArrayBuffer,
): boolean {
  const existingBytes = toUint8Array(existingKey);
  const nextBytes = new Uint8Array(nextKey);
  if (!existingBytes) {
    return false;
  }
  if (existingBytes.byteLength !== nextBytes.byteLength) {
    return false;
  }
  for (let index = 0; index < existingBytes.byteLength; index += 1) {
    if (existingBytes[index] !== nextBytes[index]) {
      return false;
    }
  }
  return true;
}

export async function ensureCurrentPushSubscription(
  registration: ServiceWorkerRegistration,
  applicationServerKey: ArrayBuffer,
): Promise<PushSubscription> {
  let pushSubscription = await registration.pushManager.getSubscription();
  if (
    pushSubscription &&
    !pushServerKeysMatch(
      pushSubscription.options.applicationServerKey,
      applicationServerKey,
    )
  ) {
    await pushSubscription.unsubscribe();
    pushSubscription = null;
  }
  if (!pushSubscription) {
    pushSubscription = await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey,
    });
  }
  return pushSubscription;
}

export function NotificationSubscription({
  server,
  token,
  translate,
}: {
  server: string;
  token: string;
  translate?: NotificationTranslator;
}) {
  if (translate) {
    return (
      <NotificationSubscriptionContent
        server={server}
        token={token}
        translate={translate}
      />
    );
  }

  return <TranslatedNotificationSubscription server={server} token={token} />;
}

function TranslatedNotificationSubscription({
  server,
  token,
}: {
  server: string;
  token: string;
}) {
  const t = useTranslations("preferences.notifications");
  return (
    <NotificationSubscriptionContent
      server={server}
      token={token}
      translate={t}
    />
  );
}

function NotificationSubscriptionContent({
  server,
  token,
  translate: t,
}: {
  server: string;
  token: string;
  translate: NotificationTranslator;
}) {
  const [pushSupported] = useState(() => supportsPushNotifications());
  const [permission, setPermission] = useState<NotificationPermission>(() => (
    typeof Notification === "undefined" ? "default" : Notification.permission
  ));
  const [subscription, setSubscription] = useState<NotificationSubscriptionRecord | null>(null);
  const [deviceName, setDeviceName] = useState(() => getNotificationDeviceName() || buildNotificationDeviceName());
  const [loading, setLoading] = useState(() => Boolean(server && token && pushSupported));
  const [busyAction, setBusyAction] = useState<"enable" | "disable" | "preferences" | "test" | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const loadFailedMessageRef = useRef(t("status.loadFailed"));
  const saving = busyAction !== null;
  const canManageNotifications = Boolean(server && token && pushSupported);

  useEffect(() => {
    loadFailedMessageRef.current = t("status.loadFailed");
  }, [t]);

  useEffect(() => {
    let cancelled = false;

    const fallbackDeviceName = getNotificationDeviceName() || buildNotificationDeviceName();

    if (!canManageNotifications) {
      return () => {
        cancelled = true;
      };
    }

    async function loadSubscription(): Promise<void> {
      try {
        setLoading(true);
        const registration = await registerNotificationServiceWorker();
        const browserSubscription = await registration?.pushManager.getSubscription() ?? null;
        const subscriptions = await listNotificationSubscriptions(server, token);
        const storedSubscriptionId = getNotificationSubscriptionId();
        let activeSubscription = subscriptions.find(
          (candidate) => candidate.subscription_id === storedSubscriptionId,
        ) ?? null;
        if (!activeSubscription && browserSubscription) {
          activeSubscription = subscriptions.find(
            (candidate) => candidate.endpoint === browserSubscription.endpoint,
          ) ?? null;
        }

        if (cancelled) {
          return;
        }

        if (activeSubscription) {
          saveNotificationSubscriptionId(activeSubscription.subscription_id);
          saveNotificationDeviceName(activeSubscription.device_name);
          setDeviceName(activeSubscription.device_name || fallbackDeviceName);
        } else {
          clearNotificationSubscriptionId();
        }

        setSubscription(activeSubscription);
        setError("");
      } catch (nextError) {
        if (cancelled) {
          return;
        }
        setError(resolveErrorMessage(nextError, loadFailedMessageRef.current));
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void loadSubscription();

    return () => {
      cancelled = true;
    };
  }, [canManageNotifications, pushSupported, server, token]);

  useEffect(() => {
    const refreshPermission = () => {
      if (typeof Notification !== "undefined") {
        setPermission(Notification.permission);
      }
    };

    window.addEventListener("focus", refreshPermission);
    return () => {
      window.removeEventListener("focus", refreshPermission);
    };
  }, []);

  async function handleEnableNotifications() {
    if (!server || !token) return;

    setBusyAction("enable");
    setError("");
    setNotice("");
    try {
      const registration = await registerNotificationServiceWorker();
      if (!registration) {
        throw new Error(t("status.unsupported"));
      }

      let nextPermission = Notification.permission;
      if (nextPermission !== "granted") {
        nextPermission = await Notification.requestPermission();
      }
      setPermission(nextPermission);
      if (nextPermission !== "granted") {
        throw new Error(
          nextPermission === "denied"
            ? t("status.permissionDenied")
            : t("status.permissionRequired"),
        );
      }

      const vapidPublicKey = await getVapidPublicKey(server);
      const applicationServerKey = decodeVapidPublicKey(vapidPublicKey);
      const pushSubscription = await ensureCurrentPushSubscription(
        registration,
        applicationServerKey,
      );

      const pushKeys = readPushKeys(pushSubscription);
      if (!pushKeys) {
        throw new Error(t("status.invalidSubscription"));
      }

      const nextDeviceName = deviceName.trim() || buildNotificationDeviceName();
      const saved = await upsertNotificationSubscription(server, token, {
        endpoint: pushSubscription.endpoint,
        p256dh: pushKeys.p256dh,
        auth: pushKeys.auth,
        device_name: nextDeviceName,
        preferences: subscription?.preferences,
      });

      saveNotificationSubscriptionId(saved.subscription_id);
      saveNotificationDeviceName(saved.device_name);
      setDeviceName(saved.device_name);
      setSubscription(saved);
    } catch (nextError) {
      setError(resolveErrorMessage(nextError, t("status.enableFailed")));
    } finally {
      setBusyAction(null);
    }
  }

  async function handleDisableNotifications() {
    if (!server || !token) return;

    setBusyAction("disable");
    setError("");
    setNotice("");
    try {
      const registration = await registerNotificationServiceWorker();
      const pushSubscription = await registration?.pushManager.getSubscription() ?? null;
      if (pushSubscription) {
        await pushSubscription.unsubscribe();
      }

      const storedSubscriptionId = subscription?.subscription_id || getNotificationSubscriptionId();
      if (storedSubscriptionId) {
        await deleteNotificationSubscription(server, token, storedSubscriptionId);
      }

      clearNotificationSubscriptionId();
      setSubscription(null);
    } catch (nextError) {
      setError(resolveErrorMessage(nextError, t("status.disableFailed")));
    } finally {
      setBusyAction(null);
    }
  }

  async function handlePreferenceChange(
    key: NotificationPreferenceKey,
    value: boolean,
  ) {
    if (!subscription) return;

    setBusyAction("preferences");
    setError("");
    setNotice("");
    try {
      const updated = await updateNotificationSubscriptionPreferences(
        server,
        token,
        subscription.subscription_id,
        { [key]: value },
      );
      setSubscription(updated);
    } catch (nextError) {
      setError(resolveErrorMessage(nextError, t("status.preferencesFailed")));
    } finally {
      setBusyAction(null);
    }
  }

  async function handleTestNotification() {
    if (!subscription) return;

    setBusyAction("test");
    setError("");
    setNotice("");
    try {
      await sendTestNotification(server, token, subscription.subscription_id);
      setNotice(t("status.testSent"));
    } catch (nextError) {
      setError(resolveErrorMessage(nextError, t("status.testFailed")));
    } finally {
      setBusyAction(null);
    }
  }

  const permissionLabel = t(`permission.${permission}`);
  const activeSubscription = canManageNotifications ? subscription : null;
  const visibleError = canManageNotifications ? error : "";
  const visibleLoading = canManageNotifications ? loading : false;
  const lastHeartbeat = formatTimestamp(activeSubscription?.last_heartbeat);
  const expiresAt = formatTimestamp(activeSubscription?.expires_at);
  const notificationsEnabled = Boolean(activeSubscription);
  const notificationsDiagnosticLabel =
    busyAction === "enable"
      ? t("actions.enabling")
      : busyAction === "disable"
      ? t("actions.disabling")
      : visibleLoading
      ? t("status.loading")
      : !pushSupported
      ? t("status.unsupported")
      : permission === "denied"
      ? t("status.permissionDenied")
      : null;
  const notificationsHeaderDescription =
    !notificationsEnabled
      ? visibleError || notificationsDiagnosticLabel || t("description")
      : t("description");

  return (
    <div className="rounded-2xl bg-surface p-4">
      <SwitchRow
        checked={notificationsEnabled}
        label={t("title")}
        description={notificationsHeaderDescription}
        disabled={visibleLoading || saving || (!notificationsEnabled && !pushSupported) || (!notificationsEnabled && permission === "denied")}
        onCheckedChange={(checked) => {
          if (checked) {
            void handleEnableNotifications();
            return;
          }
          void handleDisableNotifications();
        }}
      />

      {notificationsEnabled ? (
        <div className="mt-4 space-y-4">
        <div className="space-y-1.5">
          <label className="block text-xs font-medium text-muted-foreground">
            {t("deviceName.label")}
          </label>
          <input
            value={deviceName}
            onChange={(event) => {
              const nextDeviceName = event.target.value;
              setDeviceName(nextDeviceName);
              saveNotificationDeviceName(nextDeviceName);
            }}
            placeholder={t("deviceName.placeholder")}
            className="w-full rounded-xl border border-border bg-background px-3 py-2.5 text-sm outline-none transition-colors focus:border-ring focus:ring-2 focus:ring-ring/30"
          />
          <p className="text-xs text-muted-foreground">
            {t("deviceName.hint")}
          </p>
        </div>

        <div className="space-y-3 rounded-2xl bg-inset px-4 py-3">
          {notificationsDiagnosticLabel ? (
            <p className="text-xs text-muted-foreground">
              {notificationsDiagnosticLabel}
            </p>
          ) : null}

          <p className="text-xs text-muted-foreground">
            {t("meta.permission", { permission: permissionLabel })}
          </p>
          {lastHeartbeat ? (
            <p className="text-xs text-muted-foreground">
              {t("meta.heartbeat", { timestamp: lastHeartbeat })}
            </p>
          ) : null}
          {expiresAt ? (
            <p className="text-xs text-muted-foreground">
              {t("meta.expires", { timestamp: expiresAt })}
            </p>
          ) : null}
          {visibleError ? (
            <p className="text-sm text-destructive">
              {visibleError}
            </p>
          ) : null}
          {notice ? (
            <p className="text-sm text-success">
              {notice}
            </p>
          ) : null}

          {activeSubscription ? (
            <button
              type="button"
              onClick={handleTestNotification}
              disabled={visibleLoading || saving}
              className="inline-flex min-h-11 items-center justify-center gap-2 self-start rounded-xl border border-border bg-background px-4 py-2.5 text-sm font-medium text-foreground transition-colors hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50"
            >
              {busyAction === "test" ? <Loader2 className="h-4 w-4 animate-spin" /> : <FlaskConical className="h-4 w-4" />}
              {busyAction === "test" ? t("actions.testing") : t("actions.test")}
            </button>
          ) : null}
        </div>

        {activeSubscription ? (
          <fieldset className="space-y-3 rounded-2xl bg-inset p-4">
            <legend className="px-1 text-xs font-medium text-muted-foreground">
              {t("preferences.label")}
            </legend>
            {PREFERENCE_KEYS.map((key) => (
              <SwitchRow
                key={key}
                checked={activeSubscription.preferences[key]}
                label={t(`preferences.${key}`)}
                disabled={saving}
                onCheckedChange={(checked) => handlePreferenceChange(key, checked)}
              />
            ))}
          </fieldset>
        ) : null}
        </div>
      ) : null}
    </div>
  );
}
