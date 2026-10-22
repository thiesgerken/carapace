import assert from "node:assert/strict";
import test from "node:test";
import { setTimeout } from "node:timers/promises";
import { NextIntlClientProvider } from "next-intl";

import messages from "../../messages/en.json";
import { click, installDom, renderReact, runInAct } from "../../test/react-test-utils";
import { ArtifactShareControls } from "./artifact-share-controls";

const SERVER = "https://carapace.example.test";
const settle = () => runInAct(() => setTimeout(0));

test("sharing asks for confirmation, copies an absolute public link, and hides it after revocation", async () => {
  const restore = installDom();
  const originalFetch = globalThis.fetch;
  const methods: string[] = [];
  let copied: string | null = null;
  globalThis.fetch = (async (_input: RequestInfo | URL, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    methods.push(method);
    return Response.json(method === "PUT"
      ? { url: "/api/public/a/random-token", shared_at: "2026-10-22T18:00:00Z" }
      : { url: null, shared_at: null });
  }) as typeof fetch;
  Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText: async (value: string) => { copied = value; } } });
  try {
    window.confirm = () => false;
    const view = await renderReact(
      <NextIntlClientProvider locale="en" messages={messages} timeZone="UTC">
        <ArtifactShareControls server={SERVER} slug="report" />
      </NextIntlClientProvider>,
    );
    await settle();
    const toggle = view.container.querySelector('[role="switch"]');
    assert.ok(toggle);
    assert.equal(toggle.getAttribute("aria-checked"), "false");
    await click(toggle);
    assert.deepEqual(methods, ["GET"]);
    assert.equal(view.container.querySelector("a"), null);

    window.confirm = () => true;
    await click(toggle);
    await settle();
    assert.equal(toggle.getAttribute("aria-checked"), "true");
    assert.equal(view.container.querySelector("a")?.href, `${SERVER}/api/public/a/random-token`);
    const copy = view.container.querySelector(`button[aria-label="${messages.artifacts.sharing.copy}"]`);
    assert.ok(copy);
    await click(copy);
    assert.equal(copied, `${SERVER}/api/public/a/random-token`);

    await click(toggle);
    await settle();
    assert.equal(toggle.getAttribute("aria-checked"), "false");
    assert.equal(view.container.querySelector("a"), null);
    assert.deepEqual(methods, ["GET", "PUT", "DELETE"]);
    await view.unmount();
  } finally {
    globalThis.fetch = originalFetch;
    restore();
  }
});

test("a failed share request leaves sharing off and exposes no link", async () => {
  const restore = installDom();
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async (_input: RequestInfo | URL, init?: RequestInit) => init?.method === "PUT"
    ? new Response("Unavailable", { status: 503 })
    : Response.json({ url: null, shared_at: null })) as typeof fetch;
  try {
    window.confirm = () => true;
    const view = await renderReact(
      <NextIntlClientProvider locale="en" messages={messages} timeZone="UTC">
        <ArtifactShareControls server={SERVER} slug="report" />
      </NextIntlClientProvider>,
    );
    await settle();
    const toggle = view.container.querySelector('[role="switch"]');
    assert.ok(toggle);
    await click(toggle);
    await settle();
    assert.equal(toggle.getAttribute("aria-checked"), "false");
    assert.equal(view.container.querySelector("a"), null);
    assert.equal(view.container.querySelector('[role="alert"]')?.textContent, messages.artifacts.sharing.updateError);
    await view.unmount();
  } finally {
    globalThis.fetch = originalFetch;
    restore();
  }
});
