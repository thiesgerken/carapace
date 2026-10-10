import assert from "node:assert/strict";
import test from "node:test";
import { NextIntlClientProvider } from "next-intl";

import messages from "../../messages/en.json";
import { click, installDom, renderReact, runInAct } from "../../test/react-test-utils";
import type { MemoryStatus, MemoryTaskListResponse, MemoryTaskView } from "@/lib/types";

import { MemoryStatusProvider } from "./memory-status";
import { MemoryTasksView } from "./memory-tasks-view";

const SERVER = "https://carapace.example.test";

function task(id: number, target_label: string): MemoryTaskView {
  return {
    id,
    user: "ada",
    kind: "session_extract",
    target: `session-${id}`,
    target_label,
    status: "pending",
    week_key: "2026-W36",
    month_key: "2026-09",
    model: "haiku",
    blocked_reason: null,
    spawned_by: "auto",
    model_override: null,
    attempts: 0,
    estimate: { model: "haiku", input_tokens: 1200, output_tokens_cap: 800, cost_usd: "0.003" },
    provenance: null,
    result_id: null,
    error: null,
    created_at: "2026-09-04T10:00:00Z",
    queued_at: null,
    started_at: null,
    finished_at: null,
  };
}

const STATUS: MemoryStatus = {
  auto_mode: false,
  timezone: "Europe/Berlin",
  day: { window_start: "2026-09-03T22:00:00Z", spent_cost_usd: "0.42", spent_input_tokens: 0, limit_cost_usd: "1.00", limit_input_tokens: null },
  month: { window_start: "2026-08-31T22:00:00Z", spent_cost_usd: "3.10", spent_input_tokens: 0, limit_cost_usd: "10.00", limit_input_tokens: null },
  queue: { pending: 120, queued: 0, running: 0, done: 0, failed: 0, cancelled: 0 },
  blocked: 0,
  models: { memory_low: "haiku", memory_high: "opus" },
  sessions_without_transcript: 0,
};

const TASKS: MemoryTaskListResponse = {
  items: [task(1, "Weekend trip"), task(2, "Talos upgrade")],
  next_cursor: "page-2",
  total: 120,
  estimate: { task_count: 120, input_tokens: 144000, output_tokens_cap: 96000, cost_usd: "0.36", unpriced_count: 0 },
};

const ESTIMATE = { task_count: 120, input_tokens: 144000, output_tokens_cap: 96000, cost_usd: "0.36", unpriced_count: 0 };

test("select all matching runs the whole filter, not just the visible page", async () => {
  const restore = installDom();
  const originalFetch = globalThis.fetch;
  // jsdom has no <dialog> modality.
  window.HTMLDialogElement.prototype.showModal = function showModal(this: HTMLDialogElement) {
    this.open = true;
  };
  const posts: { path: string; body: unknown }[] = [];
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = new URL(String(input)).pathname;
    if (init?.method === "POST") posts.push({ path, body: JSON.parse(String(init.body)) });
    const body = {
      "/api/memory/status": STATUS,
      "/api/memory/tasks": TASKS,
      "/api/memory/tasks/estimate": ESTIMATE,
      "/api/memory/tasks/run": { count: 120 },
      "/api/models": [],
    }[path];
    assert.ok(body !== undefined, `unexpected request ${path}`);
    return new Response(JSON.stringify(body), { headers: { "Content-Type": "application/json" } });
  }) as typeof fetch;

  try {
    const view = await renderReact(
      <NextIntlClientProvider locale="en" messages={messages} timeZone="UTC">
        <MemoryStatusProvider server={SERVER}>
          <MemoryTasksView server={SERVER} token="" />
        </MemoryStatusProvider>
      </NextIntlClientProvider>,
    );
    const settle = () => runInAct(() => new Promise((resolve) => setTimeout(resolve, 0)));
    await settle();
    const text = () => view.container.textContent ?? "";
    const button = (label: string) => {
      const match = Array.from(view.container.querySelectorAll("button")).find((element) => element.textContent?.trim() === label);
      assert.ok(match, `no button "${label}"`);
      return match;
    };

    assert.match(text(), /Weekend trip/);
    assert.match(text(), /120 matching · est\. \$0\.36/);

    await click(view.container.querySelector('input[aria-label="Select all tasks on this page"]')!);
    button("Run selected (2)");

    await click(button("Select all 120 matching"));
    assert.match(text(), /All 120 matching are selected\./);

    await click(button("Run selected (120)"));
    await settle();
    const filter = { status: ["pending"], kind: null, period: null, model: null };
    assert.deepEqual(posts.at(-1), { path: "/api/memory/tasks/estimate", body: { selection: { filter }, model_override: null } });

    await click(button("Run"));
    await settle();
    assert.deepEqual(posts.at(-1), { path: "/api/memory/tasks/run", body: { selection: { filter }, model_override: null } });
    assert.match(text(), /Queued 120 tasks\./);

    await view.unmount();
  } finally {
    globalThis.fetch = originalFetch;
    restore();
  }
});
