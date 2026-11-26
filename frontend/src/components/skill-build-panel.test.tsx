import assert from "node:assert/strict";
import test from "node:test";
import { NextIntlClientProvider } from "next-intl";

import messages from "../../messages/en.json";
import { click, installDom, renderReact, runInAct } from "../../test/react-test-utils";
import type { KnowledgeSkillBuild } from "@/lib/api";

import { SkillBuildPanel } from "./skill-build-panel";

const SERVER = "https://carapace.example.test";
const KEY = "9f2b6c1e4d8a3f7b0c5e2d9a6b1f4c8e7d3a0b5c2e9f6d1a8b4c7e0f3a6d9b2c";

const failed: KnowledgeSkillBuild = { state: "failed", key: KEY, commands: {}, log_tail: "error: flake.lock is missing nixpkgs" };
const building: KnowledgeSkillBuild = { state: "building", key: KEY, commands: {}, log_tail: "" };

test("a failed build shows its log and retries into building", async () => {
  const restore = installDom();
  const originalFetch = globalThis.fetch;
  const requests: string[] = [];
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = new URL(String(input)).pathname;
    requests.push(`${init?.method ?? "GET"} ${path}`);
    return Response.json(building);
  }) as typeof fetch;

  try {
    const view = await renderReact(
      <NextIntlClientProvider locale="en" messages={messages} timeZone="UTC">
        <SkillBuildPanel server={SERVER} skill="weather" initial={failed} />
      </NextIntlClientProvider>,
    );
    const text = () => view.container.textContent ?? "";
    assert.match(text(), /Failed/);
    assert.match(text(), /error: flake\.lock is missing nixpkgs/);
    assert.match(text(), /9f2b6c1e4d8a/);

    const retry = Array.from(view.container.querySelectorAll("button")).find((button) => button.textContent?.trim() === "Retry");
    assert.ok(retry);
    await click(retry);
    await runInAct(() => new Promise((resolve) => setTimeout(resolve, 0)));

    assert.deepEqual(requests, ["POST /api/knowledge/skills/weather/build/retry"]);
    assert.match(text(), /Building/);
    assert.equal(
      Array.from(view.container.querySelectorAll("button")).some((button) => button.textContent?.trim() === "Retry"),
      false,
    );
    await view.unmount();
  } finally {
    globalThis.fetch = originalFetch;
    restore();
  }
});
