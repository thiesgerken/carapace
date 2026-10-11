import assert from "node:assert/strict";
import test from "node:test";
import { NextIntlClientProvider } from "next-intl";

import messages from "../../messages/en.json";
import { click, installDom, renderReact, runInAct } from "../../test/react-test-utils";
import type { MemoryStatus } from "@/lib/types";

import { MemoryRunDialog } from "./memory-run-dialog";
import { MemoryStatusProvider } from "./memory-status";

const SERVER = "https://carapace.example.test";

const STATUS: MemoryStatus = {
  auto_mode: false,
  timezone: "Europe/Berlin",
  day: { window_start: "2026-09-03T22:00:00Z", spent_cost_usd: "0", spent_input_tokens: 0, limit_cost_usd: "1.00", limit_input_tokens: null },
  month: { window_start: "2026-08-31T22:00:00Z", spent_cost_usd: "0", spent_input_tokens: 0, limit_cost_usd: "10.00", limit_input_tokens: null },
  queue: { pending: 0, queued: 0, running: 0, done: 0, failed: 2, cancelled: 0 },
  blocked: 0,
  models: { memory_low: "haiku", memory_high: "opus" },
  sessions_without_transcript: 0,
};

const EMPTY_ESTIMATE = { task_count: 0, input_tokens: 0, output_tokens_cap: 0, cost_usd: "0", unpriced_count: 0 };

test("a selection without pending tasks says so, and re-picking the current model keeps the estimate", async () => {
  const restore = installDom();
  const originalFetch = globalThis.fetch;
  // jsdom has no <dialog> modality.
  window.HTMLDialogElement.prototype.showModal = function showModal(this: HTMLDialogElement) {
    this.open = true;
  };
  let estimates = 0;
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    const path = new URL(String(input)).pathname;
    if (path === "/api/memory/tasks/estimate") estimates += 1;
    const body = {
      "/api/memory/status": STATUS,
      "/api/memory/tasks/estimate": EMPTY_ESTIMATE,
      "/api/models": [],
    }[path];
    assert.ok(body !== undefined, `unexpected request ${path}`);
    return new Response(JSON.stringify(body), { headers: { "Content-Type": "application/json" } });
  }) as typeof fetch;

  try {
    const view = await renderReact(
      <NextIntlClientProvider locale="en" messages={messages} timeZone="UTC">
        <MemoryStatusProvider server={SERVER}>
          <MemoryRunDialog server={SERVER} token="" selection={{ ids: [17, 18] }} kinds={["week_digest"]} onClose={() => {}} onQueued={() => {}} />
        </MemoryStatusProvider>
      </NextIntlClientProvider>,
    );
    const settle = () => runInAct(() => new Promise((resolve) => setTimeout(resolve, 0)));
    await settle();
    const text = () => view.container.textContent ?? "";
    const runButton = () => Array.from(view.container.querySelectorAll("button")).find((element) => element.textContent?.trim() === "Run");

    assert.match(text(), /No pending tasks in this selection\./);
    assert.equal(runButton()?.disabled, true);

    const trigger = Array.from(view.container.querySelectorAll("button")).find((element) => element.textContent?.includes("Role default (opus)"));
    assert.ok(trigger);
    await click(trigger);
    await click(view.container.querySelector('[role="option"]')!);
    await settle();

    assert.doesNotMatch(text(), /Estimating/);
    assert.match(text(), /No pending tasks in this selection\./);
    assert.equal(estimates, 1);

    await view.unmount();
  } finally {
    globalThis.fetch = originalFetch;
    restore();
  }
});
