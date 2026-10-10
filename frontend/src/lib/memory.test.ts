import assert from "node:assert/strict";
import test from "node:test";

import { budgetGauge, formatUsd, remainingBudget, toTaskFilter, toTaskSelection } from "./memory";
import type { MemoryBudgetWindowStatus, MemoryStatus } from "./types";

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
