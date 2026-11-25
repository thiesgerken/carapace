import assert from "node:assert/strict";
import test from "node:test";
import {
  clearChatDraft,
  clearConnection,
  clearNotificationSubscriptionId,
  getChatDraft,
  getInspectorOpen,
  getInspectorTab,
  getNotificationDeviceName,
  getNotificationSubscriptionId,
  getPresenceClientId,
  getShowArchivedSessionsPreference,
  getServer,
  getToken,
  hasConnection,
  saveChatDraft,
  saveConnection,
  saveInspectorOpen,
  saveInspectorTab,
  saveNotificationDeviceName,
  saveNotificationSubscriptionId,
  saveShowArchivedSessionsPreference,
} from "./storage";

type StorageLike = {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
};

const originalWindow = globalThis.window;
const originalCrypto = globalThis.crypto;
const originalLocalStorage = globalThis.localStorage;
const originalSessionStorage = globalThis.sessionStorage;

function createStorage(): StorageLike {
  const values = new Map<string, string>();
  return {
    getItem(key: string): string | null {
      return values.get(key) ?? null;
    },
    setItem(key: string, value: string): void {
      values.set(key, value);
    },
    removeItem(key: string): void {
      values.delete(key);
    },
  };
}

function setWindow(value: unknown): void {
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    writable: true,
    value,
  });
}

function setCrypto(value: unknown): void {
  Object.defineProperty(globalThis, "crypto", {
    configurable: true,
    writable: true,
    value,
  });
}

test.beforeEach(() => {
  const localStorage = createStorage();
  const sessionStorage = createStorage();
  setWindow({
    localStorage,
    sessionStorage,
    location: { origin: "https://carapace.example.test" },
  });
  Object.defineProperty(globalThis, "localStorage", {
    configurable: true,
    writable: true,
    value: localStorage,
  });
  Object.defineProperty(globalThis, "sessionStorage", {
    configurable: true,
    writable: true,
    value: sessionStorage,
  });
  setCrypto({
    randomUUID: () => "presence-uuid-1",
  });
});

test.afterEach(() => {
  if (originalWindow === undefined) {
    delete (globalThis as { window?: Window }).window;
  } else {
    setWindow(originalWindow);
  }

  if (originalCrypto === undefined) {
    delete (globalThis as { crypto?: Crypto }).crypto;
  } else {
    setCrypto(originalCrypto);
  }

  if (originalLocalStorage === undefined) {
    delete (globalThis as { localStorage?: Storage }).localStorage;
  } else {
    Object.defineProperty(globalThis, "localStorage", {
      configurable: true,
      writable: true,
      value: originalLocalStorage,
    });
  }

  if (originalSessionStorage === undefined) {
    delete (globalThis as { sessionStorage?: Storage }).sessionStorage;
  } else {
    Object.defineProperty(globalThis, "sessionStorage", {
      configurable: true,
      writable: true,
      value: originalSessionStorage,
    });
  }
});

test("connection helpers use same-origin server and username state", () => {
  localStorage.setItem("carapace_server", "https://old.example.test");

  assert.equal(getServer(), "https://carapace.example.test");
  assert.equal(localStorage.getItem("carapace_server"), null);
  assert.equal(hasConnection(), false);

  saveConnection("thies");

  assert.equal(getServer(), "https://carapace.example.test");
  assert.equal(getToken(), "thies");
  assert.equal(hasConnection(), true);
  assert.equal(localStorage.getItem("carapace_server"), null);

  clearConnection();

  assert.equal(getServer(), "https://carapace.example.test");
  assert.equal(getToken(), "");
  assert.equal(hasConnection(), false);
});

test("getPresenceClientId is stable within one browser session", () => {
  const first = getPresenceClientId();
  const second = getPresenceClientId();

  assert.equal(first, "presence-uuid-1");
  assert.equal(second, "presence-uuid-1");
});

test("chat drafts persist per session and can be removed", () => {
  saveChatDraft("session-1", "first draft");
  saveChatDraft("session-2", "second draft");

  assert.equal(getChatDraft("session-1"), "first draft");
  assert.equal(getChatDraft("session-2"), "second draft");

  saveChatDraft("session-1", "");
  clearChatDraft("session-2");

  // Read the store directly: getChatDraft cannot tell a stored "" from a missing key.
  assert.equal(sessionStorage.getItem("carapace_chat_draft_session-1"), null);
  assert.equal(sessionStorage.getItem("carapace_chat_draft_session-2"), null);
});

test("notification subscription helpers persist and clear local state", () => {
  saveNotificationSubscriptionId("sub-1");
  saveNotificationDeviceName("Android Phone");

  assert.equal(getNotificationSubscriptionId(), "sub-1");
  assert.equal(getNotificationDeviceName(), "Android Phone");

  clearNotificationSubscriptionId();

  assert.equal(getNotificationSubscriptionId(), "");
  assert.equal(getNotificationDeviceName(), "Android Phone");
});

test("archived chat visibility preference defaults to hidden and persists", () => {
  assert.equal(getShowArchivedSessionsPreference(), false);

  saveShowArchivedSessionsPreference(true);
  assert.equal(getShowArchivedSessionsPreference(), true);

  saveShowArchivedSessionsPreference(false);
  assert.equal(getShowArchivedSessionsPreference(), false);
});

test("the inspector starts closed on the session tab and remembers open state and tab", () => {
  assert.equal(getInspectorOpen(), false);
  assert.equal(getInspectorTab(), "session");

  saveInspectorOpen(true);
  saveInspectorTab("usage");
  assert.equal(getInspectorOpen(), true);
  assert.equal(getInspectorTab(), "usage");

  localStorage.setItem("carapace_inspector_tab", "gone");
  assert.equal(getInspectorTab(), "session");
});

test("the inspector helpers survive a storage that throws", () => {
  const throwing = {
    getItem(): string | null {
      throw new Error("blocked");
    },
    setItem(): void {
      throw new Error("blocked");
    },
    removeItem(): void {
      throw new Error("blocked");
    },
  };
  Object.defineProperty(globalThis, "localStorage", { configurable: true, writable: true, value: throwing });

  saveInspectorOpen(true);
  saveInspectorTab("content");
  assert.equal(getInspectorOpen(), false);
  assert.equal(getInspectorTab(), "session");
});
