import assert from "node:assert/strict";
import test from "node:test";
import { PathnameContext } from "next/dist/shared/lib/hooks-client-context.shared-runtime";
import { NextIntlClientProvider } from "next-intl";

import english from "../../messages/en.json";
import { click, installDom, renderReact, runInAct } from "../../test/react-test-utils";
import type { SessionInfo } from "@/lib/types";
import { LocaleProvider } from "./locale-provider";
import { Sidebar } from "./sidebar";

const session: SessionInfo = {
  session_id: "demo-1",
  channel_type: "web",
  channel_ref: null,
  created_at: "2026-11-26T08:00:00Z",
  last_active: new Date().toISOString(),
  title: "Plan the garden",
  attributes: { private: false, archived: false, pinned: true, favorite: false, unattended: false, ask_mode: false, yolo_mode: false },
  budget: {},
  activated_rules: [],
  disabled_rules: [],
  message_count: 3,
  sandbox: { exists: true, status: "running", storage_present: true, last_measured_used_bytes: 77 * 1024 * 1024 },
};

test("a session row is a title and one meta line, with its actions behind a ⋯ menu that never opens the row", async () => {
  const restore = installDom();
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async () => new Response(JSON.stringify({ configured: false }))) as typeof fetch;
  try {
    const calls: string[] = [];
    const view = await renderReact(
      <PathnameContext.Provider value="/">
        <LocaleProvider>
          <NextIntlClientProvider locale="en" messages={english} timeZone="UTC">
            <Sidebar
              server=""
              token="demo"
              sessions={[session]}
              activeSessionId={null}
              onSelect={(id) => calls.push(`select ${id}`)}
              onNew={() => {}}
              onNavigate={() => {}}
              onUpdateAttributes={async (id, attributes) => {
                calls.push(`update ${id} ${JSON.stringify(attributes)}`);
                return session;
              }}
              onSetArchived={async (id, archived) => void calls.push(`archived ${id} ${archived}`)}
              onDelete={async () => {}}
              onDisconnect={() => {}}
              githubUrl="https://github.com/thiesgerken/carapace"
            />
          </NextIntlClientProvider>
        </LocaleProvider>
      </PathnameContext.Provider>,
    );
    const row = view.container.querySelector('[role="button"][aria-pressed]')!;
    const [titleLine, metaLine] = Array.from(row.children);
    assert.equal(titleLine.textContent, "Plan the gardenPinned session");
    // The message count is followed by its screen reader label.
    assert.equal(metaLine.textContent, "77 MB·33 messages·just now");

    const trigger = row.querySelector('button[aria-haspopup="menu"]')!;
    await runInAct(() => {
      trigger.dispatchEvent(new window.KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    });
    await click(trigger);
    const archive = Array.from(row.querySelectorAll('[role="menuitem"]')).find((item) => item.textContent === "Archive session")!;
    await click(archive);
    assert.deepEqual(calls, ["archived demo-1 true"]);

    await click(titleLine);
    assert.deepEqual(calls, ["archived demo-1 true", "select demo-1"]);
    await view.unmount();
  } finally {
    globalThis.fetch = originalFetch;
    restore();
  }
});
