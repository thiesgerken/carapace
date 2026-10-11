import assert from "node:assert/strict";
import test from "node:test";
import { NextIntlClientProvider } from "next-intl";

import messages from "../../messages/en.json";
import { installDom, renderReact } from "../../test/react-test-utils";
import type { MemoryExtractionRecord, MemorySessionDetail } from "@/lib/types";

import { MemoryExtractionDetail } from "./memory-extraction-detail";

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

  try {
    const view = await renderReact(
      <NextIntlClientProvider locale="en" messages={messages} timeZone="UTC">
        <MemoryExtractionDetail sessionId="s1" state={{ detail: DETAIL, error: null }} />
      </NextIntlClientProvider>,
    );

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
    delete (globalThis as { self?: unknown }).self;
    restore();
  }
});

test("a session without an extraction shows its task status as a badge", async () => {
  const restore = installDom();
  Object.defineProperty(globalThis, "self", { configurable: true, writable: true, value: window });
  const detail: MemorySessionDetail = {
    session: {
      ...DETAIL.session,
      task: { id: 7, status: "failed", blocked_reason: null },
    },
    current: null,
    history: [],
  };

  try {
    const view = await renderReact(
      <NextIntlClientProvider locale="en" messages={messages} timeZone="UTC">
        <MemoryExtractionDetail sessionId="s1" state={{ detail, error: null }} />
      </NextIntlClientProvider>,
    );

    assert.match(view.container.textContent ?? "", /Task is failed\./);
    assert.ok(view.container.querySelector("svg.lucide-circle-x, svg.lucide-x-circle"), "no failed badge icon");

    await view.unmount();
  } finally {
    delete (globalThis as { self?: unknown }).self;
    restore();
  }
});
