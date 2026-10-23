import assert from "node:assert/strict";
import test from "node:test";
import { NextIntlClientProvider } from "next-intl";

import english from "../../messages/en.json";
import german from "../../messages/de.json";
import { installDom, renderReact } from "../../test/react-test-utils";
import { ArtifactToolbar } from "./artifact-toolbar";

const baseArtifact = { server: "", slug: "report" };

test("knowledge and full-screen toolbars link titled creation and update sessions in both locales", async () => {
  const restore = installDom();
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async () => new Response(JSON.stringify({ url: null, shared_at: null }))) as typeof fetch;
  try {
    for (const [locale, messages, fullScreen] of [["en", english, false], ["de", german, true]] as const) {
      const view = await renderReact(
        <NextIntlClientProvider locale={locale} messages={messages} timeZone="UTC">
          <ArtifactToolbar artifact={{ ...baseArtifact, created_in: { session_id: "creator", title: "Create report" }, updated_in: { session_id: "updater", title: "Revise report" } }} title="Report" src="/api/artifacts/report" fullScreen={fullScreen} showSource={false} onToggleSource={() => {}} />
        </NextIntlClientProvider>,
      );
      const creator = view.container.querySelector('a[href="/?session=creator"]');
      const updater = view.container.querySelector('a[href="/?session=updater"]');
      assert.equal(creator?.textContent, "Create report");
      assert.equal(updater?.textContent, "Revise report");
      assert.equal(creator?.parentElement?.textContent, `${messages.artifacts.createdIn}Create report`);
      assert.equal(updater?.parentElement?.textContent, `${messages.artifacts.updatedIn}Revise report`);
      await view.unmount();
    }
  } finally {
    globalThis.fetch = originalFetch;
    restore();
  }
});

test("unavailable session titles render IDs without links and absent history renders no provenance", async () => {
  const restore = installDom();
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async () => new Response(JSON.stringify({ url: null, shared_at: null }))) as typeof fetch;
  try {
    for (const available of [false, true]) {
      const view = await renderReact(
        <NextIntlClientProvider locale="en" messages={english} timeZone="UTC">
          <ArtifactToolbar artifact={{ ...baseArtifact, created_in: available ? { session_id: "deleted-session", title: null } : null, updated_in: available ? { session_id: "foreign-session", title: null } : null }} title="Report" src="/api/artifacts/report" fullScreen={false} showSource={false} onToggleSource={() => {}} />
        </NextIntlClientProvider>,
      );
      assert.equal(view.container.querySelector('a[href^="/?session="]'), null);
      assert.equal(view.container.textContent?.includes("deleted-session"), available);
      assert.equal(view.container.textContent?.includes("foreign-session"), available);
      assert.equal(view.container.textContent?.includes(english.artifacts.createdIn), available);
      assert.equal(view.container.textContent?.includes(english.artifacts.updatedIn), available);
      await view.unmount();
    }
  } finally {
    globalThis.fetch = originalFetch;
    restore();
  }
});
