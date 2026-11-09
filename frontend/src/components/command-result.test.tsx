import assert from "node:assert/strict";
import test from "node:test";
import { NextIntlClientProvider } from "next-intl";

import messages from "../../messages/en.json";
import { installDom, renderReact } from "../../test/react-test-utils";

import { CommandResultView } from "./command-result";

const bucket = { input_tokens: 10, output_tokens: 5, cache_read_tokens: 0, cache_write_tokens: 0, requests: 1 };

/** Agent on a ChatGPT subscription, sentinel on a pay-per-token API. */
function mixedUsage(budgetGauges: unknown[]) {
  return {
    models: { "openai-codex:gpt-5.4": bucket, "anthropic:claude-haiku-4-5": bucket },
    categories: { agent: bucket, sentinel: bucket },
    total_input: 20,
    total_output: 10,
    total_tool_calls: 0,
    model_costs: {
      "openai-codex:gpt-5.4": { cost: "0.42", subscription: true },
      "anthropic:claude-haiku-4-5": { cost: "0.01", subscription: false },
    },
    category_costs: {
      agent: { actual: "0", equivalent: "0.42" },
      sentinel: { actual: "0.01", equivalent: "0.01" },
    },
    total_cost: { actual: "0.01", equivalent: "0.43" },
    budget_gauges: budgetGauges,
  };
}

const equivalentGauge = {
  key: "equivalent_cost",
  label: "Equivalent cost",
  current_value: "$0.4300",
  current_amount: 0.43,
  limit_value: null,
  fill_pct: 0,
  reached: false,
};

async function renderUsage(data: unknown): Promise<{ summary: string; rows: string[] }> {
  const restore = installDom();
  try {
    const view = await renderReact(
      <NextIntlClientProvider locale="en" messages={messages} timeZone="UTC">
        <CommandResultView command="usage" data={data} defaultExpanded />
      </NextIntlClientProvider>,
    );
    const summary = view.container.querySelector("button")?.textContent ?? "";
    const rows = [...view.container.querySelectorAll("tbody tr")].map((row) =>
      [...row.querySelectorAll("td")].map((cell) => cell.textContent).join(" | "),
    );
    await view.unmount();
    return { summary, rows };
  } finally {
    restore();
  }
}

test("usage shows actual cost, marks subscription models and notes the equivalent where it differs", async () => {
  const { summary, rows } = await renderUsage(mixedUsage([equivalentGauge]));

  assert.match(summary, /\| \$0\.0100 \(≈ \$0\.4300 equivalent\)/);
  assert.deepEqual(rows, [
    "Equivalent cost | $0.4300 | — | — | 0.0%",
    "openai-codex:gpt-5.4 | 10 | 5 | 1 | $0.4200 · subscription",
    "anthropic:claude-haiku-4-5 | 10 | 5 | 1 | $0.0100",
    "agent | 10 | 5 | 1 | - (≈ $0.4200 equivalent)",
    "sentinel | 10 | 5 | 1 | $0.0100",
  ]);
});

test("the equivalent total follows its gauge", async () => {
  const { summary } = await renderUsage(mixedUsage([]));

  assert.doesNotMatch(summary, /equivalent/);
});
