import assert from "node:assert/strict";
import test from "node:test";
import { NextIntlClientProvider } from "next-intl";

import messages from "../../messages/en.json";
import { click, installDom, renderReact, runInAct } from "../../test/react-test-utils";
import type { PromptPreview } from "@/lib/types";

import { PromptPreviewView } from "./prompt-preview-view";

const SERVER = "https://carapace.example.test";

function preview(role: PromptPreview["role"]): PromptPreview {
  return role === "agent"
    ? {
      role,
      model: "anthropic:sonnet",
      sections: [
        { key: "shared", title: "Shared prefix", text: "You are carapace.", tokens: 1200 },
        { key: "instructions", title: "Agent instructions", text: "Use tools.", tokens: 300 },
        { key: "memory", title: "Memory (what a new session would get now)", text: "W41: Talos upgrade.", tokens: 900 },
        { key: "volatile", title: "Volatile tail", text: "Session s1", tokens: 20 },
      ],
      total_tokens: 2420,
      cacheable_until: 2,
      memory_budget_tokens: 4000,
      memory_used_tokens: 900,
    }
    : {
      role,
      model: "anthropic:haiku",
      sections: [{ key: "instructions", title: "Sentinel instructions", text: "Judge actions.", tokens: 500 }],
      total_tokens: 500,
      cacheable_until: null,
      memory_budget_tokens: null,
      memory_used_tokens: null,
    };
}

test("the preview shows sections, the cache boundary and the memory budget, and switches roles", async () => {
  const restore = installDom();
  const originalFetch = globalThis.fetch;
  const roles: string[] = [];
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    const url = new URL(String(input));
    assert.equal(url.pathname, "/api/prompts/preview");
    const role = url.searchParams.get("role") as PromptPreview["role"];
    roles.push(role);
    return Response.json(preview(role));
  }) as typeof fetch;

  try {
    const view = await renderReact(
      <NextIntlClientProvider locale="en" messages={messages} timeZone="UTC">
        <PromptPreviewView server={SERVER} />
      </NextIntlClientProvider>,
    );
    const settle = () => runInAct(() => new Promise((resolve) => setTimeout(resolve, 0)));
    await settle();

    const text = () => view.container.textContent ?? "";
    assert.match(text(), /anthropic:sonnet/);
    assert.match(text(), /2,420/);
    assert.match(text(), /900 \/ 4,000/);
    const summaries = Array.from(view.container.querySelectorAll("summary"), (summary) => summary.textContent);
    assert.deepEqual(summaries, [
      "Shared prefix1,200 tokens",
      "Agent instructions300 tokens",
      "Memory (what a new session would get now)900 tokens",
      "Volatile tail20 tokens",
    ]);
    // The marker sits right after the last cacheable section, before the volatile tail.
    const marker = view.container.querySelector('[role="separator"]');
    assert.equal(marker?.previousElementSibling?.querySelector("summary")?.textContent, "Memory (what a new session would get now)900 tokens");

    const sentinel = Array.from(view.container.querySelectorAll('[role="radio"]')).find((radio) => radio.textContent === "Sentinel");
    assert.ok(sentinel);
    await click(sentinel);
    await settle();
    assert.deepEqual(roles, ["agent", "sentinel"]);
    assert.match(text(), /anthropic:haiku/);
    assert.equal(view.container.querySelector('[role="separator"]'), null);
    assert.equal(view.container.querySelector('[role="meter"]'), null);
    await view.unmount();
  } finally {
    globalThis.fetch = originalFetch;
    restore();
  }
});
