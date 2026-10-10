"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { getMemoryStatus } from "@/lib/api";
import { budgetGauge, formatTokens, formatUsd, hasActiveTasks } from "@/lib/memory";
import type { MemoryBudgetWindowStatus, MemoryStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

const POLL_INTERVAL_MS = 4000;

interface MemoryStatusContextValue {
  status: MemoryStatus | null;
  error: string | null;
  refreshStatus: () => Promise<void>;
}

const MemoryStatusContext = createContext<MemoryStatusContextValue | null>(null);

export function useMemoryStatus(): MemoryStatusContextValue {
  const value = useContext(MemoryStatusContext);
  if (value === null) {
    throw new Error("useMemoryStatus must be used within MemoryStatusProvider");
  }
  return value;
}

/**
 * Owns the one status poll of the Memory area. Tabs re-read their own data whenever `status`
 * changes, so a single timer keeps strip and lists in step while tasks are queued or running.
 */
export function MemoryStatusProvider({ server, children }: { server: string; children: ReactNode }) {
  const [status, setStatus] = useState<MemoryStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refreshStatus = useCallback(async () => {
    try {
      setStatus(await getMemoryStatus(server));
      setError(null);
    } catch (statusError) {
      setError(statusError instanceof Error ? statusError.message : String(statusError));
    }
  }, [server]);

  useEffect(() => {
    const timer = setTimeout(() => void refreshStatus(), 0);
    return () => clearTimeout(timer);
  }, [refreshStatus]);

  const active = status !== null && hasActiveTasks(status);
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => {
      if (document.visibilityState === "visible") void refreshStatus();
    }, POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [active, refreshStatus]);

  const value = useMemo(() => ({ status, error, refreshStatus }), [status, error, refreshStatus]);
  return <MemoryStatusContext.Provider value={value}>{children}</MemoryStatusContext.Provider>;
}

function BudgetMeter({ label, window }: { label: string; window: MemoryBudgetWindowStatus }) {
  const locale = useLocale();
  const t = useTranslations("memory.status");
  const gauge = budgetGauge(window);
  const format = (value: number) => (gauge.unit === "usd" ? formatUsd(value, locale) : formatTokens(value, locale));
  const ratio = gauge.limit ? Math.min(gauge.spent / gauge.limit, 1) : null;

  return (
    <div className="flex min-w-0 items-center gap-2">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-medium tabular-nums text-foreground">
        {format(gauge.spent)}
        {gauge.limit === null ? null : ` / ${format(gauge.limit)}`}
        {gauge.unit === "tokens" ? ` ${t("tokens")}` : null}
      </span>
      {ratio === null ? (
        <span className="text-muted-foreground">{t("noLimit")}</span>
      ) : (
        <span
          role="meter"
          aria-label={label}
          aria-valuemin={0}
          aria-valuemax={gauge.limit ?? 0}
          aria-valuenow={gauge.spent}
          className="h-1.5 w-20 overflow-hidden rounded-full bg-muted"
        >
          <span
            className={cn("block h-full rounded-full", ratio >= 1 ? "bg-destructive" : "bg-[#236b86]")}
            style={{ width: `${ratio * 100}%` }}
          />
        </span>
      )}
    </div>
  );
}

export function MemoryStatusStrip() {
  const t = useTranslations("memory.status");
  const tStatuses = useTranslations("memory.taskStatuses");
  const locale = useLocale();
  const { status, error } = useMemoryStatus();

  if (status === null) {
    return (
      <div className={cn("mb-4 rounded-lg border border-border/80 bg-background/80 px-4 py-3 text-xs", error ? "text-destructive" : "text-muted-foreground")}>
        {error ?? t("loading")}
      </div>
    );
  }

  const monthLabel = new Intl.DateTimeFormat(locale, { month: "short", timeZone: status.timezone }).format(Date.parse(status.month.window_start));
  const queue = (["pending", "queued", "running", "failed"] as const).map((key) => `${status.queue[key].toLocaleString(locale)} ${tStatuses(key)}`);

  return (
    <div className="mb-4 space-y-2 rounded-lg border border-border/80 bg-background/80 px-4 py-3 text-xs">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
        <Link
          href="/settings/account#memory"
          title={t("autoModeHint")}
          className={cn(
            "rounded-full px-2.5 py-0.5 font-medium transition-colors hover:ring-2 hover:ring-ring/30",
            status.auto_mode ? "bg-[#236b86] text-white" : "bg-muted text-muted-foreground",
          )}
        >
          {t(status.auto_mode ? "autoModeOn" : "autoModeOff")}
        </Link>
        <BudgetMeter label={t("today")} window={status.day} />
        <BudgetMeter label={monthLabel} window={status.month} />
      </div>
      <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-1 text-muted-foreground">
        <span>
          {t("queue")}: {queue.join(" · ")}
          {status.blocked > 0 ? ` · ${t("blocked", { count: status.blocked })}` : null}
          {error ? <span className="ml-2 text-destructive">{error}</span> : null}
        </span>
        <span className="font-mono">
          memory_low: {status.models.memory_low} · memory_high: {status.models.memory_high}
        </span>
      </div>
    </div>
  );
}
