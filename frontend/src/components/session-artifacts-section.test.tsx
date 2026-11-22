import assert from "node:assert/strict";
import test from "node:test";
import { setTimeout } from "node:timers/promises";
import { NextIntlClientProvider } from "next-intl";

import english from "../../messages/en.json";
import { installDom, renderReact, runInAct } from "../../test/react-test-utils";
import type { SessionArtifact } from "@/lib/api";
import { SessionArtifactsSection } from "./session-artifacts-section";

const SERVER = "https://carapace.example.test";

async function render(artifacts: SessionArtifact[]) {
  const requests: string[] = [];
  globalThis.fetch = (async (input) => {
    requests.push(String(input));
    return Response.json(artifacts);
  }) as typeof fetch;
  const view = await renderReact(
    <NextIntlClientProvider locale="en" messages={english} timeZone="UTC">
      <SessionArtifactsSection server={SERVER} sessionId="s1" refreshKey={3} />
    </NextIntlClientProvider>,
  );
  await runInAct(() => setTimeout(0));
  return { view, requests };
}

test("session artifacts link live ones and strike through deleted ones", async () => {
  const restore = installDom();
  const originalFetch = globalThis.fetch;
  const changed = new Date(Date.now() - 5 * 60_000).toISOString();
  try {
    const { view, requests } = await render([
      { slug: "q3-sales", title: "Q3 sales", change: "created", last_changed: changed, exists: true },
      { slug: "sales-draft", title: "sales-draft", change: "updated", last_changed: changed, exists: false },
    ]);
    assert.deepEqual(requests, [`${SERVER}/api/sessions/s1/artifacts`]);
    assert.equal(view.container.textContent?.startsWith(english.chatView.artifacts.title), true);
    const items = [...view.container.querySelectorAll("li")];
    assert.equal(items.length, 2);
    assert.equal(items[0].querySelector("a")?.getAttribute("href"), "/artifacts?slug=q3-sales");
    assert.ok(items[0].textContent?.includes("new · 5 minutes ago"));
    assert.equal(items[1].querySelector("a"), null);
    assert.ok(items[1].querySelector(".line-through")?.textContent === "sales-draft");
    assert.ok(items[1].textContent?.includes("updated · 5 minutes ago"));
    await view.unmount();
  } finally {
    globalThis.fetch = originalFetch;
    restore();
  }
});

test("a session without artifact commits shows no section", async () => {
  const restore = installDom();
  const originalFetch = globalThis.fetch;
  try {
    const { view } = await render([]);
    assert.equal(view.container.innerHTML, "");
    await view.unmount();
  } finally {
    globalThis.fetch = originalFetch;
    restore();
  }
});
