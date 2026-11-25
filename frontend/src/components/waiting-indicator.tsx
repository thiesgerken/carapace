"use client";

import { useFormatter, useTranslations } from "next-intl";
import { useState } from "react";

import { Tortoise, type TortoisePose } from "@/components/tortoise";
import { useNow } from "@/hooks/use-now";
import { compactCount } from "@/lib/request-table";
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

// Each phrase names the pose that acts it out. To add one: an entry here and its text under
// `chatView.waiting.phrases` in both message files.
export const PHRASES: Record<"processing_prompt" | "thinking" | "sentinel", readonly Phrase[]> = {
  processing_prompt: [
    { key: "nibble", pose: "munch" },
    { key: "digest", pose: "munch" },
    { key: "chewTwice", pose: "munch" },
    { key: "eatThrough", pose: "munch" },
    { key: "finePrint", pose: "glass" },
    { key: "betweenLines", pose: "glass" },
    { key: "history", pose: "book" },
    { key: "plentyOfTime", pose: "hourglass" },
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
  sentinel: [
    { key: "knocking", pose: "peek" },
    { key: "peeksOut", pose: "peek" },
  ],
};

// While the answer streams, the text itself shows the work, so the tortoise acts without a phrase.
// A tool call being written counts too: its live card replaces this line once it arrives.
export const GENERATING_POSES: readonly TortoisePose[] = ["walk", "scribble", "wrench"];

/** What the tortoise does for *activity*, and the phrase that goes with it, if any. One pick per turn and bucket. */
function act(activity: LlmActivity | null, turnSeed: number): { pose: TortoisePose; phrase?: string } {
  if (!activity) return { pose: "pulse" };
  const bucket = activity.source === "sentinel" ? "sentinel" : activity.phase;
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

/** How long the agent's request has run and roughly how many tokens it has written. */
export function ActivityCounter({ activity }: { activity: LlmActivity }) {
  const t = useTranslations("chatView.waiting");
  const format = useFormatter();
  const now = useNow(true);
  // ponytail: server clock vs. browser clock; skew shifts the counter, clamped at zero.
  const seconds = Math.max(0, Math.floor((now - Date.parse(activity.started_at)) / 1000));
  const parts = [seconds < 60 ? t("seconds", { seconds }) : t("minutes", { minutes: Math.floor(seconds / 60), seconds: seconds % 60 })];
  const tokens = Math.round((activity.streamed_chars ?? 0) / CHARS_PER_TOKEN);
  if (tokens > 0) {
    parts.push(t("tokens", { count: compactCount(tokens, (n, maximumFractionDigits) => format.number(n, { maximumFractionDigits })) }));
  }
  return <span className="tabular-nums">{parts.join(" · ")}</span>;
}

/**
 * What the agent's request is doing, acted out by the tortoise, with how long it has run and roughly
 * how many tokens it has written. Mount it once per turn and *hide* it rather than unmounting it, so
 * the phrases, the stall clock and the shimmer hold for the whole turn instead of re-rolling.
 */
export function WaitingIndicator({ activity, hidden = false }: { activity: LlmActivity | null; hidden?: boolean }) {
  const t = useTranslations("chatView.waiting");
  const agent = activity?.source === "agent" ? activity : null;
  // Ticks for as long as the line is up, including the gaps between requests, so a new request's
  // progress is stamped with the current time rather than when the last one ended.
  const now = useNow(true);
  const lastProgressAt = useLastProgressAt(agent, now);
  const [turnSeed] = useState(() => Math.floor(Math.random() * 2 ** 32));
  const [shimmerDelay] = useState(() => `-${Date.now() % SHIMMER_MS}ms`);

  const { pose, phrase } = act(activity, turnSeed);
  const stalled = agent !== null && now - lastProgressAt >= STALL_MS;

  return (
    <div hidden={hidden} className="flex items-center gap-2 px-2 text-xs text-muted-foreground">
      <Tortoise pose={stalled ? "sleep" : pose} className="h-6 w-auto shrink-0" />
      {phrase && (
        <span className="text-shimmer" style={{ animationDelay: shimmerDelay }}>
          {t(`phrases.${phrase}`)}
        </span>
      )}
      {agent && <ActivityCounter activity={agent} />}
    </div>
  );
}
