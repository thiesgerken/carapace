import assert from "node:assert/strict";
import test from "node:test";
import { NextIntlClientProvider } from "next-intl";

import de from "../../messages/de.json";
import en from "../../messages/en.json";
import { installDom, renderReact } from "../../test/react-test-utils";
import type { LlmActivity } from "@/lib/types";

import { WaitingIndicator } from "./waiting-indicator";

const ago = (ms: number) => new Date(Date.now() - ms).toISOString();

async function text(activity: LlmActivity | null, locale: "en" | "de" = "en"): Promise<string> {
  const view = await renderReact(
    <NextIntlClientProvider locale={locale} messages={locale === "en" ? en : de} timeZone="UTC">
      <WaitingIndicator activity={activity} />
    </NextIntlClientProvider>,
  );
  const content = view.container.textContent ?? "";
  await view.unmount();
  return content;
}

test("WaitingIndicator names the phase and counts time and approximate tokens", async () => {
  const restore = installDom();
  try {
    const activity: LlmActivity = { request_id: "r1", source: "agent", phase: "generating", started_at: ago(78_500), streamed_chars: 7_300 };
    assert.equal(await text(activity), "Generating...1 min 18 s · ~1.8k tokens");
    assert.equal(await text(activity, "de"), "Generiere...1 min 18 s · ~1,8k Tokens");
    // A tool call whose live card hasn't arrived yet is plain generating.
    assert.equal(await text({ ...activity, phase: "tool_call", tool_name: "exec" }), "Generating...1 min 18 s · ~1.8k tokens");
    // Before the first token only the clock runs.
    assert.equal(await text({ ...activity, phase: "processing_prompt", started_at: ago(3_200), streamed_chars: 0 }), "Processing prompt...3 s");
    // Other roles' requests (the sentinel's) leave the agent's waiting label generic.
    assert.equal(await text({ ...activity, source: "sentinel" }), "Working...");
    assert.equal(await text(null), "Working...");
  } finally {
    restore();
  }
});
