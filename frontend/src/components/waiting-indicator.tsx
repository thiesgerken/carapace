"use client";

import { useFormatter, useTranslations } from "next-intl";
import { useState } from "react";

import { useNow } from "@/hooks/use-now";
import { compactCount } from "@/lib/request-table";
import type { LlmActivity } from "@/lib/types";

// A rough average for English text and code; the request record brings the real count.
const CHARS_PER_TOKEN = 4;

// The `.text-shimmer` sweep in globals.css.
const SHIMMER_MS = 2000;

// A tool call being written shows on its live card (see `streamingCallIndex`); this line covers the
// moment before that card arrives.
const PHASE_KEYS = {
  processing_prompt: "processingPrompt",
  thinking: "thinking",
  generating: "generating",
  tool_call: "generating",
} as const;

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

/** What the agent's request is doing, how long it has run and roughly how many tokens it has written. */
export function WaitingIndicator({ activity }: { activity: LlmActivity | null }) {
  const t = useTranslations("chatView.waiting");
  const agent = activity?.source === "agent" ? activity : null;
  const [shimmerDelay] = useState(() => `-${Date.now() % SHIMMER_MS}ms`);

  return (
    <div className="flex items-center gap-2 px-2 text-xs text-muted-foreground">
      <span className="text-shimmer" style={{ animationDelay: shimmerDelay }}>{agent ? t(PHASE_KEYS[agent.phase]) : t("working")}</span>
      {agent && <ActivityCounter activity={agent} />}
    </div>
  );
}
