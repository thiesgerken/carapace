import assert from "node:assert/strict";
import test from "node:test";
import { act } from "react";
import { NextIntlClientProvider } from "next-intl";

import messages from "../../messages/en.json";
import { click, installDom, renderReact, setInputValue } from "../../test/react-test-utils";
import type { SessionBudgetSettings } from "@/lib/types";

import { SessionBudgetSection, type SessionBudgetField } from "./session-budget-section";

type SaveCall = [SessionBudgetField, string | null];

async function renderSection(
  budget: SessionBudgetSettings,
  onSave: (field: SessionBudgetField, value: string | null) => Promise<void>,
) {
  return renderReact(
    <NextIntlClientProvider locale="en" messages={messages} timeZone="UTC">
      <SessionBudgetSection budget={budget} disabled={false} onSave={onSave} />
    </NextIntlClientProvider>,
  );
}

function limitButton(container: HTMLElement, label: string): HTMLButtonElement {
  const button = container.querySelector<HTMLButtonElement>(`button[aria-label="Edit ${label} limit"]`);
  assert.ok(button, `missing button for ${label}`);
  return button;
}

function limitInput(container: HTMLElement): HTMLInputElement {
  const input = container.querySelector<HTMLInputElement>("input");
  assert.ok(input, "missing limit input");
  return input;
}

async function pressKey(element: HTMLElement, key: string): Promise<void> {
  await act(async () => {
    element.dispatchEvent(new window.KeyboardEvent("keydown", { key, bubbles: true }));
  });
}

test("shows every limit, unset ones as no limit, before any usage exists", async () => {
  const restore = installDom();
  try {
    const view = await renderSection({ input_tokens: 100_000, cost_usd: "2.50" }, async () => {});
    const rows = [...view.container.querySelectorAll("dt")].map(
      (dt) => `${dt.textContent}: ${dt.nextElementSibling?.textContent}`,
    );
    assert.deepEqual(rows, [
      "Input tokens: 100,000",
      "Output tokens: No limit",
      "Cost (USD): $2.50",
      "Tool calls: No limit",
    ]);
    await view.unmount();
  } finally {
    restore();
  }
});

test("Enter saves the typed value as is", async () => {
  const restore = installDom();
  try {
    const calls: SaveCall[] = [];
    const view = await renderSection({}, async (field, value) => {
      calls.push([field, value]);
    });

    await click(limitButton(view.container, "Tool calls"));
    const input = limitInput(view.container);
    await setInputValue(input, " 1k ");
    await pressKey(input, "Enter");

    assert.deepEqual(calls, [["tool_calls", "1k"]]);
    assert.equal(view.container.querySelector("input"), null);
    await view.unmount();
  } finally {
    restore();
  }
});

test("an emptied limit is saved as no limit", async () => {
  const restore = installDom();
  try {
    const calls: SaveCall[] = [];
    const view = await renderSection({ output_tokens: 5_000 }, async (field, value) => {
      calls.push([field, value]);
    });

    await click(limitButton(view.container, "Output tokens"));
    const input = limitInput(view.container);
    assert.equal(input.value, "5000");
    await setInputValue(input, "");
    await pressKey(input, "Enter");

    assert.deepEqual(calls, [["output_tokens", null]]);
    await view.unmount();
  } finally {
    restore();
  }
});

test("Escape and unchanged values do not save", async () => {
  const restore = installDom();
  try {
    const calls: SaveCall[] = [];
    const view = await renderSection({ input_tokens: 10 }, async (field, value) => {
      calls.push([field, value]);
    });

    await click(limitButton(view.container, "Input tokens"));
    await setInputValue(limitInput(view.container), "99");
    await pressKey(limitInput(view.container), "Escape");
    assert.equal(view.container.querySelector("input"), null);

    await click(limitButton(view.container, "Input tokens"));
    await pressKey(limitInput(view.container), "Enter");

    assert.deepEqual(calls, []);
    await view.unmount();
  } finally {
    restore();
  }
});

test("a rejected value keeps the editor open and shows the server error", async () => {
  const restore = installDom();
  try {
    const view = await renderSection({}, async () => {
      throw new Error("Invalid tool call budget: 1.5");
    });

    await click(limitButton(view.container, "Tool calls"));
    await setInputValue(limitInput(view.container), "1.5");
    await pressKey(limitInput(view.container), "Enter");

    assert.equal(limitInput(view.container).value, "1.5");
    assert.match(view.container.textContent ?? "", /Invalid tool call budget: 1\.5/);
    await view.unmount();
  } finally {
    restore();
  }
});
