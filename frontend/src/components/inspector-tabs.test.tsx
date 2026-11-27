import assert from "node:assert/strict";
import test from "node:test";
import { NextIntlClientProvider } from "next-intl";

import english from "../../messages/en.json";
import german from "../../messages/de.json";
import type { InspectorTab } from "../lib/inspector-tabs";
import { click, installDom, renderReact } from "../../test/react-test-utils";
import { InspectorTabs } from "./inspector-tabs";

test("the inspector tabs mark the selected tab and report clicks, in both locales", async () => {
  const restore = installDom();
  try {
    for (const [locale, messages, labels] of [
      ["en", english, ["Session", "Usage", "Environment", "Content"]],
      ["de", german, ["Session", "Nutzung", "Umgebung", "Inhalte"]],
    ] as const) {
      const picked: InspectorTab[] = [];
      const view = await renderReact(
        <NextIntlClientProvider locale={locale} messages={messages} timeZone="UTC">
          <InspectorTabs value="usage" onChange={(tab) => picked.push(tab)} />
        </NextIntlClientProvider>,
      );
      const tabs = Array.from(view.container.querySelectorAll('[role="tab"]'));
      assert.deepEqual(tabs.map((tab) => tab.textContent), labels);
      assert.deepEqual(tabs.map((tab) => tab.getAttribute("aria-selected")), ["false", "true", "false", "false"]);
      assert.deepEqual(tabs.map((tab) => tab.getAttribute("tabindex")), ["-1", "0", "-1", "-1"]);

      await click(tabs[3]);
      assert.deepEqual(picked, ["content"]);
      await view.unmount();
    }
  } finally {
    restore();
  }
});
