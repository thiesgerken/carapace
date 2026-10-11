import assert from "node:assert/strict";
import test from "node:test";
import { NextIntlClientProvider } from "next-intl";

import messages from "../../messages/en.json";
import { installDom, renderReact } from "../../test/react-test-utils";
import type { MemoryExtractionRecord, MemorySessionDetail } from "@/lib/types";

import { ChatMemorySection } from "./chat-memory-section";
import type { MemorySessionDetailState } from "./memory-extraction-detail";

const CURRENT: MemoryExtractionRecord = {
  id: 2,
  session_id: "s1",
  week_key: "2026-W36",
  month_key: "2026-09",
  is_current: true,
  input_hash: "abc",
  provenance: {
    carapace_version: "0.158.7",
    model: "haiku",
    prompt_version: "a1b2c3",
    input_format_version: 1,
    input_hash: "abc",
    input_tokens: 1200,
    output_tokens: 300,
    cost_usd: "0.004",
    duration_ms: 2100,
    task_id: 2,
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
      statement: "Runs a Synology NAS.",
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

const DETAIL: MemorySessionDetail = {
  session: {
    session_id: "s1",
    title: "Talos upgrade",
    channel_type: "web",
    created_at: "2026-09-02T10:00:00Z",
    week_key: "2026-W36",
    extraction: {
      id: 2,
      abstract: "Planned the Talos upgrade.",
      fact_counts: { user: 0, social: 0, surroundings: 1 },
      model: "haiku",
      prompt_version: "a1b2c3",
      cost_usd: "0.004",
      created_at: "2026-09-08T07:12:00Z",
      outdated: ["prompt_version"],
    },
    task: { id: 9, status: "queued", blocked_reason: null },
  },
  current: CURRENT,
  history: [],
};

async function render(state: MemorySessionDetailState, open: boolean) {
  return renderReact(
    <NextIntlClientProvider locale="en" messages={messages} timeZone="UTC">
      <ChatMemorySection sessionId="s1" state={state} open={open} onOpenChange={() => {}} />
    </NextIntlClientProvider>,
  );
}

test("the collapsed section shows the status, outdated reason and task badge", async () => {
  const restore = installDom();
  // next/link's prefetch observer reaches for `self`, which jsdom globals don't install.
  Object.defineProperty(globalThis, "self", { configurable: true, writable: true, value: window });
  try {
    const view = await render({ detail: DETAIL, error: null }, false);
    const section = view.container.querySelector("details[data-memory-section]");
    assert.ok(section);
    assert.equal((section as HTMLDetailsElement).open, false);
    assert.match(section.querySelector("summary")?.textContent ?? "", /outdated · prompt changed.*queued/);

    const fact = Array.from(section.querySelectorAll("li")).find((item) => item.textContent?.includes("Runs a Synology NAS."));
    assert.equal(fact?.querySelector("a")?.getAttribute("href"), "/?session=s1&event=4");
    const openInMemory = Array.from(section.querySelectorAll("a")).find((link) => link.textContent === "Open in Memory");
    assert.equal(openInMemory?.getAttribute("href"), "/memory/sessions?session=s1");
    await view.unmount();
  } finally {
    delete (globalThis as { self?: unknown }).self;
    restore();
  }
});

test("sessions memory does not cover render nothing", async () => {
  const restore = installDom();
  try {
    const view = await render({ detail: null, error: null }, true);
    assert.equal(view.container.innerHTML, "");
    await view.unmount();
  } finally {
    restore();
  }
});
