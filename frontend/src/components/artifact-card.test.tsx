import assert from "node:assert/strict";
import test from "node:test";
import { setTimeout } from "node:timers/promises";
import { NextIntlClientProvider } from "next-intl";

import english from "../../messages/en.json";
import german from "../../messages/de.json";
import { installDom, renderReact, runInAct } from "../../test/react-test-utils";
import { ToolCallBadge } from "./tool-call-badge";

const SERVER = "https://carapace.example.test";

function delivery(path: string, mime: string) {
  return <ToolCallBadge tool="send_file" args={{ path }} detail="" result="Sent file" files={[{ file_id: "f1", name: path.split("/").at(-1)!, mime, size: 120 }]} server={SERVER} sessionId="s1" />;
}

test("artifact delivery labels use the persisted snapshot title in English and German, not the live title", async () => {
  const restore = installDom();
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async (input) => new Response(String(input).includes("/api/sessions/")
    ? "<head><title> Snapshot &amp;\n review </title></head><svg><title>Not the page title</title></svg>"
    : "<title>Live revision</title>")) as typeof fetch;
  try {
    for (const [locale, messages, expected] of [["en", english, "Artifact · Snapshot & review"], ["de", german, "Artefakt · Snapshot & review"]] as const) {
      const view = await renderReact(
        <NextIntlClientProvider locale={locale} messages={messages} timeZone="UTC">
          {delivery("/workspace/artifacts/report/index.html", "text/html")}
        </NextIntlClientProvider>,
      );
      await runInAct(() => setTimeout(0));
      assert.equal(view.container.querySelector("button > span.font-medium")?.textContent, expected);
      await view.unmount();
    }
  } finally {
    globalThis.fetch = originalFetch;
    restore();
  }
});

test("a missing snapshot title falls back to the artifact slug while ordinary HTML, images, and downloads retain their label", async () => {
  const restore = installDom();
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async () => new Response("<title> \n </title>")) as typeof fetch;
  try {
    for (const [path, mime, expected] of [
      ["/workspace/artifacts/release-review/index.html", "text/html", "Artifact · release-review"],
      ["/workspace/report.html", "text/html", english.toolCallBadge.labels.sentFile],
      ["/workspace/chart.png", "image/png", english.toolCallBadge.labels.sentFile],
      ["/workspace/data.csv", "text/csv", english.toolCallBadge.labels.sentFile],
    ]) {
      const view = await renderReact(
        <NextIntlClientProvider locale="en" messages={english} timeZone="UTC">{delivery(path, mime)}</NextIntlClientProvider>,
      );
      await runInAct(() => setTimeout(0));
      assert.equal(view.container.querySelector("button > span.font-medium")?.textContent, expected);
      await view.unmount();
    }
  } finally {
    globalThis.fetch = originalFetch;
    restore();
  }
});
