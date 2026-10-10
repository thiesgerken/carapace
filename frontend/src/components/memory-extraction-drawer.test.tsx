import assert from "node:assert/strict";
import test from "node:test";
import { NextIntlClientProvider } from "next-intl";

import messages from "../../messages/en.json";
import { installDom, renderReact, runInAct } from "../../test/react-test-utils";
import type { MemoryExtractionRecord, MemorySessionDetail } from "@/lib/types";

import { MemoryExtractionDrawer } from "./memory-extraction-drawer";

const SERVER = "https://carapace.example.test";

function record(id: number, is_current: boolean, statement: string): MemoryExtractionRecord {
  return {
    id,
    session_id: "s1",
    week_key: "2026-W36",
    month_key: "2026-09",
    is_current,
    input_hash: "abc",
    provenance: {
      carapace_version: "0.158.7",
      model: is_current ? "haiku" : "sonnet",
      prompt_version: "a1b2c3",
      input_format_version: 1,
      input_hash: "abc",
      input_tokens: 1200,
      output_tokens: 300,
      cost_usd: "0.004",
      duration_ms: 2100,
      task_id: id,
      created_at: "2026-09-08T07:12:00Z",
    },
    extraction: {
      abstract: "Planned the Talos upgrade.",
      outcomes: [],
      open_loops: [],
      on_my_mind: [],
      friction: [],
      tags: [],
      facts: [{
        category: "surroundings",
        statement,
        subject: "NAS",
        source_seqs: [4],
        source_kind: "observed",
        confidence: "high",
        durability: "durable",
        valid_until: null,
      }],
    },
    created_at: "2026-09-08T07:12:00Z",
  };
}

const DETAIL: MemorySessionDetail = {
  session: { session_id: "s1", title: "Talos upgrade", channel_type: "web", created_at: "2026-09-02T10:00:00Z", week_key: "2026-W36", extraction: null, task: null },
  current: record(2, true, "Runs a Synology NAS."),
  history: [record(1, false, "Has a NAS.")],
};

test("only the current extraction links fact sources to events", async () => {
  const restore = installDom();
  // next/link's prefetch observer reaches for `self`, which jsdom globals don't install.
  Object.defineProperty(globalThis, "self", { configurable: true, writable: true, value: window });
  const originalFetch = globalThis.fetch;
  window.HTMLDialogElement.prototype.showModal = function showModal(this: HTMLDialogElement) {
    this.open = true;
  };
  globalThis.fetch = (async () => new Response(JSON.stringify(DETAIL))) as typeof fetch;

  try {
    const view = await renderReact(
      <NextIntlClientProvider locale="en" messages={messages} timeZone="UTC">
        <MemoryExtractionDrawer server={SERVER} sessionId="s1" onClose={() => {}} />
      </NextIntlClientProvider>,
    );
    await runInAct(() => new Promise((resolve) => setTimeout(resolve, 0)));

    const factSources = (statement: string) => {
      const fact = Array.from(view.container.querySelectorAll("li")).find((item) => item.textContent?.includes(statement));
      assert.ok(fact, `no fact "${statement}"`);
      return fact;
    };
    assert.equal(factSources("Runs a Synology NAS.").querySelector("a")?.getAttribute("href"), "/?session=s1&event=4");
    const older = factSources("Has a NAS.");
    assert.equal(older.querySelector("a"), null);
    assert.match(older.textContent ?? "", /#4/);

    await view.unmount();
  } finally {
    globalThis.fetch = originalFetch;
    delete (globalThis as { self?: unknown }).self;
    restore();
  }
});
