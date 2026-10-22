import assert from "node:assert/strict";
import test from "node:test";
import { setTimeout } from "node:timers/promises";
import { NextIntlClientProvider } from "next-intl";

import messages from "../../messages/en.json";
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
