import { isInspectorTab, type InspectorTab } from "./inspector-tabs";
import { normalizeServer } from "./server-url";

const SERVER_KEY = "carapace_server";
const USERNAME_KEY = "carapace_username";
const LOCALE_OVERRIDE_KEY = "carapace_locale_override";
const SHOW_ARCHIVED_SESSIONS_KEY = "carapace_show_archived_sessions";
const PRESENCE_CLIENT_ID_KEY = "carapace_presence_client_id";
const CHAT_DRAFT_KEY_PREFIX = "carapace_chat_draft_";
const NOTIFICATION_SUBSCRIPTION_ID_KEY =
  "carapace_notification_subscription_id";
const NOTIFICATION_DEVICE_NAME_KEY = "carapace_notification_device_name";
const INSPECTOR_OPEN_KEY = "carapace_inspector_open";
const INSPECTOR_TAB_KEY = "carapace_inspector_tab";

export type LocaleOverride = "system" | "en" | "de";

export function getServer(): string {
  if (typeof window === "undefined") return "";
  localStorage.removeItem(SERVER_KEY);
  return normalizeServer(window.location.origin);
}

export function getToken(): string {
  if (typeof window === "undefined") return "";
  return localStorage.getItem(USERNAME_KEY) ?? "";
}

export function saveConnection(username: string) {
  localStorage.removeItem(SERVER_KEY);
  localStorage.setItem(USERNAME_KEY, username);
}

export function clearConnection() {
  localStorage.removeItem(SERVER_KEY);
  localStorage.removeItem(USERNAME_KEY);
}

export function hasConnection(): boolean {
  return !!getToken();
}

export function getLocaleOverride(): LocaleOverride {
  if (typeof window === "undefined") return "system";

  const value = localStorage.getItem(LOCALE_OVERRIDE_KEY);
  return value === "en" || value === "de" || value === "system"
    ? value
    : "system";
}

export function saveLocaleOverride(localeOverride: LocaleOverride): void {
  localStorage.setItem(LOCALE_OVERRIDE_KEY, localeOverride);
}

export function getShowArchivedSessionsPreference(): boolean {
  if (typeof window === "undefined") return false;
  return localStorage.getItem(SHOW_ARCHIVED_SESSIONS_KEY) === "true";
}

export function saveShowArchivedSessionsPreference(
  showArchivedSessions: boolean,
): void {
  localStorage.setItem(
    SHOW_ARCHIVED_SESSIONS_KEY,
    showArchivedSessions ? "true" : "false",
  );
}

export function getPresenceClientId(): string {
  if (typeof window === "undefined") return "";

  const existing = window.sessionStorage.getItem(PRESENCE_CLIENT_ID_KEY);
  if (existing) return existing;

  const generated =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID()
      : `presence-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
  window.sessionStorage.setItem(PRESENCE_CLIENT_ID_KEY, generated);
  return generated;
}

// Drafts are written on every keystroke, so unlike the other helpers here they
// have to survive a throwing sessionStorage: a quota overflow or a context that
// blocks site data must not take the composer down with it.
export function getChatDraft(sessionId: string): string {
  if (typeof window === "undefined") return "";
  try {
    return window.sessionStorage.getItem(`${CHAT_DRAFT_KEY_PREFIX}${sessionId}`) ?? "";
  } catch {
    return "";
  }
}

export function saveChatDraft(sessionId: string, draft: string): void {
  if (!draft) {
    clearChatDraft(sessionId);
    return;
  }
  try {
    window.sessionStorage.setItem(`${CHAT_DRAFT_KEY_PREFIX}${sessionId}`, draft);
  } catch {
    // Draft persistence is best effort; losing it beats breaking typing.
  }
}

export function clearChatDraft(sessionId: string): void {
  try {
    window.sessionStorage.removeItem(`${CHAT_DRAFT_KEY_PREFIX}${sessionId}`);
  } catch {
    // Nothing to do: the draft was never stored.
  }
}

export function getNotificationSubscriptionId(): string {
  if (typeof window === "undefined") return "";
  return localStorage.getItem(NOTIFICATION_SUBSCRIPTION_ID_KEY) ?? "";
}

export function saveNotificationSubscriptionId(subscriptionId: string): void {
  localStorage.setItem(NOTIFICATION_SUBSCRIPTION_ID_KEY, subscriptionId);
}

export function clearNotificationSubscriptionId(): void {
  localStorage.removeItem(NOTIFICATION_SUBSCRIPTION_ID_KEY);
}

export function getNotificationDeviceName(): string {
  if (typeof window === "undefined") return "";
  return localStorage.getItem(NOTIFICATION_DEVICE_NAME_KEY) ?? "";
}

export function saveNotificationDeviceName(deviceName: string): void {
  localStorage.setItem(NOTIFICATION_DEVICE_NAME_KEY, deviceName);
}

// The inspector layout is a convenience: without storage (blocked site data, private mode) it starts
// closed on the first tab, and a failed write must not break toggling it.
export function getInspectorOpen(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return localStorage.getItem(INSPECTOR_OPEN_KEY) === "true";
  } catch {
    return false;
  }
}

export function saveInspectorOpen(open: boolean): void {
  try {
    localStorage.setItem(INSPECTOR_OPEN_KEY, open ? "true" : "false");
  } catch {
    // Best effort, see above.
  }
}

export function getInspectorTab(): InspectorTab {
  if (typeof window === "undefined") return "session";
  try {
    const tab = localStorage.getItem(INSPECTOR_TAB_KEY);
    return isInspectorTab(tab) ? tab : "session";
  } catch {
    return "session";
  }
}

export function saveInspectorTab(tab: InspectorTab): void {
  try {
    localStorage.setItem(INSPECTOR_TAB_KEY, tab);
  } catch {
    // Best effort, see above.
  }
}
