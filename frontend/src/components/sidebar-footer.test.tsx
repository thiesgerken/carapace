import assert from "node:assert/strict";
import test from "node:test";
import { PathnameContext } from "next/dist/shared/lib/hooks-client-context.shared-runtime";
import { NextIntlClientProvider } from "next-intl";

import english from "../../messages/en.json";
import { click, installDom, renderReact } from "../../test/react-test-utils";
import { SidebarFooter } from "./sidebar-footer";

test("the account menu holds the navigation, marks the current route and closes on navigation", async () => {
  const restore = installDom();
  const originalFetch = globalThis.fetch;
  // No knowledge remote: the git indicator stays hidden.
  globalThis.fetch = (async () => new Response(JSON.stringify({ configured: false }))) as typeof fetch;
  try {
    const navigated: string[] = [];
    const view = await renderReact(
      <PathnameContext.Provider value="/memory/facts">
        <NextIntlClientProvider locale="en" messages={english} timeZone="UTC">
          <SidebarFooter
            server=""
            token="demo"
            currentUser={{ username: "demo", display_name: "Demo User" } as never}
            frontendVersion="1.0.0"
            backendVersion="1.0.0"
            githubUrl="https://github.com/thiesgerken/carapace"
            onNavigate={() => navigated.push("nav")}
            onDisconnect={() => {}}
          />
        </NextIntlClientProvider>
      </PathnameContext.Provider>,
    );
    const items = () => Array.from(view.container.querySelectorAll('[role="menuitem"]'));
    assert.equal(view.container.querySelector("nav"), null);
    assert.deepEqual(items(), []);

    await click(view.container.querySelector('button[aria-haspopup="menu"]')!);
    assert.deepEqual(items().map((item) => item.textContent), ["Knowledge", "Memory", "Settings", "thiesgerken/carapacev1.0.0", "Log out"]);
    assert.deepEqual(items().map((item) => item.getAttribute("aria-current")), [null, "page", null, null, null]);

    await click(items()[0]);
    assert.deepEqual(navigated, ["nav"]);
    assert.deepEqual(items(), []);
    await view.unmount();
  } finally {
    globalThis.fetch = originalFetch;
    restore();
  }
});
