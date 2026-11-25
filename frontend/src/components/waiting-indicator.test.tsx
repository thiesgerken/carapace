import assert from "node:assert/strict";
import test from "node:test";
import { NextIntlClientProvider } from "next-intl";

import de from "../../messages/de.json";
import en from "../../messages/en.json";
import { installDom, renderReact, runInAct } from "../../test/react-test-utils";
import type { LlmActivity } from "@/lib/types";

import { PHRASES, STALL_MS, WaitingIndicator } from "./waiting-indicator";

// The clock is frozen at NOW, so the elapsed time does not depend on how long the test runs.
const NOW = Date.parse("2026-01-01T12:00:00Z");
const ago = (ms: number) => new Date(NOW - ms).toISOString();

const MESSAGES = { en, de };
type Locale = keyof typeof MESSAGES;
const GENERATING: LlmActivity = { request_id: "r1", source: "agent", phase: "generating", started_at: ago(78_500), streamed_chars: 7_300 };

const node = (activity: LlmActivity | null, locale: Locale = "en") => (
  <NextIntlClientProvider locale={locale} messages={MESSAGES[locale]} timeZone="UTC">
    <WaitingIndicator activity={activity} />
  </NextIntlClientProvider>
);

async function shown(activity: LlmActivity | null, locale: Locale = "en"): Promise<{ text: string; pose: string | null }> {
  const view = await renderReact(node(activity, locale));
  const result = { text: view.container.textContent ?? "", pose: view.container.querySelector("svg")?.getAttribute("data-pose") ?? null };
  await view.unmount();
  return result;
}

/** The phrase of *phase* that *text* opens with; which one is up to the request id, so tests don't pin it. */
function phraseIn(text: string, phase: keyof typeof PHRASES) {
  const texts: Record<string, string> = en.chatView.waiting.phrases;
  const phrase = PHRASES[phase].find(({ key }) => text.startsWith(texts[key]));
  assert.ok(phrase, `"${text}" opens with none of the ${phase} phrases`);
  return phrase;
}

test("every phrase has its text in both languages, and every text a phrase", () => {
  const keys = Object.values(PHRASES).flatMap((phrases) => phrases.map(({ key }) => key)).sort();
  assert.deepEqual(Object.keys(en.chatView.waiting.phrases).sort(), keys);
  assert.deepEqual(Object.keys(de.chatView.waiting.phrases).sort(), keys);
});

test("WaitingIndicator acts out the phase and counts time and approximate tokens", async (t) => {
  t.mock.timers.enable({ apis: ["Date"], now: NOW });
  const restore = installDom();
  try {
    const generating = await shown(GENERATING);
    assert.ok(generating.text.endsWith("1 min 18 s · 1.8k tokens"), generating.text);
    assert.equal(generating.pose, phraseIn(generating.text, "generating").pose);
    // The phrase belongs to the request, so a remount shows the same one.
    assert.deepEqual(await shown(GENERATING), generating);
    assert.ok((await shown(GENERATING, "de")).text.endsWith("1 min 18 s · 1,8k Tokens"));
    // A tool call whose live card hasn't arrived yet is plain generating.
    assert.deepEqual(await shown({ ...GENERATING, phase: "tool_call", tool_name: "exec" }), generating);

    // Before the first token only the clock runs.
    const prompt = await shown({ ...GENERATING, phase: "processing_prompt", started_at: ago(3_200), streamed_chars: 0 });
    assert.ok(prompt.text.endsWith("3 s"), prompt.text);
    assert.equal(prompt.pose, phraseIn(prompt.text, "processing_prompt").pose);

    // The sentinel's requests get their own phrases and no counter, whatever their phase.
    const sentinel = await shown({ ...GENERATING, source: "sentinel" });
    assert.equal(sentinel.pose, phraseIn(sentinel.text, "sentinel").pose);
    assert.ok(!sentinel.text.includes("tokens"), sentinel.text);
    assert.deepEqual(await shown(null), { text: "Working…", pose: "pulse" });
  } finally {
    restore();
  }
});

test("WaitingIndicator dozes off without progress and wakes on the next token", async (t) => {
  t.mock.timers.enable({ apis: ["Date", "setInterval"], now: NOW });
  const restore = installDom();
  try {
    const view = await renderReact(node(GENERATING));
    const pose = () => view.container.querySelector("svg")?.getAttribute("data-pose");
    const label = () => view.container.querySelector(".text-shimmer")?.textContent;
    const awake = pose();
    const phrase = label();

    await runInAct(async () => t.mock.timers.tick(STALL_MS - 1_000));
    assert.equal(pose(), awake);
    await runInAct(async () => t.mock.timers.tick(1_000));
    assert.equal(pose(), "sleep");
    assert.equal(label(), phrase);

    await view.rerender(node({ ...GENERATING, streamed_chars: 7_400 }));
    assert.equal(pose(), awake);
    await view.unmount();
  } finally {
    restore();
  }
});

test("WaitingIndicator starts a request awake after a long gap between requests", async (t) => {
  t.mock.timers.enable({ apis: ["Date", "setInterval"], now: NOW });
  const restore = installDom();
  try {
    // Between requests (a long tool run) the activity is null while the line stays up.
    const view = await renderReact(node(null));
    await runInAct(async () => t.mock.timers.tick(STALL_MS + 5_000));
    await view.rerender(node({ ...GENERATING, request_id: "r2", phase: "processing_prompt", streamed_chars: 0 }));
    await runInAct(async () => t.mock.timers.tick(1_000));
    assert.notEqual(view.container.querySelector("svg")?.getAttribute("data-pose"), "sleep");
    await view.unmount();
  } finally {
    restore();
  }
});
