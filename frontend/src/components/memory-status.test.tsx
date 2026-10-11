import assert from "node:assert/strict";
import test from "node:test";
import { NextIntlClientProvider } from "next-intl";

import messages from "../../messages/en.json";
import { click, installDom, renderReact, runInAct } from "../../test/react-test-utils";
import type { MemoryStatus, MemoryTaskKindCounts } from "@/lib/types";

import { MemoryStatusProvider, MemoryStatusStrip } from "./memory-status";

const SERVER = "https://carapace.example.test";

function status(outdated: MemoryTaskKindCounts): MemoryStatus {
  return {
    auto_mode: true,
    timezone: "Europe/Berlin",
    day: { window_start: "2026-09-03T22:00:00Z", spent_cost_usd: "0", spent_input_tokens: 0, limit_cost_usd: "1.00", limit_input_tokens: null },
    month: { window_start: "2026-08-31T22:00:00Z", spent_cost_usd: "0", spent_input_tokens: 0, limit_cost_usd: "10.00", limit_input_tokens: null },
    queue: { pending: 0, queued: 0, running: 0, done: 0, failed: 0, cancelled: 0 },
    blocked: 0,
    models: { memory_low: "haiku", memory_high: "opus" },
    sessions_without_transcript: 0,
    outdated,
  };
}

test("refreshing outdated records confirms, spawns once and reports the created tasks", async () => {
  const restore = installDom();
  // next/link's prefetch observer reaches for `self`, which jsdom globals don't install.
  Object.defineProperty(globalThis, "self", { configurable: true, writable: true, value: window });
  const originalFetch = globalThis.fetch;
  const created = { session_extract: 3, week_digest: 1, month_digest: 0 };
  let spawns = 0;
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = new URL(String(input)).pathname;
    if (path === "/api/memory/tasks/spawn-outdated") {
      assert.equal(init?.method, "POST");
      spawns += 1;
      return Response.json(created);
    }
    assert.equal(path, "/api/memory/status", `unexpected request ${path}`);
    return Response.json(status(spawns ? { session_extract: 0, week_digest: 0, month_digest: 0 } : created));
  }) as typeof fetch;

  try {
    const view = await renderReact(
      <NextIntlClientProvider locale="en" messages={messages} timeZone="UTC">
        <MemoryStatusProvider server={SERVER}>
          <MemoryStatusStrip server={SERVER} />
        </MemoryStatusProvider>
      </NextIntlClientProvider>,
    );
    const settle = () => runInAct(() => new Promise((resolve) => setTimeout(resolve, 0)));
    await settle();
    const text = () => view.container.textContent ?? "";
    const button = (label: string) => {
      const found = Array.from(view.container.querySelectorAll("button")).find((element) => element.textContent?.trim() === label);
      assert.ok(found, `no button ${label}`);
      return found;
    };

    await click(button("Refresh 4 outdated records"));
    assert.match(text(), /Create 4 pending tasks\? Auto mode queues them right away\./);
    await click(button("Cancel"));
    assert.equal(spawns, 0);

    await click(button("Refresh 4 outdated records"));
    await click(button("Create"));
    await settle();
    assert.equal(spawns, 1);
    assert.match(text(), /Created 3 extraction tasks and 1 digest task\./);
    assert.equal(button("Refresh 0 outdated records").disabled, true);
    await view.unmount();
  } finally {
    globalThis.fetch = originalFetch;
    delete (globalThis as { self?: unknown }).self;
    restore();
  }
});
