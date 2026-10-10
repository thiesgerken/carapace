import assert from "node:assert/strict";
import test from "node:test";
import { NextIntlClientProvider } from "next-intl";

import messages from "../../messages/en.json";
import { click, installDom, renderReact, runInAct } from "../../test/react-test-utils";
import type { MemoryDigestRecord, MemoryPeriodDetail, MemoryStatus } from "@/lib/types";

import { MemoryPeriodDetailView } from "./memory-period-detail";
import { MemoryStatusProvider } from "./memory-status";

const SERVER = "https://carapace.example.test";

function digest(id: number, model: string, summary: string): MemoryDigestRecord {
  return {
    id,
    level: "week",
    period_key: "2026-W36",
    is_current: id === 2,
    coverage: [{ source_id: "s1", source_hash: "h1" }],
    coverage_hash: "c",
    provenance: {
      carapace_version: "0.158.7",
      model,
      prompt_version: "a1b2c3",
      input_format_version: 1,
      input_hash: "abc",
      input_tokens: 9000,
      output_tokens: 800,
      cost_usd: "0.08",
      duration_ms: 12000,
      task_id: id,
      created_at: "2026-09-08T07:12:00Z",
    },
    digest: {
      summary,
      on_my_mind: [{ theme: "Talos upgrade", refs: ["s1"] }],
      highlights: [],
      open_loops: [],
      learned: [{
        category: "user",
        statement: "Prefers dry runs before upgrades.",
        subject: null,
        source_kind: "user_said",
        confidence: "high",
        durability: "durable",
        valid_until: null,
        refs: ["s1"],
      }],
    },
    created_at: "2026-09-08T07:12:00Z",
  };
}

const DETAIL: MemoryPeriodDetail = {
  node: {
    level: "week",
    key: "2026-W36",
    start: "2026-08-31",
    end: "2026-09-06",
    covered: 1,
    total: 1,
    digest: { id: 2, model: "opus", prompt_version: "a1b2c3", carapace_version: "0.158.7", cost_usd: "0.08", created_at: "2026-09-08T07:12:00Z", outdated: [] },
    stale: false,
    task: null,
  },
  current: digest(2, "opus", "Mostly infra work on the homelab cluster."),
  history: [digest(1, "sonnet", "Homelab work.")],
  sessions: [{
    session_id: "s1",
    title: "Talos upgrade dry run",
    channel_type: "web",
    created_at: "2026-09-02T10:00:00Z",
    week_key: "2026-W36",
    extraction: null,
    task: null,
  }],
  weeks: [],
};

const STATUS: MemoryStatus = {
  auto_mode: false,
  timezone: "Europe/Berlin",
  day: { window_start: "2026-09-07T22:00:00Z", spent_cost_usd: "0", spent_input_tokens: 0, limit_cost_usd: null, limit_input_tokens: null },
  month: { window_start: "2026-08-31T22:00:00Z", spent_cost_usd: "0", spent_input_tokens: 0, limit_cost_usd: null, limit_input_tokens: null },
  queue: { pending: 0, queued: 0, running: 0, done: 0, failed: 0, cancelled: 0 },
  blocked: 0,
  models: { memory_low: "haiku", memory_high: "opus" },
  sessions_without_transcript: 0,
};

test("week detail links refs to sessions, keeps history collapsed and regenerates via spawn + run dialog", async () => {
  const restore = installDom();
  // next/link's prefetch observer reaches for `self`, which jsdom globals don't install.
  Object.defineProperty(globalThis, "self", { configurable: true, writable: true, value: window });
  window.HTMLDialogElement.prototype.showModal = function showModal(this: HTMLDialogElement) {
    this.open = true;
  };
  const originalFetch = globalThis.fetch;
  const posts: { path: string; body: unknown }[] = [];
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = new URL(String(input)).pathname;
    if (init?.method === "POST") posts.push({ path, body: JSON.parse(String(init.body)) });
    const body = {
      "/api/memory/status": STATUS,
      "/api/memory/periods/week/2026-W36": DETAIL,
      "/api/memory/tasks/spawn": { task_ids: [77] },
      "/api/memory/tasks/estimate": { task_count: 1, input_tokens: 9000, output_tokens_cap: 2000, cost_usd: "0.09", unpriced_count: 0 },
      "/api/models": [],
    }[path];
    assert.ok(body !== undefined, `unexpected request ${path}`);
    return new Response(JSON.stringify(body));
  }) as typeof fetch;

  try {
    const view = await renderReact(
      <NextIntlClientProvider locale="en" messages={messages} timeZone="UTC">
        <MemoryStatusProvider server={SERVER}>
          <MemoryPeriodDetailView server={SERVER} token="" periodKey="2026-W36" />
        </MemoryStatusProvider>
      </NextIntlClientProvider>,
    );
    const settle = () => runInAct(() => new Promise((resolve) => setTimeout(resolve, 0)));
    await settle();

    assert.match(view.container.textContent ?? "", /Mostly infra work/);
    const themeRef = Array.from(view.container.querySelectorAll("li")).find((item) => item.textContent?.startsWith("Talos upgrade"))?.querySelector("a");
    assert.equal(themeRef?.getAttribute("href"), "/memory/sessions?session=s1");
    assert.equal(themeRef?.textContent, "Talos upgrade dry run");
    const history = view.container.querySelector("details");
    assert.ok(history && !history.open);
    assert.match(history.textContent ?? "", /sonnet · carapace 0\.158\.7/);

    const regenerate = Array.from(view.container.querySelectorAll("button")).find((button) => button.textContent?.trim() === "Regenerate");
    await click(regenerate!);
    await settle();
    assert.deepEqual(posts[0], { path: "/api/memory/tasks/spawn", body: { kind: "week_digest", targets: ["2026-W36"] } });
    assert.deepEqual(posts[1], { path: "/api/memory/tasks/estimate", body: { selection: { ids: [77] }, model_override: null } });
    assert.ok(view.container.querySelector("dialog[open]"));

    await view.unmount();
  } finally {
    globalThis.fetch = originalFetch;
    delete (globalThis as { self?: unknown }).self;
    restore();
  }
});
