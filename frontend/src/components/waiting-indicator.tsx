"use client";

import { Loader2 } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";

import { useNow } from "@/hooks/use-now";
import type { LlmActivity } from "@/lib/types";

// A rough average for English text and code; the request record brings the real count.
const CHARS_PER_TOKEN = 4;

const PHASE_KEYS = {
  processing_prompt: "processingPrompt",
  thinking: "thinking",
  generating: "generating",
} as const;

/** What the agent's request is doing, how long it has run and roughly how many tokens it has written. */
export function WaitingIndicator({ activity }: { activity: LlmActivity | null }) {
  const t = useTranslations("chatView.waiting");
  const format = useFormatter();
  const agent = activity?.source === "agent" ? activity : null;
  const now = useNow(agent !== null);

  let label = t("working");
  let counter: string | null = null;
  if (agent) {
    label = agent.phase === "tool_call" ? t("toolCall", { tool: agent.tool_name ?? "" }) : t(PHASE_KEYS[agent.phase]);
    // ponytail: server clock vs. browser clock; skew shifts the counter, clamped at zero.
    const seconds = Math.max(0, Math.floor((now - Date.parse(agent.started_at)) / 1000));
    const parts = [seconds < 60 ? t("seconds", { seconds }) : t("minutes", { minutes: Math.floor(seconds / 60), seconds: seconds % 60 })];
    const tokens = Math.round((agent.streamed_chars ?? 0) / CHARS_PER_TOKEN);
    if (tokens > 0) {
      const count = tokens < 1000 ? format.number(tokens) : `${format.number(tokens / 1000, { maximumFractionDigits: 1 })}k`;
      parts.push(t("tokens", { count }));
    }
    counter = parts.join(" · ");
  }

  return (
    <div className="flex items-center gap-2 text-sm text-muted-foreground">
      <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin" />
      <span>{label}</span>
      {counter && <span className="tabular-nums">{counter}</span>}
    </div>
  );
}
