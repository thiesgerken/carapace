"use client";

import { ChevronRight, Loader2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { UsageDetails, UsageSummary, isUsageData, type UsagePayload } from "@/components/command-result";
import { fetchSessionUsage } from "@/lib/api";

export type SessionUsageState = { data: UsagePayload | undefined; error: string | null };

const LOADING: SessionUsageState = { data: undefined, error: null };

type Outcome = { sessionId: string; data: UsagePayload } | { sessionId: string; error: string };

/**
 * The session's `/usage` breakdown over REST, so it loads while a turn runs. Fetched only while
 * `enabled`, and again whenever `refreshKey` changes (the live turn usage from the WebSocket).
 */
export function useSessionUsage(
  server: string,
  token: string,
  sessionId: string,
  enabled: boolean,
  refreshKey: unknown,
): SessionUsageState {
  const [outcome, setOutcome] = useState<Outcome | null>(null);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    fetchSessionUsage(server, token, sessionId)
      .then((data) => {
        if (cancelled) return;
        if (!isUsageData(data)) throw new Error("Unexpected usage payload");
        setOutcome({ sessionId, data });
      })
      .catch((loadError: unknown) => {
        if (!cancelled) setOutcome({ sessionId, error: loadError instanceof Error ? loadError.message : String(loadError) });
      });
    return () => {
      cancelled = true;
    };
  }, [server, token, sessionId, enabled, refreshKey]);

  // Keyed by session: an outcome for another session reads as loading.
  if (outcome === null || outcome.sessionId !== sessionId) return LOADING;
  return "error" in outcome ? { data: undefined, error: outcome.error } : { data: outcome.data, error: null };
}

/**
 * The usage breakdown in the chat inspector, collapsed by default. Rendered twice (desktop column
 * and mobile sheet), so the open state and the fetched data live in the caller. The budget gauges
 * are left to the budget section next to it.
 */
export function ChatUsageSection({ state, open, onOpenChange }: {
  state: SessionUsageState;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations("chatView.usage");
  const { data, error } = state;

  return (
    <details
      data-usage-section
      open={open}
      onToggle={(event) => onOpenChange(event.currentTarget.open)}
      className="group/card rounded-2xl border border-border/70 bg-background/90 p-3 shadow-sm"
    >
      <summary className="flex cursor-pointer list-none items-start justify-between gap-2 [&::-webkit-details-marker]:hidden">
        <div className="min-w-0 space-y-1">
          <div className="text-[11px] font-medium uppercase tracking-[0.12em] text-muted-foreground">{t("title")}</div>
          {open ? (
            error ? (
              <div className="text-xs text-destructive">{error}</div>
            ) : data === undefined ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />
            ) : (
              <div className="text-xs text-muted-foreground">
                <UsageSummary data={data} />
              </div>
            )
          ) : null}
        </div>
        <ChevronRight
          aria-hidden="true"
          className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform group-open/card:rotate-90"
        />
      </summary>

      {data ? (
        <div className="mt-3 border-t border-border/60 pt-1">
          <UsageDetails data={data} showBudget={false} />
        </div>
      ) : null}
    </details>
  );
}
