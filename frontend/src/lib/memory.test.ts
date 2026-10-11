import assert from "node:assert/strict";
import test from "node:test";

import {
  budgetGauge,
  exceedsBudget,
  factMatchesText,
  groupFacts,
  isExpiredFact,
  formatUsd,
  groupMonthsByYear,
  isoWeek,
  monthLabel,
  roleDefaultModels,
  hasActiveTasks,
  missingSourceCount,
  periodBadge,
  periodLevel,
  remainingBudget,
  summarizeSkips,
  taskActivityAt,
  taskRunModel,
  runnableTaskIds,
  sourceTasksForm,
  toSessionFilter,
  toSpawnRequest,
  toTaskFilter,
  toTaskSelection,
  weekLabel,
} from "./memory";
import type { MemoryBudgetWindowStatus, MemoryFactView, MemoryMonthNode, MemoryPeriodNode, MemorySessionRow, MemoryStatus, MemoryTask } from "./types";

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

test("formatUsd keeps sub-cent costs visible and budgets at two decimals", () => {
  assert.equal(formatUsd("0.00213", "en"), "$0.0021");
  assert.equal(formatUsd("0.0004", "en"), "$0.0004");
  assert.equal(formatUsd("0.004", "en"), "$0.004");
  assert.equal(formatUsd("0.123", "en"), "$0.123");
  assert.equal(formatUsd("1", "en"), "$1.00");
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

function memoryTask(overrides: Partial<MemoryTask> = {}): MemoryTask {
  return {
    id: 1,
    user: "ada",
    kind: "session_extract",
    target: "s1",
    status: "pending",
    week_key: "2026-W36",
    month_key: "2026-09",
    model: "stale",
    blocked_reason: null,
    spawned_by: "auto",
    model_override: null,
    attempts: 0,
    estimate: { model: "stale", input_tokens: 1, output_tokens_cap: 1, cost_usd: "0.01" },
    provenance: null,
    result_id: null,
    error: null,
    created_at: "2026-09-04T10:00:00Z",
    queued_at: null,
    started_at: null,
    finished_at: null,
    ...overrides,
  };
}

test("taskRunModel ignores the spawn-time estimate model", () => {
  const models = { memory_low: "low", memory_high: "high" };
  assert.equal(taskRunModel(memoryTask(), models), "low");
  assert.equal(taskRunModel(memoryTask({ kind: "week_digest" }), models), "high");
  assert.equal(taskRunModel(memoryTask({ model_override: "picked" }), models), "picked");
  const provenance = {
    carapace_version: "0", model: "ran", prompt_version: "p", input_format_version: 1, input_hash: "h",
    input_tokens: 1, output_tokens: 1, cost_usd: null, duration_ms: 1, task_id: 1, created_at: "2026-09-04T10:00:00Z",
  };
  assert.equal(taskRunModel(memoryTask({ model_override: "picked", provenance }), models), "ran");
  assert.equal(taskRunModel(memoryTask({ kind: "mirror", estimate: null }), models), null);
  assert.equal(taskRunModel(memoryTask(), null), null);
});

test("taskActivityAt takes the latest lifecycle timestamp", () => {
  assert.equal(taskActivityAt(memoryTask()), "2026-09-04T10:00:00Z");
  assert.equal(taskActivityAt(memoryTask({ queued_at: "2026-09-05T08:00:00Z" })), "2026-09-05T08:00:00Z");
  assert.equal(
    taskActivityAt(memoryTask({ queued_at: "2026-09-05T08:00:00Z", started_at: "2026-09-05T08:01:00Z", finished_at: "2026-09-05T08:02:00Z" })),
    "2026-09-05T08:02:00Z",
  );
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

test("a week belongs to the month of its Thursday", () => {
  const day = (date: Date) => date.toISOString().slice(0, 10);
  const first = isoWeek("2026-W01");
  assert.deepEqual([day(first.start), day(first.end), first.monthKey], ["2025-12-29", "2026-01-04", "2026-01"]);
  const julyAugust = isoWeek("2026-W31");
  assert.deepEqual([day(julyAugust.start), day(julyAugust.end), julyAugust.monthKey], ["2026-07-27", "2026-08-02", "2026-07"]);
  const augustSeptember = isoWeek("2026-W36");
  assert.deepEqual([day(augustSeptember.start), augustSeptember.monthKey], ["2026-08-31", "2026-09"]);
  assert.match(weekLabel("2026-W31", "de", true), /^Juli 2026 · /);
});

test("monthLabel names the key's month, not the month of its first Monday", () => {
  assert.equal(monthLabel("2026-09", "en", true), "September 2026");
  assert.equal(monthLabel("2026-09", "en", false), "September");
});

function fact(overrides: Partial<MemoryFactView>): MemoryFactView {
  return {
    id: 1,
    extraction_id: 1,
    session_id: "s1",
    session_title: "Talos upgrade",
    category: "social",
    subject: "Anna",
    statement: "Anna is moving to Hamburg.",
    source_kind: "user_said",
    confidence: "high",
    durability: "dated",
    valid_until: "2026-10-31",
    source_seqs: [4],
    week_key: "2026-W36",
    created_at: "2026-09-08T07:12:00Z",
    ...overrides,
  };
}

test("groupFacts merges normalized statement + subject and tracks first and last seen", () => {
  const groups = groupFacts([
    fact({ id: 1, week_key: "2026-W36" }),
    fact({ id: 2, week_key: "2026-W09", statement: "anna is  moving to Hamburg", subject: "anna " }),
    fact({ id: 3, statement: "Anna has a cat." }),
  ]);
  assert.equal(groups.length, 2);
  const moving = groups.find((group) => group.occurrences.length === 2)!;
  assert.deepEqual(moving.occurrences.map((f) => f.id), [2, 1]);
  assert.equal(moving.firstSeen, "2026-W09");
  assert.equal(moving.lastSeen, "2026-W36");
  assert.equal(moving.latest.id, 1);
});

test("dated facts expire after valid_until; text filter covers statement, subject and session", () => {
  assert.equal(isExpiredFact(fact({}), "2026-11-01"), true);
  assert.equal(isExpiredFact(fact({}), "2026-10-31"), false);
  assert.equal(isExpiredFact(fact({ durability: "durable", valid_until: null }), "2030-01-01"), false);
  const [group] = groupFacts([fact({})]);
  assert.equal(factMatchesText(group, "hamburg"), true);
  assert.equal(factMatchesText(group, "talos"), true);
  assert.equal(factMatchesText(group, "berlin"), false);
});

test("summarizeSkips counts repeated reasons", () => {
  assert.equal(summarizeSkips([{ target: "2026-W37", reason: "no_handler" }]), "no_handler");
  assert.equal(
    summarizeSkips([
      { target: "a", reason: "private" },
      { target: "b", reason: "already_open" },
      { target: "c", reason: "private" },
    ]),
    "private ×2, already_open",
  );
});

test("roleDefaultModels names one model per role in the selection", () => {
  const models = { memory_low: "low-model", memory_high: "high-model" };
  assert.equal(roleDefaultModels(["session_extract"], models), "low-model");
  assert.equal(roleDefaultModels(["week_digest", "month_digest"], models), "high-model");
  assert.equal(roleDefaultModels(["session_extract", "week_digest", "mirror"], models), "low: low-model · high: high-model");
  assert.equal(roleDefaultModels(["session_extract", "week_digest"], { memory_low: "same", memory_high: "same" }), "same");
  assert.equal(roleDefaultModels(["mirror"], models), null);
});

test("a digest's source link filters to its period's sources", () => {
  assert.deepEqual(sourceTasksForm({ kind: "week_digest", target: "2026-W36" }), { status: "", kind: "session_extract", period: "2026-W36", model: "" });
  assert.deepEqual(sourceTasksForm({ kind: "month_digest", target: "2026-09" }), { status: "", kind: "", period: "2026-09", model: "" });
  assert.equal(missingSourceCount({ waiting: 4, pending_ids: [1, 2], failed: 1 }), 3);
});
