import assert from "node:assert/strict";
import test from "node:test";
import { NextIntlClientProvider } from "next-intl";

import messages from "../../messages/en.json";
import { installDom, renderReact, runInAct } from "../../test/react-test-utils";
import type { HomeData } from "@/lib/types";

import { HomeView } from "./home-view";

const SERVER = "https://carapace.example.test";

const EMPTY: HomeData = {
  open_loops: [],
  this_week: null,
  notices: { pending_approvals: [], failed_memory_tasks: 0, outdated_memory_records: 0, memory_budget: null },
};

const FULL: HomeData = {
  open_loops: [
    {
      text: "Upgrade the **third** node ![x](https://tracker.example/p.png)",
      session_id: "s1",
      session_title: "Talos upgrade",
      session_last_active: "2026-10-11T10:00:00Z",
      week_key: "2026-W41",
    },
    { text: "Book the train.", session_id: "s2", session_title: null, session_last_active: "2026-10-09T10:00:00Z", week_key: "2026-W41" },
  ],
  this_week: {
    source: "week_digest",
    period_key: "2026-W41",
    themes: [{ theme: "Homelab", refs: ["s1"] }],
    highlights: ["Two nodes upgraded"],
    sessions: [],
  },
  notices: {
    pending_approvals: [{ session_id: "s3", session_title: "Deploy" }, { session_id: "s4", session_title: null }],
    failed_memory_tasks: 2,
    outdated_memory_records: 0,
    memory_budget: { used_usd: "0.92", limit_usd: "1.00", window: "day" },
  },
};

async function renderHome(data: HomeData) {
  const restore = installDom();
  // next/link's prefetch observer reaches for `self`, which jsdom globals don't install.
  Object.defineProperty(globalThis, "self", { configurable: true, writable: true, value: window });
  // The composer asks for the pointer type; jsdom has no matchMedia.
  window.matchMedia = ((query: string) => ({ matches: false, media: query, addEventListener() {}, removeEventListener() {} })) as unknown as typeof window.matchMedia;
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    assert.equal(new URL(String(input)).pathname, "/api/home");
    return Response.json(data);
  }) as typeof fetch;
  const view = await renderReact(
    <NextIntlClientProvider locale="en" messages={messages} timeZone="UTC">
      <HomeView server={SERVER} agentName="carapace" onStart={async () => true} />
    </NextIntlClientProvider>,
  );
  await runInAct(() => new Promise((resolve) => setTimeout(resolve, 0)));
  return {
    view,
    links: () => Array.from(view.container.querySelectorAll("a"), (link) => [link.textContent, link.getAttribute("href")]),
    async cleanup() {
      await view.unmount();
      globalThis.fetch = originalFetch;
      delete (globalThis as { self?: unknown }).self;
      restore();
    },
  };
}

test("home shows open loops as plain text, the week and only the non-zero notices, linking by id", async () => {
  const home = await renderHome(FULL);
  try {
    const text = home.view.container.textContent ?? "";
    // Model text stays literal: no Markdown, so no image fetch either.
    assert.match(text, /Upgrade the \*\*third\*\* node !\[x\]\(https:\/\/tracker\.example\/p\.png\)/);
    assert.equal(home.view.container.querySelector("img"), null);
    assert.match(text, /Untitled session/);
    assert.match(text, /Homelab/);
    assert.match(text, /Two nodes upgraded/);
    assert.doesNotMatch(text, /outdated/);

    const links = home.links();
    assert.deepEqual(links.filter(([label]) => label === "Continue").map(([, href]) => href), ["/?session=s1", "/?session=s2"]);
    assert.ok(links.some(([label, href]) => label === "2 sessions waiting for approval" && href === "/?session=s3"));
    assert.ok(links.some(([label, href]) => label === "2 failed memory tasks" && href === "/memory/tasks?status=failed"));
    assert.ok(links.some(([label, href]) => label === "Memory budget today: $0.92 of $1.00" && href === "/settings/account#memory"));
    assert.ok(links.some(([, href]) => href === "/memory/timeline?period=2026-W41"));
  } finally {
    await home.cleanup();
  }
});

test("without memory, home is the composer and one line pointing to the Memory area", async () => {
  const home = await renderHome(EMPTY);
  try {
    assert.ok(home.view.container.querySelector("textarea"));
    assert.equal(home.view.container.querySelectorAll("section").length, 0);
    assert.deepEqual(home.links(), [["memory", "/memory"]]);
  } finally {
    await home.cleanup();
  }
});
