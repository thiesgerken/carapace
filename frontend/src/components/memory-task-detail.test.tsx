import assert from "node:assert/strict";
import test from "node:test";
import { NextIntlClientProvider } from "next-intl";

import messages from "../../messages/en.json";
import { installDom, renderReact, runInAct } from "../../test/react-test-utils";
import type { MemoryDigestRecord, MemoryPeriodDetail, MemoryTaskView } from "@/lib/types";

import { MemoryTaskDetail } from "./memory-task-detail";

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

const MODELS = { memory_low: "haiku", memory_high: "opus" };

function weekDigestTask(resultId: number): MemoryTaskView {
  return {
    id: resultId,
    user: "ada",
    kind: "week_digest",
    target: "2026-W36",
    target_label: "2026-W36",
    dependencies: null,
    status: "done",
    week_key: "2026-W36",
    month_key: "2026-09",
    model: "sonnet",
    blocked_reason: null,
    spawned_by: "auto",
    model_override: null,
    attempts: 1,
    estimate: null,
    provenance: digest(resultId, "sonnet", "").provenance,
    result_id: resultId,
    error: null,
    created_at: "2026-09-08T07:00:00Z",
    queued_at: null,
    started_at: null,
    finished_at: null,
  };
}

async function renderTask(task: MemoryTaskView, models = MODELS): Promise<string> {
  const restore = installDom();
  // next/link's prefetch observer reaches for `self`, which jsdom globals don't install.
  Object.defineProperty(globalThis, "self", { configurable: true, writable: true, value: window });
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async () => new Response(JSON.stringify(DETAIL))) as typeof fetch;
  try {
    const view = await renderReact(
      <NextIntlClientProvider locale="en" messages={messages} timeZone="UTC">
        <MemoryTaskDetail server={SERVER} task={task} models={models} />
      </NextIntlClientProvider>,
    );
    await runInAct(() => new Promise((resolve) => setTimeout(resolve, 0)));
    const text = view.container.textContent ?? "";
    await view.unmount();
    return text;
  } finally {
    globalThis.fetch = originalFetch;
    delete (globalThis as { self?: unknown }).self;
    restore();
  }
}

test("a done digest task shows the digest it produced, not the current one", async () => {
  const text = await renderTask(weekDigestTask(1));
  assert.match(text, /Homelab work\./);
  assert.doesNotMatch(text, /Mostly infra work/);
  assert.match(text, /Superseded by a newer result\./);
  assert.match(text, /Talos upgrade dry run/);
});

test("the current result needs no superseded hint", async () => {
  const text = await renderTask(weekDigestTask(2));
  assert.match(text, /Mostly infra work on the homelab cluster\./);
  assert.doesNotMatch(text, /Superseded/);
});

test("an open task names the model it would run with now, not the stale estimate's", async () => {
  const task: MemoryTaskView = {
    ...weekDigestTask(2),
    status: "pending",
    model: "sonnet",
    provenance: null,
    result_id: null,
    estimate: { model: "sonnet", input_tokens: 900, output_tokens_cap: 6000, cost_usd: null },
  };
  const text = await renderTask(task);
  assert.match(text, /opus · Estimate 900 in · ≤6K out/);
  assert.doesNotMatch(text, /sonnet/);
});
