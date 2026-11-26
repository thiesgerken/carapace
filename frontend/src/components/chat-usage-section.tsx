"use client";

import { Ellipsis, Loader2, Shrink } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { UsageDetails, UsageSummary, isUsageData, type UsagePayload } from "@/components/command-result";
import { CompactionDialog } from "@/components/compaction-dialog";
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

/** The session to compact and how: the chat sends `/compact [focus]` and `/uncompact` like typed commands. */
export interface CompactionControls {
  server: string;
  token: string;
  sessionId: string;
  disabled: boolean;
  onCompact: (focus: string) => void;
  onUncompact: () => void;
}

/**
 * The usage breakdown in the chat inspector's Usage tab, with the compaction controls in its header.
 * Rendered twice (desktop column and mobile sheet), so the fetched data lives in the caller. The
 * budget gauges are left to the budget section next to it.
 */
export function ChatUsageSection({ state, compaction }: { state: SessionUsageState; compaction: CompactionControls }) {
  const t = useTranslations("chatView.usage");
  const tCompaction = useTranslations("chatView.compaction");
  const { data, error } = state;
  const [dialogOpen, setDialogOpen] = useState(false);

  return (
    <section className="py-4">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 space-y-1">
          <div className="text-xs font-medium text-muted-foreground">{t("title")}</div>
          {error ? (
            <div className="text-xs text-destructive">{error}</div>
          ) : data === undefined ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />
          ) : (
            <div className="text-xs text-muted-foreground">
              <UsageSummary data={data} />
            </div>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <button
            type="button"
            disabled={compaction.disabled}
            onClick={() => compaction.onCompact("")}
            className="inline-flex h-7 items-center gap-1 rounded-md px-2 text-xs font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Shrink className="h-3.5 w-3.5" />
            {tCompaction("compact")}
          </button>
          <button
            type="button"
            disabled={compaction.disabled}
            onClick={() => setDialogOpen(true)}
            title={tCompaction("more")}
            aria-label={tCompaction("more")}
            className="inline-flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Ellipsis className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      {data ? (
        <div className="mt-2">
          <UsageDetails data={data} showBudget={false} />
        </div>
      ) : null}
      {dialogOpen ? (
        <CompactionDialog
          server={compaction.server}
          token={compaction.token}
          sessionId={compaction.sessionId}
          onClose={() => setDialogOpen(false)}
          onCompact={compaction.onCompact}
          onUncompact={compaction.onUncompact}
        />
      ) : null}
    </section>
  );
}
