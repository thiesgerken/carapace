import assert from "node:assert/strict";
import test, { type TestContext } from "node:test";
import { NextIntlClientProvider } from "next-intl";

import messages from "../../messages/en.json";
import { click, installDom, renderReact, runInAct } from "../../test/react-test-utils";
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
      id: "loop-1",
      text: "Upgrade the **third** node ![x](https://tracker.example/p.png)",
      session_id: "s1",
      session_title: "Talos upgrade",
      session_last_active: "2026-10-11T10:00:00Z",
      week_key: "2026-W41",
    },
    { id: "loop-2", text: "Book the train.", session_id: "s2", session_title: null, session_last_active: "2026-10-09T10:00:00Z", week_key: "2026-W41" },
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

/** `holdDismiss` keeps every POST open until it resolves. */
async function renderHome(data: HomeData, holdDismiss?: Promise<void>) {
  const restore = installDom();
  // next/link's prefetch observer reaches for `self`, which jsdom globals don't install.
  Object.defineProperty(globalThis, "self", { configurable: true, writable: true, value: window });
  // The composer asks for the pointer type; jsdom has no matchMedia.
  window.matchMedia = ((query: string) => ({ matches: false, media: query, addEventListener() {}, removeEventListener() {} })) as unknown as typeof window.matchMedia;
  const originalFetch = globalThis.fetch;
  const mutations: string[] = [];
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = new URL(String(input)).pathname;
    if (path === "/api/home") return Response.json(data);
    assert.match(path, /^\/api\/home\/open-loops\/[^/]+\/dismiss$/);
    mutations.push(`${init?.method} ${path}`);
    if (init?.method === "POST" && holdDismiss) await holdDismiss;
    return new Response(null, { status: 204 });
  }) as typeof fetch;
  const view = await renderReact(
    <NextIntlClientProvider locale="en" messages={messages} timeZone="UTC">
      <HomeView server={SERVER} agentName="carapace" onStart={async () => true} />
    </NextIntlClientProvider>,
  );
  await runInAct(() => new Promise((resolve) => setTimeout(resolve, 0)));
  return {
    view,
    mutations,
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

test("dismissing a loop hides it with an undo, and the last one leaves the empty state", async (t: TestContext) => {
  const home = await renderHome(FULL);
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const flush = () => runInAct(async () => {});
  const button = (label: string) => {
    const found = Array.from(home.view.container.querySelectorAll("button")).find((element) => element.getAttribute("aria-label") === label || element.textContent === label);
    assert.ok(found, `no button ${label}`);
    return found;
  };
  const loops = () => Array.from(home.view.container.querySelectorAll("li.group\\/loop"), (item) => item.textContent ?? "");
  try {
    await click(button("Done"));
    await flush();
    assert.deepEqual(home.mutations, ["POST /api/home/open-loops/loop-1/dismiss"]);
    assert.match(loops()[0], /^Done: Upgrade the/);
    assert.equal(home.view.container.ownerDocument.activeElement?.textContent, "Undo");

    await click(button("Undo"));
    await flush();
    assert.deepEqual(home.mutations.at(-1), "DELETE /api/home/open-loops/loop-1/dismiss");
    assert.match(loops()[0], /^Upgrade the/);

    await click(button("Done"));
    await click(button("Done"));
    await runInAct(async () => t.mock.timers.tick(6000));
    assert.deepEqual(loops(), []);
    assert.match(home.view.container.textContent ?? "", /Nothing left open\./);
  } finally {
    t.mock.timers.reset();
    await home.cleanup();
  }
});

test("a quick undo waits for its dismissal to reach the server", async () => {
  let release = () => {};
  const home = await renderHome(FULL, new Promise((resolve) => {
    release = resolve;
  }));
  const flush = () => runInAct(async () => {});
  const button = (label: string) => {
    const found = Array.from(home.view.container.querySelectorAll("button")).find((element) => element.getAttribute("aria-label") === label || element.textContent === label);
    assert.ok(found, `no button ${label}`);
    return found;
  };
  try {
    await click(button("Done"));
    await click(button("Undo"));
    await flush();
    assert.deepEqual(home.mutations, ["POST /api/home/open-loops/loop-1/dismiss"]);

    release();
    await flush();
    assert.deepEqual(home.mutations, ["POST /api/home/open-loops/loop-1/dismiss", "DELETE /api/home/open-loops/loop-1/dismiss"]);
  } finally {
    await home.cleanup();
  }
});
