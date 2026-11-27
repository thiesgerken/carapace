import assert from "node:assert/strict";
import test from "node:test";
import { PathnameContext } from "next/dist/shared/lib/hooks-client-context.shared-runtime";
import { NextIntlClientProvider } from "next-intl";

import english from "../../messages/en.json";
import { click, installDom, renderReact, runInAct } from "../../test/react-test-utils";
import { SidebarFooter } from "./sidebar-footer";

function renderFooter(pathname = "/") {
  return renderReact(
    <PathnameContext.Provider value={pathname}>
      <NextIntlClientProvider locale="en" messages={english} timeZone="UTC">
        <SidebarFooter
          server=""
          token="demo"
          currentUser={{ username: "demo", display_name: "Demo User" } as never}
          frontendVersion="1.0.0"
          backendVersion="1.0.0"
          githubUrl="https://github.com/thiesgerken/carapace"
          onNavigate={() => {}}
          onDisconnect={() => {}}
        />
      </NextIntlClientProvider>
    </PathnameContext.Provider>,
  );
}

/** Lets the git status fetches and the re-reads they trigger settle. */
const settle = () => runInAct(() => new Promise((resolve) => setTimeout(resolve, 10)));

test("the account menu holds the navigation, marks the current route and closes on navigation", async () => {
  const restore = installDom();
  const originalFetch = globalThis.fetch;
  // No knowledge remote: the sync row stays hidden.
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

test("the knowledge sync row stays hidden while the repo is in sync with its remote", async () => {
  const restore = installDom();
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async () =>
    new Response(JSON.stringify({ remote_configured: true, ahead: 0, behind: 0, head: null, head_subject: null }))) as typeof fetch;
  try {
    const view = await renderFooter();
    await settle();
    assert.equal(view.container.querySelector('a[href="/knowledge"]'), null);
    assert.equal(view.container.querySelector('button[aria-label^="Sync"]'), null);
    await view.unmount();
  } finally {
    globalThis.fetch = originalFetch;
    restore();
  }
});

test("the knowledge sync row shows behind/ahead and syncs by pulling, then pushing", async () => {
  const restore = installDom();
  const originalFetch = globalThis.fetch;
  const calls: string[] = [];
  let counts = { ahead: 1, behind: 2 };
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    const path = String(input);
    if (path.endsWith("/api/git/status")) {
      return new Response(JSON.stringify({ remote_configured: true, ...counts, head: null, head_subject: null }));
    }
    calls.push(path);
    if (path.endsWith("/api/git/push")) counts = { ahead: 0, behind: 0 };
    return new Response(JSON.stringify({ ok: true, message: "", denied: false }));
  }) as typeof fetch;
  try {
    const view = await renderFooter();
    await settle();
    const row = view.container.querySelector('a[href="/knowledge"]');
    assert.equal(row?.textContent, "Knowledge21");
    assert.equal(row?.getAttribute("title"), "Not in sync with the knowledge remote: 2 to pull, 1 to push");

    await click(view.container.querySelector('button[aria-label^="Sync"]')!);
    await settle();
    assert.deepEqual(calls, ["/api/git/pull", "/api/git/push"]);
    assert.equal(view.container.querySelector('a[href="/knowledge"]'), null);
    await view.unmount();
  } finally {
    globalThis.fetch = originalFetch;
    restore();
  }
});

test("the knowledge sync row skips the push when the pull fails and shows the error", async () => {
  const restore = installDom();
  const originalFetch = globalThis.fetch;
  const calls: string[] = [];
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    const path = String(input);
    if (path.endsWith("/api/git/status")) {
      return new Response(JSON.stringify({ remote_configured: true, ahead: 1, behind: 1, head: null, head_subject: null }));
    }
    calls.push(path);
    return new Response(JSON.stringify({ ok: false, message: "Merge conflict in knowledge repo", denied: false }));
  }) as typeof fetch;
  try {
    const view = await renderFooter();
    await settle();
    await click(view.container.querySelector('button[aria-label^="Sync"]')!);
    await settle();
    assert.deepEqual(calls, ["/api/git/pull"]);
    const row = view.container.querySelector('a[href="/knowledge"]');
    assert.equal(row?.textContent, "KnowledgePull failed");
    assert.equal(row?.getAttribute("title"), "Merge conflict in knowledge repo");
    await view.unmount();
  } finally {
    globalThis.fetch = originalFetch;
    restore();
  }
});

test("a sync holds the button busy across pull and push, and re-reads status only after the push", async () => {
  const restore = installDom();
  const originalFetch = globalThis.fetch;
  const calls: string[] = [];
  const pending = new Map<string, (body: object) => void>();
  // Every request after the first status read waits until the test answers it.
  const respond = async (path: string, body: object) => {
    await runInAct(() => pending.get(path)!(body));
    pending.delete(path);
  };
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    const path = String(input);
    calls.push(path);
    if (calls.length === 1) {
      return new Response(JSON.stringify({ remote_configured: true, ahead: 1, behind: 2, head: null, head_subject: null }));
    }
    return new Promise<Response>((resolve) => {
      pending.set(path, (body) => resolve(new Response(JSON.stringify(body))));
    });
  }) as typeof fetch;
  try {
    const view = await renderFooter();
    await settle();
    const button = () => view.container.querySelector<HTMLButtonElement>('button[aria-label^="Sync"]')!;

    await click(button());
    assert.equal(button().disabled, true);
    await respond("/api/git/pull", { ok: true, message: "Merged", denied: false });
    assert.equal(button().disabled, true);
    assert.deepEqual(calls.slice(1), ["/api/git/pull", "/api/git/push"]);

    await respond("/api/git/push", { ok: false, message: "rejected: non-fast-forward", denied: false });
    assert.deepEqual(calls.slice(1), ["/api/git/pull", "/api/git/push", "/api/git/status"]);
    // The re-read lands after the push failed and must not clear its error.
    await respond("/api/git/status", { remote_configured: true, ahead: 2, behind: 0, head: null, head_subject: null });
    const row = view.container.querySelector('a[href="/knowledge"]');
    assert.equal(row?.textContent, "KnowledgePush failed");
    assert.equal(row?.getAttribute("title"), "rejected: non-fast-forward");
    assert.equal(button().disabled, false);
    await view.unmount();
  } finally {
    globalThis.fetch = originalFetch;
    restore();
  }
});
