import assert from "node:assert/strict";
import test from "node:test";

import {
  budgetGauge,
  exceedsBudget,
  formatUsd,
  groupMonthsByYear,
  monthLabel,
  hasActiveTasks,
  periodBadge,
  periodLevel,
  remainingBudget,
  runnableTaskIds,
  toSessionFilter,
  toSpawnRequest,
  toTaskFilter,
  toTaskSelection,
} from "./memory";
import type { MemoryBudgetWindowStatus, MemoryMonthNode, MemoryPeriodNode, MemorySessionRow, MemoryStatus } from "./types";

function window(overrides: Partial<MemoryBudgetWindowStatus> = {}): MemoryBudgetWindowStatus {
  return {
    window_start: "2026-09-01T00:00:00Z",
    spent_cost_usd: "0.42",
    spent_input_tokens: 1000,
    limit_cost_usd: null,
    limit_input_tokens: null,
    ...overrides,
  };
}

function status(day: MemoryBudgetWindowStatus, month: MemoryBudgetWindowStatus): MemoryStatus {
  return {
    auto_mode: false,
    timezone: "Europe/Berlin",
    day,
    month,
    queue: { pending: 0, queued: 0, running: 0, done: 0, failed: 0, cancelled: 0 },
    blocked: 0,
    models: { memory_low: "low", memory_high: "high" },
    sessions_without_transcript: 0,
  };
}

test("formatUsd keeps a third digit for sub-dollar amounts", () => {
  assert.equal(formatUsd("0.004", "en"), "$0.004");
  assert.equal(formatUsd("3.1", "en"), "$3.10");
  assert.equal(formatUsd("0", "en"), "$0.00");
});

test("budgetGauge prefers the cost limit and falls back to tokens", () => {
  assert.deepEqual(budgetGauge(window({ limit_cost_usd: "1.00", limit_input_tokens: 5000 })), { unit: "usd", spent: 0.42, limit: 1 });
  assert.deepEqual(budgetGauge(window({ limit_input_tokens: 5000 })), { unit: "tokens", spent: 1000, limit: 5000 });
  assert.deepEqual(budgetGauge(window()), { unit: "usd", spent: 0.42, limit: null });
});

test("remainingBudget takes the tightest window and clamps overspend to zero", () => {
  const day = window({ spent_cost_usd: "0.25", limit_cost_usd: "1.00" });
  const month = window({ spent_cost_usd: "3.10", limit_cost_usd: "10.00", limit_input_tokens: 500 });
  assert.deepEqual(remainingBudget(status(day, month)), { usd: 0.75, tokens: 0 });
  assert.deepEqual(remainingBudget(status(window(), window())), { usd: null, tokens: null });
});

test("selections send ids or the filter, never both", () => {
  const filter = toTaskFilter({ status: "pending", kind: "", period: "2026-09", model: "" });
  assert.deepEqual(filter, { status: ["pending"], kind: null, period: "2026-09", model: null });
  assert.deepEqual(toTaskSelection({ kind: "ids", ids: [1, 2] }, filter), { ids: [1, 2] });
  assert.deepEqual(toTaskSelection({ kind: "matching" }, filter), { filter });
});

test("budget-blocked queued tasks don't keep the poll alive", () => {
  const blocked = { ...status(window(), window()), blocked: 3 };
  blocked.queue = { ...blocked.queue, queued: 3 };
  assert.equal(hasActiveTasks(blocked), false);
  assert.equal(hasActiveTasks({ ...blocked, queue: { ...blocked.queue, running: 1 } }), true);
});

test("exceedsBudget checks token-only budgets too", () => {
  const tokenOnly = status(window({ limit_input_tokens: 5000 }), window());
  const estimate = { task_count: 1, input_tokens: 4500, output_tokens_cap: 0, cost_usd: "0", unpriced_count: 1 };
  assert.equal(exceedsBudget(estimate, tokenOnly), true);
  assert.equal(exceedsBudget({ ...estimate, input_tokens: 4000 }, tokenOnly), false);
});

test("outdated reasons only narrow the outdated state", () => {
  const form = { week: "2026-W36", state: "outdated", outdatedReason: "prompt_version", taskStatus: "", model: "", channel: "" } as const;
  assert.deepEqual(toSessionFilter(form), {
    week: "2026-W36",
    state: ["outdated"],
    outdated_reason: "prompt_version",
    task_status: null,
    model: null,
    channel: null,
  });
  assert.equal(toSessionFilter({ ...form, state: "current" }).outdated_reason, null);
});

test("session picks spawn by targets or by filter", () => {
  const filter = toSessionFilter({ week: "", state: "outdated", outdatedReason: "", taskStatus: "", model: "", channel: "" });
  assert.deepEqual(toSpawnRequest({ kind: "ids", ids: ["s1"] }, filter), { kind: "session_extract", targets: ["s1"] });
  assert.deepEqual(toSpawnRequest({ kind: "matching" }, filter), { kind: "session_extract", filter });
});

test("runnableTaskIds skips picked sessions without a task", () => {
  const row = (session_id: string, taskId: number | null): MemorySessionRow => ({
    session_id,
    title: null,
    channel_type: "web",
    created_at: "2026-09-01T00:00:00Z",
    week_key: null,
    extraction: null,
    task: taskId === null ? null : { id: taskId, status: "pending", blocked_reason: null },
  });
  assert.deepEqual(runnableTaskIds([row("a", 1), row("b", null), row("c", 3)], ["a", "b"]), [1]);
});

function periodNode(overrides: Partial<MemoryPeriodNode> = {}): MemoryPeriodNode {
  return {
    level: "week",
    key: "2026-W36",
    start: "2026-08-31",
    end: "2026-09-06",
    covered: 12,
    total: 14,
    digest: null,
    stale: false,
    task: null,
    ...overrides,
  };
}

test("periodBadge distinguishes not run, current and stale with reasons", () => {
  const digest = { id: 1, model: "opus", prompt_version: "a1", carapace_version: "0.158.7", cost_usd: "0.08", created_at: "2026-09-08T07:12:00Z", outdated: [] };
  assert.deepEqual(periodBadge(periodNode()), { kind: "notRun" });
  assert.deepEqual(periodBadge(periodNode({ digest })), { kind: "current" });
  assert.deepEqual(
    periodBadge(periodNode({ digest: { ...digest, outdated: ["prompt_version"] }, stale: true })),
    { kind: "stale", reasons: ["sources", "prompt_version"] },
  );
});

test("periodLevel and year grouping follow the period keys", () => {
  assert.equal(periodLevel("2026-W36"), "week");
  assert.equal(periodLevel("2026-09"), "month");
  const month = (key: string): MemoryMonthNode => ({ ...periodNode({ level: "month", key }), weeks: [] });
  assert.deepEqual(
    groupMonthsByYear([month("2027-01"), month("2026-12"), month("2026-11")]).map(([year, months]) => [year, months.map((m) => m.key)]),
    [["2027", ["2027-01"]], ["2026", ["2026-12", "2026-11"]]],
  );
});

test("monthLabel names the key's month, not the month of its first Monday", () => {
  assert.equal(monthLabel("2026-09", "en", true), "September 2026");
  assert.equal(monthLabel("2026-09", "en", false), "September");
});
