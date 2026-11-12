import assert from "node:assert/strict";
import test from "node:test";

import type { BudgetGauge, TurnUsage } from "@/lib/types";

import { visibleBudgetGauges } from "./chat-input";

function autonomy(streak: number, limit: number): BudgetGauge {
  return {
    key: "autonomy",
    label: "Autonomy",
    current_value: String(streak),
    current_amount: streak,
    limit_value: String(limit),
    fill_pct: (100 * streak) / limit,
    reached: streak >= limit,
  };
}

function usage(budgetGauges: BudgetGauge[]): TurnUsage {
  return { input_tokens: 0, output_tokens: 0, budget_gauges: budgetGauges };
}

test("the autonomy bar shows only above half of the limit", () => {
  assert.deepEqual(visibleBudgetGauges(usage([autonomy(1, 10)])), []);
  assert.deepEqual(visibleBudgetGauges(usage([autonomy(5, 10)])), []);
  assert.deepEqual(visibleBudgetGauges(usage([autonomy(6, 10)])).map((gauge) => gauge.key), ["autonomy"]);
});

test("other gauges still show as soon as they have spend", () => {
  const toolCalls: BudgetGauge = { ...autonomy(1, 10), key: "tool_calls", label: "Tool calls" };
  assert.deepEqual(visibleBudgetGauges(usage([toolCalls, autonomy(1, 10)])).map((gauge) => gauge.key), ["tool_calls"]);
});
