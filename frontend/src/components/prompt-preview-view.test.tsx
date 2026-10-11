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
        { key: "tools", title: "Tool definitions (1)", text: '[\n  {\n    "name": "read"\n  }\n]', tokens: 40 },
        { key: "shared", title: "Shared prefix", text: "# AGENTS.md\n\nYou are **carapace**.", tokens: 1200 },
        { key: "instructions", title: "Agent instructions", text: "Use tools.", tokens: 300 },
        { key: "memory", title: "Memory", text: "W41: Talos upgrade. ![x](https://tracker.example/p.png)", tokens: 900 },
        { key: "volatile", title: "Volatile tail", text: "Session s1", tokens: 20 },
      ],
      total_tokens: 2420,
      cacheable_until: 3,
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
  const nodeAtob = globalThis.atob;
  const restore = installDom();
  // Shiki decodes its WASM with atob, and jsdom's rejects that payload.
  globalThis.atob = nodeAtob;
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
    const openSection = async (title: string) => {
      const details = Array.from(view.container.querySelectorAll("details")).find((element) => element.querySelector("summary")?.textContent?.startsWith(title));
      assert.ok(details, `no section ${title}`);
      await runInAct(() => {
        details.open = true;
        details.dispatchEvent(new Event("toggle"));
      });
      await settle();
      return details;
    };
    assert.match(text(), /900 \/ 4,000/);
    const fill = view.container.querySelector<HTMLElement>('[role="meter"] > div');
    assert.equal(fill?.style.width, "22.5%");

    // One segment per section, sized by tokens; the cache tick sits after the memory section (2,440 of 2,460).
    const segments = Array.from(view.container.querySelectorAll<HTMLButtonElement>('button[aria-label*=" tokens · "]'));
    assert.deepEqual(segments.map((segment) => segment.style.flexGrow), ["40", "1200", "300", "900", "20"]);
    assert.equal(segments[1].getAttribute("aria-label"), "Shared prefix · 1,200 tokens · 49.6%");
    const tick = view.container.querySelector<HTMLElement>('[title="End of cacheable prefix"]');
    assert.equal(Number.parseFloat(tick?.style.left ?? ""), (2440 / 2460) * 100);
    const scrolled: Element[] = [];
    window.Element.prototype.scrollIntoView = function scrollIntoView(this: Element) {
      scrolled.push(this);
    };
    await click(segments[3]);
    await settle();
    const memory = view.container.querySelector<HTMLDetailsElement>("#prompt-section-memory");
    assert.equal(memory?.open, true);
    assert.deepEqual(scrolled, [memory]);
    const summaries = Array.from(view.container.querySelectorAll("summary"), (summary) => summary.textContent);
    assert.deepEqual(summaries, [
      "Tool definitions (1)40 tokens",
      "Shared prefix1,200 tokens",
      "Agent instructions300 tokens",
      "Memory900 tokens",
      "Volatile tail20 tokens",
    ]);
    // The marker sits right after the last cacheable section, before the volatile tail.
    const marker = view.container.querySelector('[role="separator"]');
    assert.equal(marker?.previousElementSibling?.querySelector("summary")?.textContent, "Memory900 tokens");

    // Rendered: Markdown becomes markup, the tool definitions a JSON code block.
    const shared = await openSection("Shared prefix");
    assert.equal(shared.querySelector("h1")?.textContent, "AGENTS.md");
    assert.equal(shared.querySelector("strong")?.textContent, "carapace");
    const memorySection = await openSection("Memory");
    assert.equal(memorySection.querySelector("img"), null);
    assert.equal(memorySection.querySelector("pre")?.textContent, "W41: Talos upgrade. ![x](https://tracker.example/p.png)");
    const tools = await openSection("Tool definitions");
    assert.match(tools.querySelector("pre")?.textContent ?? "", /"name": "read"/);

    // Raw: the exact text, Markdown untouched, tool definitions still a code block.
    const raw = Array.from(view.container.querySelectorAll('[role="radio"]')).find((radio) => radio.textContent === "Raw");
    assert.ok(raw);
    await click(raw);
    await settle();
    assert.equal(shared.querySelector("pre")?.textContent, "# AGENTS.md\n\nYou are **carapace**.");
    assert.equal(shared.querySelector("h1"), null);
    assert.match(tools.querySelector("pre")?.textContent ?? "", /"name": "read"/);

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
