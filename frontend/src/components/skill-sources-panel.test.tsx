import assert from "node:assert/strict";
import test from "node:test";
import { NextIntlClientProvider } from "next-intl";

import messages from "../../messages/en.json";
import { click, flushReact, installDom, renderReact, runInAct, setInputValue } from "../../test/react-test-utils";
import type { KnowledgeSkillsConfig, KnowledgeSkillSources } from "@/lib/api";

import { SkillSourcesPanel } from "./skill-sources-panel";

const SERVER = "https://carapace.example.test";

const checked: KnowledgeSkillSources = {
  checked_at: "2026-11-21T08:00:00Z",
  checking: false,
  check_error: null,
  config_error: null,
  skills: [
    {
      name: "tracker",
      path: null,
      origin: "github:someone/tracker",
      locked_rev: "a".repeat(40),
      locked_at: "2026-11-01T00:00:00Z",
      update: { state: "available", available_rev: "b".repeat(40), available_at: "2026-11-20T00:00:00Z", detail: "" },
      overridden: true,
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
      overridden: false,
    },
    {
      name: "archive",
      path: null,
      origin: "https://example.com/archive.tar.gz",
      locked_rev: null,
      locked_at: "2026-11-02T00:00:00Z",
      update: { state: "current", available_rev: null, available_at: null, detail: "" },
      overridden: false,
    },
  ],
};

const noConfig: KnowledgeSkillsConfig = { base: "", skills: [] };

test("the skill list shows origin, locked rev and the update verdict, and starts a check", async () => {
  const restore = installDom();
  const originalFetch = globalThis.fetch;
  const requests: string[] = [];
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    const path = new URL(String(input)).pathname;
    if (path.endsWith("/config")) return Response.json(noConfig);
    requests.push(`${method} ${path}`);
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
    // Only the skill skills/flake.nix overrides carries the marker.
    const rowOf = (name: string) => Array.from(view.container.querySelectorAll("tr")).find((row) => row.textContent?.includes(name));
    assert.match(rowOf("github:someone/tracker")?.textContent ?? "", /overridden/);
    assert.doesNotMatch(rowOf("./notes")?.textContent ?? "", /overridden/);

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

test("an available update has an Update button; a refused update shows the server's reason", async () => {
  const restore = installDom();
  const originalFetch = globalThis.fetch;
  const requests: string[] = [];
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    const path = new URL(String(input)).pathname;
    if (path.endsWith("/config")) return Response.json(noConfig);
    requests.push(`${method} ${path}`);
    if (method === "POST") {
      return Response.json({ detail: "skills/flake.lock changed in the meantime; nothing was committed" }, { status: 409 });
    }
    return Response.json(checked);
  }) as typeof fetch;

  try {
    const view = await renderReact(
      <NextIntlClientProvider locale="en" messages={messages} timeZone="UTC">
        <SkillSourcesPanel server={SERVER} />
      </NextIntlClientProvider>,
    );
    await flushReact();
    const updates = Array.from(view.container.querySelectorAll("button")).filter((b) => b.textContent?.trim() === "Update");
    // Only tracker has an update; the outdated and current skills get no button.
    assert.equal(updates.length, 1);
    await click(updates[0]);
    await runInAct(() => new Promise((resolve) => setTimeout(resolve, 0)));

    assert.deepEqual(requests, ["GET /api/knowledge/skills", "POST /api/knowledge/skills/tracker/update"]);
    assert.match(view.container.textContent ?? "", /changed in the meantime/);
    await view.unmount();
  } finally {
    globalThis.fetch = originalFetch;
    restore();
  }
});

test("a skill missing a setting or a binding says so, and saving commits only what changed against config.json's version", async () => {
  const restore = installDom();
  const originalFetch = globalThis.fetch;
  const puts: { path: string; body: unknown }[] = [];
  const config: KnowledgeSkillsConfig = {
    base: "c".repeat(40),
    skills: [
      {
        name: "tracker",
        enabled: true,
        state: "failed",
        detail: "error: skill tracker: no value for its setting DAYS; set it in skills/config.json",
        settings: [
          { name: "CITY", type: "str", description: "City", default: "Berlin", value: "Kiel", missing: false },
          { name: "DAYS", type: "int", description: "Days ahead", default: null, value: null, missing: true },
        ],
        credentials: [{ name: "API_KEY", type: "secret", description: "Weather API key", binding: null }],
      },
    ],
  };
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = new URL(String(input)).pathname;
    if (init?.method === "PUT") {
      puts.push({ path, body: JSON.parse(String(init.body)) });
      return Response.json({ ...config, base: "d".repeat(40) });
    }
    if (path.endsWith("/credentials")) return Response.json([{ vault_path: "personal/weather", name: "Weather", description: "" }]);
    return Response.json(path.endsWith("/config") ? config : checked);
  }) as typeof fetch;

  try {
    const view = await renderReact(
      <NextIntlClientProvider locale="en" messages={messages} timeZone="UTC">
        <SkillSourcesPanel server={SERVER} />
      </NextIntlClientProvider>,
    );
    await flushReact();
    const text = () => view.container.textContent ?? "";
    assert.match(text(), /Needs configuration/);
    assert.match(text(), /Credential not bound/);

    const settings = Array.from(view.container.querySelectorAll("button")).find((b) => b.textContent?.trim() === "Settings");
    assert.ok(settings);
    await click(settings);
    // Nix's own word on the values, in the same table.
    assert.match(text(), /no value for its setting DAYS/);
    const days = view.container.querySelector<HTMLInputElement>("#skill-setting-DAYS");
    assert.ok(days);
    await setInputValue(days, "3");
    await flushReact();
    // The datalist offers the user's entries by vault path.
    assert.ok(view.container.querySelector('datalist option[value="personal/weather"]'));
    const apiKey = view.container.querySelector<HTMLInputElement>("#skill-credential-API_KEY");
    assert.ok(apiKey);
    await setInputValue(apiKey, "personal/weather");
    const save = Array.from(view.container.querySelectorAll("button")).find((b) => b.textContent?.trim() === "Save");
    assert.ok(save);
    await click(save);
    await runInAct(() => new Promise((resolve) => setTimeout(resolve, 0)));

    assert.deepEqual(puts, [
      { path: "/api/knowledge/skills/tracker/config", body: {
          base: "c".repeat(40),
          enable: true,
          settings: { DAYS: 3 },
          credentials: { API_KEY: "personal/weather" },
        },
      },
    ]);
    await view.unmount();
  } finally {
    globalThis.fetch = originalFetch;
    restore();
  }
});
