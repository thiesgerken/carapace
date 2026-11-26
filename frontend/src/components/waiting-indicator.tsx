"use client";

import { useFormatter, useTranslations } from "next-intl";
import { useState } from "react";

import { Tortoise, type TortoisePose } from "@/components/tortoise";
import { useNow } from "@/hooks/use-now";
import { compactCount } from "@/lib/request-table";
import { stepTopic, type RunningStep, type StepTopic } from "@/lib/tool-call-status";
import type { LlmActivity } from "@/lib/types";

// A rough average for English text and code; the request record brings the real count.
const CHARS_PER_TOKEN = 4;

// The `.text-shimmer` sweep in globals.css.
const SHIMMER_MS = 2000;

// After this long without a new token or phase the tortoise dozes off. Label and counter stay, so
// the line still says what the request is doing.
export const STALL_MS = 60_000;

type Phrase = { key: string; pose: TortoisePose };

// Phrases that fit prompt and thinking alike.
const EITHER_PHASE: readonly Phrase[] = [
  { key: "creep", pose: "walk" },
  { key: "fullThrottle", pose: "walk" },
  { key: "wordByWord", pose: "walk" },
  { key: "writes", pose: "scribble" },
  { key: "keepsShort", pose: "pulse" },
  { key: "tinker", pose: "wrench" },
];

const KNOCKING: Phrase = { key: "knocking", pose: "peek" };
const PEEKS_OUT: Phrase = { key: "peeksOut", pose: "peek" };
const PLENTY_OF_TIME: Phrase = { key: "plentyOfTime", pose: "hourglass" };

// Each phrase names the pose that acts it out. To add one: an entry here and its text under
// `chatView.waiting.phrases` in both message files. Besides the model's phases, the buckets are the
// steps a tool call waits on between model requests; "sentinel" is both, as its requests are its steps.
export const PHRASES: Record<"processing_prompt" | "thinking" | StepTopic, readonly Phrase[]> = {
  processing_prompt: [
    { key: "nibble", pose: "munch" },
    { key: "digest", pose: "munch" },
    { key: "chewTwice", pose: "munch" },
    { key: "eatThrough", pose: "munch" },
    { key: "finePrint", pose: "glass" },
    { key: "betweenLines", pose: "glass" },
    { key: "history", pose: "book" },
    PLENTY_OF_TIME,
    ...EITHER_PHASE,
  ],
  thinking: [
    { key: "ponder", pose: "think" },
    { key: "hunch", pose: "think" },
    { key: "experience", pose: "think" },
    { key: "inShell", pose: "pulse" },
    { key: "unhurried", pose: "pulse" },
    { key: "stepByStep", pose: "walk" },
    { key: "turbo", pose: "turbo" },
    { key: "overtaken", pose: "snail" },
    ...EITHER_PHASE,
  ],
  // The sentinel's own requests: it is reviewing something that crosses the sandbox boundary.
  sentinel: [KNOCKING, PEEKS_OUT],
  domain: [KNOCKING, PEEKS_OUT],
  credential: [
    { key: "rummagesForKey", pose: "glass" },
    PEEKS_OUT,
  ],
  sandbox: [
    { key: "buildsHouse", pose: "wrench" },
    { key: "movesIn", pose: "walk" },
  ],
  skill: [{ key: "studiesSkill", pose: "glass" }],
  skillBuild: [
    { key: "tinkersTools", pose: "wrench" },
    { key: "awaitsBuild", pose: "hourglass" },
  ],
  skillProfile: [
    { key: "learnsCommands", pose: "book" },
    { key: "stowsCommands", pose: "munch" },
  ],
  wait: [{ key: "awaitsYourGo", pose: "hourglass" }, PLENTY_OF_TIME],
  execLock: [{ key: "waitsItsTurn", pose: "hourglass" }, PLENTY_OF_TIME],
};

// While the answer streams, the text itself shows the work, so the tortoise acts without a phrase.
// A tool call being written counts too: its live card replaces this line once it arrives.
export const GENERATING_POSES: readonly TortoisePose[] = ["walk", "scribble", "wrench"];

/**
 * What the tortoise does for *activity*, or for the tool call's *step* between model requests, and the
 * phrase that goes with it, if any. One pick per turn and bucket.
 */
function act(activity: LlmActivity | null, step: RunningStep | null, turnSeed: number): { pose: TortoisePose; phrase?: string } {
  const bucket = activity ? (activity.source === "sentinel" ? "sentinel" : activity.phase) : step ? stepTopic(step) : null;
  if (bucket === null) return { pose: "pulse" };
  if (bucket === "generating" || bucket === "tool_call") return { pose: pick(GENERATING_POSES, turnSeed, "generating") };
  const { key, pose } = pick(PHRASES[bucket], turnSeed, bucket);
  return { pose, phrase: key };
}

const pick = <T,>(items: readonly T[], turnSeed: number, bucket: string): T => items[fnv1a(`${turnSeed}:${bucket}`) % items.length];

function fnv1a(text: string): number {
  let hash = 0x811c9dc5;
  for (let i = 0; i < text.length; i++) hash = Math.imul(hash ^ text.charCodeAt(i), 0x01000193);
  return hash >>> 0;
}

/** When the request last showed progress: a new phase or more streamed characters. */
function useLastProgressAt(activity: LlmActivity | null, now: number): number {
  const key = activity ? `${activity.request_id}:${activity.phase}:${activity.streamed_chars ?? 0}` : "";
  const [progress, setProgress] = useState({ key, at: now });
  if (progress.key !== key) setProgress({ key, at: now });
  return progress.at;
}

function elapsedText(ms: number, t: ReturnType<typeof useTranslations<"chatView.waiting">>): string {
  const seconds = Math.max(0, Math.floor(ms / 1000));
  return seconds < 60 ? t("seconds", { seconds }) : t("minutes", { minutes: Math.floor(seconds / 60), seconds: seconds % 60 });
}

/** How long ago *since* (ms since the epoch) was, ticking. */
export function Elapsed({ since }: { since: number }) {
  const t = useTranslations("chatView.waiting");
  const now = useNow(true);
  return <span className="tabular-nums">{elapsedText(now - since, t)}</span>;
}

/** How long the agent's request has run and roughly how many tokens it has written. */
export function ActivityCounter({ activity }: { activity: LlmActivity }) {
  const t = useTranslations("chatView.waiting");
  const format = useFormatter();
  const now = useNow(true);
  // ponytail: server clock vs. browser clock; skew shifts the counter, clamped at zero.
  const parts = [elapsedText(now - Date.parse(activity.started_at), t)];
  const tokens = Math.round((activity.streamed_chars ?? 0) / CHARS_PER_TOKEN);
  if (tokens > 0) {
    parts.push(t("tokens", { count: compactCount(tokens, (n, maximumFractionDigits) => format.number(n, { maximumFractionDigits })) }));
  }
  return <span className="tabular-nums">{parts.join(" · ")}</span>;
}

/**
 * What the agent's request is doing, acted out by the tortoise, with how long it has run and roughly
 * how many tokens it has written. Between requests it acts out the *step* a tool call waits on, with how
 * long that has run. Mount it once per turn and *hide* it rather than unmounting it, so the phrases,
 * the stall clock and the shimmer hold for the whole turn instead of re-rolling.
 */
export function WaitingIndicator({
  activity,
  step = null,
  hidden = false,
}: {
  activity: LlmActivity | null;
  step?: RunningStep | null;
  hidden?: boolean;
}) {
  const t = useTranslations("chatView.waiting");
  const agent = activity?.source === "agent" ? activity : null;
  // Ticks for as long as the line is up, including the gaps between requests, so a new request's
  // progress is stamped with the current time rather than when the last one ended.
  const now = useNow(true);
  const lastProgressAt = useLastProgressAt(agent, now);
  const [turnSeed] = useState(() => Math.floor(Math.random() * 2 ** 32));
  const [shimmerDelay] = useState(() => `-${Date.now() % SHIMMER_MS}ms`);

  const { pose, phrase } = act(activity, step, turnSeed);
  // Only a request can stall: a known step may take minutes (a skill build) without being stuck.
  const stalled = agent !== null && now - lastProgressAt >= STALL_MS;

  return (
    <div hidden={hidden} className="flex items-center gap-2 px-2 text-xs text-muted-foreground">
      <Tortoise pose={stalled ? "sleep" : pose} className="h-6 w-auto shrink-0" />
      {phrase && (
        <span className="text-shimmer" style={{ animationDelay: shimmerDelay }}>
          {t(`phrases.${phrase}`)}
        </span>
      )}
      {agent ? <ActivityCounter activity={agent} /> : !activity && step && <Elapsed since={step.startedAt} />}
    </div>
  );
}
