import assert from "node:assert/strict";
import test from "node:test";
import { NextIntlClientProvider } from "next-intl";

import messages from "../../messages/en.json";
import { click, flushReact, installDom, renderReact, runInAct } from "../../test/react-test-utils";
import type { KnowledgeSkillSources } from "@/lib/api";

import { SkillSourcesPanel } from "./skill-sources-panel";

const SERVER = "https://carapace.example.test";

const checked: KnowledgeSkillSources = {
  checked_at: "2026-11-21T08:00:00Z",
  checking: false,
  check_error: null,
  skills: [
    {
      name: "tracker",
      path: null,
      origin: "github:someone/tracker",
      locked_rev: "a".repeat(40),
      locked_at: "2026-11-01T00:00:00Z",
      update: { state: "available", available_rev: "b".repeat(40), available_at: "2026-11-20T00:00:00Z", detail: "" },
    },
    {
      name: "notes",
      path: "skills/notes",
      origin: "./notes",
      locked_rev: null,
      locked_at: null,
      update: {
        state: "outdated",
        available_rev: null,
        available_at: null,
        detail: "Its inputs changed: run `nix flake update notes --flake ./skills` and commit skills/flake.lock.",
      },
    },
    {
      name: "archive",
      path: null,
      origin: "https://example.com/archive.tar.gz",
      locked_rev: null,
      locked_at: "2026-11-02T00:00:00Z",
      update: { state: "current", available_rev: null, available_at: null, detail: "" },
    },
  ],
};

test("the skill list shows origin, locked rev and the update verdict, and starts a check", async () => {
  const restore = installDom();
  const originalFetch = globalThis.fetch;
  const requests: string[] = [];
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    requests.push(`${method} ${new URL(String(input)).pathname}`);
    return Response.json(method === "POST" ? { ...checked, checking: true } : checked);
  }) as typeof fetch;

  try {
    const view = await renderReact(
      <NextIntlClientProvider locale="en" messages={messages} timeZone="UTC">
        <SkillSourcesPanel server={SERVER} />
      </NextIntlClientProvider>,
    );
    await flushReact();
    const text = () => view.container.textContent ?? "";
    assert.match(text(), /github:someone\/tracker/);
    assert.match(text(), /aaaaaaa/);
    assert.match(text(), /Update available/);
    assert.match(text(), /bbbbbbb/);
    assert.match(text(), /Lock outdated/);
    assert.match(text(), /nix flake update notes --flake \.\/skills/);
    // A tarball input has no rev: its lock date, not "local".
    const archiveRow = Array.from(view.container.querySelectorAll("tr")).find((row) => row.textContent?.includes("archive.tar.gz"));
    assert.match(archiveRow?.textContent ?? "", /Nov 2, 2026/);
    assert.doesNotMatch(archiveRow?.textContent ?? "", /local/);
    assert.equal(view.container.querySelector('a[href="/knowledge?path=skills%2Fnotes"]')?.textContent, "notes");

    const button = Array.from(view.container.querySelectorAll("button")).find((b) => b.textContent?.trim() === "Check for updates");
    assert.ok(button);
    await click(button);
    await runInAct(() => new Promise((resolve) => setTimeout(resolve, 0)));

    assert.deepEqual(requests, ["GET /api/knowledge/skills", "POST /api/knowledge/skills/updates/check"]);
    assert.match(text(), /Checking…/);
    await view.unmount();
  } finally {
    globalThis.fetch = originalFetch;
    restore();
  }
});
