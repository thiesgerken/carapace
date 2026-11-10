import assert from "node:assert/strict";
import { setTimeout as sleep } from "node:timers/promises";
import test from "node:test";
import type { SessionSearchHit } from "@/lib/types";
import { useSessionSearch, type SessionSearchMode, type SessionSearchResult } from "./use-session-search";
import { installDom, renderReact, runInAct } from "../../test/react-test-utils";

const originalFetch = globalThis.fetch;

function HookHarness({
  query,
  mode,
  refreshKey,
  onResult,
}: {
  query: string;
  mode: SessionSearchMode;
  refreshKey: number;
  onResult: (result: SessionSearchResult) => void;
}) {
  onResult(useSessionSearch("https://carapace.example.test", "token-1", query, mode, refreshKey));
  return null;
}

function hit(sessionId: string, snippet: string | null): SessionSearchHit {
  return { session: { session_id: sessionId } as SessionSearchHit["session"], snippet };
}

test.afterEach(() => {
  Object.defineProperty(globalThis, "fetch", { configurable: true, writable: true, value: originalFetch });
});

test("useSessionSearch stays idle on a blank query and debounces one request per query", async () => {
  const restoreDom = installDom();
  const urls: string[] = [];
  Object.defineProperty(globalThis, "fetch", {
    configurable: true,
    writable: true,
    value: async (input: string | URL | Request) => {
      urls.push(String(input));
      return Response.json([hit("s1", "…with buttermilk…")]);
    },
  });
  const results: SessionSearchResult[] = [];
  const onResult = (result: SessionSearchResult) => {
    results.push(result);
  };

  try {
    const view = await renderReact(<HookHarness query="  " mode="title" refreshKey={0} onResult={onResult} />);
    await runInAct(() => sleep(300));
    assert.deepEqual(results.at(-1), { hits: null, loading: false, failed: false });
    assert.deepEqual(urls, []);

    await view.rerender(<HookHarness query="butter" mode="fulltext" refreshKey={0} onResult={onResult} />);
    await view.rerender(<HookHarness query="buttermilk " mode="fulltext" refreshKey={0} onResult={onResult} />);
    assert.equal(results.at(-1)?.loading, true);
    await runInAct(() => sleep(300));

    assert.deepEqual(urls, ["https://carapace.example.test/api/sessions/search?q=buttermilk&fulltext=true"]);
    assert.deepEqual(results.at(-1), { hits: [hit("s1", "…with buttermilk…")], loading: false, failed: false });

    await view.rerender(<HookHarness query="buttermilk " mode="fulltext" refreshKey={1} onResult={onResult} />);
    await runInAct(() => sleep(300));
    assert.equal(urls.length, 2);

    await view.unmount();
  } finally {
    restoreDom();
  }
});

test("useSessionSearch reports a failed request", async () => {
  const restoreDom = installDom();
  Object.defineProperty(globalThis, "fetch", {
    configurable: true,
    writable: true,
    value: async () => new Response(JSON.stringify({ detail: "boom" }), { status: 500 }),
  });
  const results: SessionSearchResult[] = [];

  try {
    const view = await renderReact(
      <HookHarness query="pancakes" mode="title" refreshKey={0} onResult={(result) => results.push(result)} />,
    );
    await runInAct(() => sleep(300));

    assert.deepEqual(results.at(-1), { hits: [], loading: false, failed: true });
    await view.unmount();
  } finally {
    restoreDom();
  }
});
