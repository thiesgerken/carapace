import assert from "node:assert/strict";
import test from "node:test";
import { setTimeout } from "node:timers/promises";
import { NextIntlClientProvider } from "next-intl";

import messages from "../../messages/en.json";
import germanMessages from "../../messages/de.json";
import { click, installDom, renderReact, runInAct } from "../../test/react-test-utils";
import { FilePreview } from "./file-preview";

const SERVER = "https://carapace.example.test";

test("an HTML snapshot switches between a sandboxed preview and escaped source, retaining its download", async () => {
  const restore = installDom();
  const originalFetch = globalThis.fetch;
  const html = '<h1>Report</h1><script>parent.document.body.remove()</script>';
  globalThis.fetch = (async () => new Response(html)) as typeof fetch;
  try {
    const view = await renderReact(
      <NextIntlClientProvider locale="en" messages={messages} timeZone="UTC">
        <FilePreview fileId="f1" name="index.html" mime="text/html" server={SERVER} sessionId="s1" />
      </NextIntlClientProvider>,
    );
    const frame = view.container.querySelector("iframe");
    assert.ok(frame);
    assert.equal(frame.getAttribute("sandbox"), "allow-scripts");
    assert.equal(frame.getAttribute("src"), `${SERVER}/api/sessions/s1/files/f1?artifact=1`);
    assert.equal(view.container.querySelector('a[target="_blank"]')?.getAttribute("href"), frame.src);
    assert.equal(view.container.querySelector('a[download]')?.getAttribute("href"), `${SERVER}/api/sessions/s1/files/f1?download=1`);
    const toggle = view.container.querySelector("button");
    assert.ok(toggle);
    await click(toggle);
    await runInAct(() => setTimeout(0));
    assert.equal(view.container.querySelector("iframe"), null);
    assert.equal(view.container.querySelector("pre")?.textContent, html);
    assert.equal(view.container.querySelector("script"), null);
    await click(toggle);
    assert.ok(view.container.querySelector("iframe"));
    await view.unmount();
  } finally {
    globalThis.fetch = originalFetch;
    restore();
  }
});

test("artifact source failures use the selected locale rather than raw HTTP error text", async () => {
  const restore = installDom();
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async () => new Response("Not found", { status: 404 })) as typeof fetch;
  try {
    const view = await renderReact(
      <NextIntlClientProvider locale="de" messages={germanMessages} timeZone="UTC">
        <FilePreview fileId="f1" name="index.html" mime="text/html" server={SERVER} sessionId="s1" />
      </NextIntlClientProvider>,
    );
    const toggle = view.container.querySelector("button");
    assert.ok(toggle);
    await click(toggle);
    await runInAct(() => setTimeout(0));
    assert.equal(view.container.querySelector('[role="alert"]')?.textContent, germanMessages.artifacts.sourceError);
    await view.unmount();
  } finally {
    globalThis.fetch = originalFetch;
    restore();
  }
});

test("only sent artifact entry points link to the live viewer, not other HTML or escaping paths", async () => {
  const restore = installDom();
  try {
    for (const [path, expected] of [
      ["/workspace/artifacts/report/index.html", "/artifacts?slug=report"],
      ["/workspace/reports/index.html", undefined],
      ["/workspace/artifacts/../index.html", undefined],
    ] as const) {
      const view = await renderReact(
        <NextIntlClientProvider locale="en" messages={messages} timeZone="UTC">
          <FilePreview fileId="f1" name="index.html" path={path} mime="text/html" server={SERVER} sessionId="s1" />
        </NextIntlClientProvider>,
      );
      assert.equal(view.container.querySelector('a[href^="/artifacts?"]')?.getAttribute("href"), expected);
      await view.unmount();
    }
  } finally {
    restore();
  }
});
