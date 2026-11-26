import assert from "node:assert/strict";
import test, { type TestContext } from "node:test";
import { NextIntlClientProvider } from "next-intl";

import de from "../../messages/de.json";
import en from "../../messages/en.json";
import { installDom, renderReact, runInAct } from "../../test/react-test-utils";
import type { ExecStep, RunningStep } from "@/lib/tool-call-status";
import type { LlmActivity } from "@/lib/types";

import { GENERATING_POSES, PHRASES, STALL_MS, WaitingIndicator, act } from "./waiting-indicator";

// The clock is frozen at NOW, so the elapsed time does not depend on how long the test runs.
const NOW = Date.parse("2026-01-01T12:00:00Z");
const ago = (ms: number) => new Date(NOW - ms).toISOString();

const MESSAGES = { en, de };
type Locale = keyof typeof MESSAGES;
const GENERATING: LlmActivity = { request_id: "r1", source: "agent", phase: "generating", started_at: ago(78_500), streamed_chars: 7_300 };
const THINKING: LlmActivity = { ...GENERATING, phase: "thinking" };

const BUILD: RunningStep = { spanId: "b", kind: "skill", name: "build wait", startedAt: NOW - 95_000 };

const node = (
  activity: LlmActivity | null,
  { locale = "en", hidden, step, awaitsUser }: { locale?: Locale; hidden?: boolean; step?: RunningStep | ExecStep; awaitsUser?: boolean } = {},
) => (
  <NextIntlClientProvider locale={locale} messages={MESSAGES[locale]} timeZone="UTC">
    <WaitingIndicator activity={activity} step={step} awaitsUser={awaitsUser} hidden={hidden} />
  </NextIntlClientProvider>
);

async function shown(
  activity: LlmActivity | null,
  locale: Locale = "en",
  step?: RunningStep | ExecStep,
  awaitsUser?: boolean,
): Promise<{ text: string; pose: string | null }> {
  const view = await renderReact(node(activity, { locale, step, awaitsUser }));
  const result = { text: view.container.textContent ?? "", pose: view.container.querySelector("svg")?.getAttribute("data-pose") ?? null };
  await view.unmount();
  return result;
}

/** The phrase of *bucket* that *text* opens with; which one is up to the turn's seed, so tests don't pin it. */
function phraseIn(text: string, bucket: keyof typeof PHRASES) {
  const texts: Record<string, string> = en.chatView.waiting.phrases;
  const phrase = PHRASES[bucket].find(({ key }) => text.startsWith(texts[key]));
  assert.ok(phrase, `"${text}" opens with none of the ${bucket} phrases`);
  return phrase;
}

function setUp(t: TestContext, apis: ("Date" | "setInterval")[] = ["Date"]): () => void {
  t.mock.timers.enable({ apis, now: NOW });
  t.mock.method(Math, "random", () => 0.42);
  return installDom();
}

test("every phrase has its text in both languages, and every text a phrase", () => {
  const keys = [...new Set(Object.values(PHRASES).flatMap((phrases) => phrases.map(({ key }) => key)))].sort();
  assert.deepEqual(Object.keys(en.chatView.waiting.phrases).sort(), keys);
  assert.deepEqual(Object.keys(de.chatView.waiting.phrases).sort(), keys);
});

test("WaitingIndicator acts out the phase and counts time and approximate tokens", async (t) => {
  const restore = setUp(t);
  try {
    // Before the first token only the clock runs.
    const prompt = await shown({ ...GENERATING, phase: "processing_prompt", started_at: ago(3_200), streamed_chars: 0 });
    assert.ok(prompt.text.endsWith("3 s"), prompt.text);
    assert.equal(prompt.pose, phraseIn(prompt.text, "processing_prompt").pose);

    const thinking = await shown(THINKING);
    assert.ok(thinking.text.endsWith("1 min 18 s · 1.8k tokens"), thinking.text);
    assert.equal(thinking.pose, phraseIn(thinking.text, "thinking").pose);
    assert.ok((await shown(THINKING, "de")).text.endsWith("1 min 18 s · 1,8k Tokens"));

    // While the answer streams, the tortoise works without a phrase; a tool call being written is the same.
    const generating = await shown(GENERATING);
    assert.equal(generating.text, "1 min 18 s · 1.8k tokens");
    assert.ok(GENERATING_POSES.includes(generating.pose as (typeof GENERATING_POSES)[number]), String(generating.pose));
    assert.deepEqual(await shown({ ...GENERATING, phase: "tool_call", tool_name: "exec" }), generating);

    // The sentinel's requests get their own phrases and no counter.
    const sentinel = await shown({ ...GENERATING, source: "sentinel" });
    assert.equal(sentinel.pose, phraseIn(sentinel.text, "sentinel").pose);
    assert.ok(!sentinel.text.includes("tokens"), sentinel.text);

    // Between requests only the tortoise shows that the turn is still going.
    assert.deepEqual(await shown(null), { text: "", pose: "pulse" });
  } finally {
    restore();
  }
});

test("WaitingIndicator keeps its phrases for the whole turn, across requests and while hidden", async (t) => {
  const restore = setUp(t);
  try {
    const view = await renderReact(node(THINKING));
    const label = () => view.container.querySelector(".text-shimmer")?.textContent;
    const first = label();

    t.mock.method(Math, "random", () => 0.99);
    await view.rerender(node(null, { hidden: true }));
    assert.equal(view.container.firstElementChild?.hasAttribute("hidden"), true);
    await view.rerender(node({ ...THINKING, request_id: "r2" }));
    assert.equal(label(), first);
    await view.unmount();
  } finally {
    restore();
  }
});

test("WaitingIndicator dozes off without progress and wakes on the next token", async (t) => {
  const restore = setUp(t, ["Date", "setInterval"]);
  try {
    const view = await renderReact(node(THINKING));
    const pose = () => view.container.querySelector("svg")?.getAttribute("data-pose");
    const label = () => view.container.querySelector(".text-shimmer")?.textContent;
    const awake = pose();
    const phrase = label();

    await runInAct(async () => t.mock.timers.tick(STALL_MS - 1_000));
    assert.equal(pose(), awake);
    await runInAct(async () => t.mock.timers.tick(1_000));
    assert.equal(pose(), "sleep");
    assert.equal(label(), phrase);

    await view.rerender(node({ ...THINKING, streamed_chars: 7_400 }));
    assert.equal(pose(), awake);
    await view.unmount();
  } finally {
    restore();
  }
});

test("WaitingIndicator starts a request awake after a long gap between requests", async (t) => {
  const restore = setUp(t, ["Date", "setInterval"]);
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

test("between requests WaitingIndicator acts out the step a tool call waits on and how long it has run", async (t) => {
  const restore = setUp(t);
  try {
    const build = await shown(null, "en", BUILD);
    assert.ok(build.text.endsWith("1 min 35 s"), build.text);
    assert.equal(build.pose, phraseIn(build.text, "skillBuild").pose);

    // A span the chat has no words for by name gets its kind's phrases.
    const lookup = await shown(null, "en", { ...BUILD, name: "ensure_built" });
    assert.equal(lookup.pose, phraseIn(lookup.text, "skill").pose);
    const lock = await shown(null, "de", { ...BUILD, kind: "wait", name: "exec lock" });
    assert.ok(lock.text.endsWith("1 min 35 s"), lock.text);
    assert.equal(lock.pose, "hourglass");

    // A domain check and the sentinel request reviewing it are one bucket, and the step's counter stays.
    const domain: RunningStep = { ...BUILD, kind: "domain", name: "pypi.org" };
    const check = await shown(null, "en", domain);
    const review = await shown({ ...GENERATING, source: "sentinel" }, "en", domain);
    assert.equal(review.text, check.text);
    assert.ok(check.text.endsWith("1 min 35 s"), check.text);

    // A running request is what the line is about, even while a step runs.
    const thinking = await shown(THINKING, "en", BUILD);
    assert.equal(thinking.pose, phraseIn(thinking.text, "thinking").pose);
    assert.ok(thinking.text.endsWith("1 min 18 s · 1.8k tokens"), thinking.text);
  } finally {
    restore();
  }
});

test("WaitingIndicator stays awake through a long step", async (t) => {
  const restore = setUp(t, ["Date", "setInterval"]);
  try {
    const view = await renderReact(node(null, { step: BUILD }));
    await runInAct(async () => t.mock.timers.tick(STALL_MS * 3));
    assert.notEqual(view.container.querySelector("svg")?.getAttribute("data-pose"), "sleep");
    await view.unmount();
  } finally {
    restore();
  }
});

test("a wait for the user always says so plainly, whatever runs meanwhile and whatever the turn rolled", () => {
  for (let seed = 0; seed < 64; seed++) {
    assert.deepEqual(act(true, GENERATING, BUILD, seed), { pose: "hourglass", phrase: "awaitsYourGo" });
  }
});

test("WaitingIndicator names a wait for the user without a counter, and a long command with one", async (t) => {
  const restore = setUp(t);
  try {
    const approval = await shown(GENERATING, "en", BUILD, true);
    assert.deepEqual(approval, { text: "Waits for your go…", pose: "hourglass" });

    const exec: ExecStep = { spanId: "e", kind: "exec", name: "exec", startedAt: NOW - 42_000 };
    const command = await shown(null, "de", exec);
    assert.equal(command.text, "Führt den Befehl aus…42 s");
  } finally {
    restore();
  }
});
