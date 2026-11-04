import assert from "node:assert/strict";
import test from "node:test";
import { NextIntlClientProvider } from "next-intl";

import messages from "../../messages/en.json";
import { installDom, renderReact } from "../../test/react-test-utils";
import type { SandboxUsage } from "@/lib/types";

import { SandboxUsageBanner } from "./sandbox-usage-banner";

async function renderBanner(usage: SandboxUsage | null): Promise<string | null> {
  const restore = installDom();
  try {
    const view = await renderReact(
      <NextIntlClientProvider locale="en" messages={messages} timeZone="UTC">
        <SandboxUsageBanner usage={usage} />
      </NextIntlClientProvider>,
    );
    const banner = view.container.querySelector("[role]");
    const result = banner ? `${banner.getAttribute("role")}: ${banner.textContent}` : null;
    await view.unmount();
    return result;
  } finally {
    restore();
  }
}

test("no banner below the warning threshold or without usage", async () => {
  assert.equal(await renderBanner({ count: 19, warn_at: 20, max: 100 }), null);
  assert.equal(await renderBanner(null), null);
});

test("warning banner from the warning threshold on", async () => {
  assert.equal(
    await renderBanner({ count: 23, warn_at: 20, max: 100 }),
    "status: 23 sandboxes retained (warning at 20, max 100). Delete old sessions to free storage.",
  );
});

test("warning banner without a hard limit leaves the max out", async () => {
  assert.equal(
    await renderBanner({ count: 23, warn_at: 20, max: 0 }),
    "status: 23 sandboxes retained (warning at 20). Delete old sessions to free storage.",
  );
});

test("error banner at the hard limit", async () => {
  assert.equal(
    await renderBanner({ count: 100, warn_at: 20, max: 100 }),
    "alert: 100/100 sandboxes. New sessions can't start a sandbox until you delete old ones.",
  );
});

test("no banner when both limits are off", async () => {
  assert.equal(await renderBanner({ count: 500, warn_at: 0, max: 0 }), null);
});
