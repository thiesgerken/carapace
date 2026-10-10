import assert from "node:assert/strict";
import test from "node:test";
import { NextIntlClientProvider } from "next-intl";

import messages from "../../messages/en.json";
import { installDom, renderReact } from "../../test/react-test-utils";

import { VersionBadge } from "./version-badge";

test("the mismatch warning stays outside the clipped version slot", async () => {
  const restore = installDom();
  try {
    const view = await renderReact(
      <NextIntlClientProvider locale="en" messages={messages} timeZone="UTC">
        <VersionBadge frontendVersion="0.158.6" backendVersion="0.158.7" />
      </NextIntlClientProvider>,
    );
    const clip = view.container.querySelector(".overflow-hidden");
    assert.ok(clip);
    assert.match(clip.textContent ?? "", /^v0\.158\.7$/);
    const warning = view.container.querySelector("svg");
    assert.ok(warning && !clip.contains(warning));
    await view.unmount();
  } finally {
    restore();
  }
});
