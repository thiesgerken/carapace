import assert from "node:assert/strict";
import test from "node:test";
import { setTimeout } from "node:timers/promises";
import { NextIntlClientProvider } from "next-intl";

import english from "../../messages/en.json";
import german from "../../messages/de.json";
import { click, installDom, renderReact, runInAct } from "../../test/react-test-utils";
import type { ArtifactReference } from "@/lib/artifacts";
import { ToolCallBadge } from "./tool-call-badge";

const SERVER = "https://carapace.example.test";

function reference(artifactReference: ArtifactReference) {
  return <ToolCallBadge tool="show_artifact" args={{ slug: artifactReference.slug }} detail="" result="{}" exitCode={0} server={SERVER} sessionId="s1" artifactReference={artifactReference} />;
}

function serveArtifact(title: string | null): string[] {
  const requests: string[] = [];
  globalThis.fetch = (async (input) => {
    const url = String(input);
    requests.push(url);
    if (url.endsWith("/share")) return Response.json({ url: null, shared_at: null });
    if (title === null) return Response.json({ detail: "Not found" }, { status: 404 });
    return Response.json({ type: "dir", artifact: { slug: "report", title, created_in: null, updated_in: null } });
  }) as typeof fetch;
  return requests;
}

test("an artifact reference shows the live title, starts collapsed, and expands to the live route", async () => {
  const restore = installDom();
  const originalFetch = globalThis.fetch;
  serveArtifact("Quarterly report");
  try {
    for (const [locale, messages, update, expected] of [
      ["en", english, false, "Artifact · Quarterly report"],
      ["de", german, false, "Artefakt · Quarterly report"],
      ["de", german, true, "Artefakt aktualisiert · Quarterly report"],
    ] as const) {
      const view = await renderReact(
        <NextIntlClientProvider locale={locale} messages={messages} timeZone="UTC">
          {reference({ slug: "report", update, revision: 1 })}
        </NextIntlClientProvider>,
      );
      await runInAct(() => setTimeout(0));
      assert.equal(view.container.querySelector("button > span.font-medium")?.textContent, expected);
      const toggle = view.container.querySelector("button");
      assert.ok(toggle);
      assert.equal(toggle.getAttribute("aria-expanded"), "false");
      assert.equal(view.container.querySelector("iframe"), null);
      const viewerLink = view.container.querySelector('a[target="_blank"]');
      assert.equal(viewerLink?.getAttribute("href"), "/artifacts?slug=report");
      await click(toggle);
      await runInAct(() => setTimeout(0));
      assert.equal(view.container.querySelector("iframe")?.getAttribute("src"), `${SERVER}/api/artifacts/report`);
      await view.unmount();
    }
  } finally {
    globalThis.fetch = originalFetch;
    restore();
  }
});

test("a new reference to the slug reloads the preview on the artifact's current state", async () => {
  const restore = installDom();
  const originalFetch = globalThis.fetch;
  const requests = serveArtifact("v1");
  try {
    const render = (revision: number) => (
      <NextIntlClientProvider locale="en" messages={english} timeZone="UTC">
        {reference({ slug: "report", update: false, revision })}
      </NextIntlClientProvider>
    );
    const view = await renderReact(render(1));
    await runInAct(() => setTimeout(0));
    await click(view.container.querySelector("button")!);
    const firstFrame = view.container.querySelector("iframe");
    assert.ok(firstFrame);
    serveArtifact("v2");
    await view.rerender(render(2));
    await runInAct(() => setTimeout(0));
    assert.equal(view.container.querySelector("button > span.font-medium")?.textContent, "Artifact · v2");
    const secondFrame = view.container.querySelector("iframe");
    assert.ok(secondFrame && secondFrame !== firstFrame);
    assert.ok(requests.some((url) => url === `${SERVER}/api/knowledge/browse/artifacts/report`));
    await view.unmount();
  } finally {
    globalThis.fetch = originalFetch;
    restore();
  }
});

test("a deleted or renamed artifact says so in its collapsed row and has nothing to expand", async () => {
  const restore = installDom();
  const originalFetch = globalThis.fetch;
  serveArtifact(null);
  try {
    for (const [update, expected] of [[false, "Artefakt · report · existiert nicht mehr"], [true, "Artefakt aktualisiert · report · existiert nicht mehr"]] as const) {
      const view = await renderReact(
        <NextIntlClientProvider locale="de" messages={german} timeZone="UTC">
          {reference({ slug: "report", update, revision: 1 })}
        </NextIntlClientProvider>,
      );
      await runInAct(() => setTimeout(0));
      assert.equal(view.container.querySelector("button > span.font-medium")?.textContent, expected);
      const toggle = view.container.querySelector("button");
      assert.ok(toggle?.disabled);
      assert.equal(toggle.getAttribute("aria-expanded"), null);
      await click(toggle);
      assert.equal(view.container.querySelector("iframe"), null);
      assert.equal(view.container.querySelector('a[target="_blank"]'), null);
      await view.unmount();
    }
  } finally {
    globalThis.fetch = originalFetch;
    restore();
  }
});
