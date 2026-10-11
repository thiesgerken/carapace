"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ChevronLeft, ChevronRight, Loader2 } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { MemoryPeriodDetailView, PeriodBadgeMark, periodHref } from "@/components/memory-period-detail";
import { useMemoryStatus } from "@/components/memory-status";
import { TaskStatusIcon, controlClassName } from "@/components/memory-ui";
import { MonthCalendar } from "@/components/month-calendar";
import { getMemoryPeriods } from "@/lib/api";
import { monthLabel, periodBadge, periodMonth } from "@/lib/memory";
import type { MemoryMonthNode, MemoryPeriodNode, MemoryPeriodTree } from "@/lib/types";
import { cn } from "@/lib/utils";

/** The digest's badge, its coverage, and the task while it still needs attention. */
function PeriodState({ node }: { node: MemoryPeriodNode }) {
  const status = node.task?.status;
  return (
    <span className="inline-flex items-center gap-1 text-[11px] tabular-nums text-muted-foreground">
      {node.digest || node.covered > 0 ? `${node.covered}/${node.total}` : null}
      <PeriodBadgeMark badge={periodBadge(node)} />
      {status && status !== "done" && status !== "cancelled" ? <TaskStatusIcon status={status} /> : null}
    </span>
  );
}

function MonthStep({ month, label, icon: Icon }: { month: MemoryMonthNode | undefined; label: string; icon: typeof ChevronLeft }) {
  const className = "inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-muted-foreground";
  if (month === undefined) {
    return <span aria-hidden="true" className={cn(className, "opacity-30")}><Icon className="h-4 w-4" /></span>;
  }
  return (
    <Link href={periodHref(month.key)} title={label} aria-label={label} className={cn(className, "hover:bg-muted hover:text-foreground")}>
      <Icon className="h-4 w-4" />
    </Link>
  );
}

/** The selected period's month; the arrows and the select only go to months with data. */
function PeriodCalendar({ months, selectedKey }: { months: MemoryMonthNode[]; selectedKey: string }) {
  const t = useTranslations("memory.timeline");
  const locale = useLocale();
  const router = useRouter();
  const monthKey = periodMonth(selectedKey);
  const month = months.find((node) => node.key === monthKey);
  const weeks = new Map(month?.weeks.map((week) => [week.key, week]));
  // Months arrive newest first.
  const older = months.find((node) => node.key < monthKey);
  const newer = months.filter((node) => node.key > monthKey).at(-1);

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-1">
        <MonthStep month={older} label={t("previousMonth")} icon={ChevronLeft} />
        <select
          aria-label={t("jumpToMonth")}
          value={monthKey}
          onChange={(event) => router.push(periodHref(event.target.value))}
          className={cn(controlClassName, "min-w-0 flex-1 text-center font-semibold")}
        >
          {month === undefined ? <option value={monthKey} disabled>{monthLabel(monthKey, locale, true)}</option> : null}
          {months.map((node) => <option key={node.key} value={node.key}>{monthLabel(node.key, locale, true)}</option>)}
        </select>
        <MonthStep month={newer} label={t("nextMonth")} icon={ChevronRight} />
      </div>
      {month ? (
        <Link
          href={periodHref(month.key)}
          aria-current={month.key === selectedKey ? "page" : undefined}
          className={cn("flex items-center justify-between rounded-md px-2 py-1.5 text-sm hover:bg-muted", month.key === selectedKey && "bg-accent text-accent-foreground")}
        >
          {t("monthDigest")}
          <PeriodState node={month} />
        </Link>
      ) : null}
      <MonthCalendar
        monthKey={monthKey}
        renderRow={(weekKey, cells, className) => {
          if (!weeks.has(weekKey)) return <div className={className}>{cells}</div>;
          return (
            <Link
              href={periodHref(weekKey)}
              aria-current={weekKey === selectedKey ? "page" : undefined}
              className={cn(className, "rounded-md hover:bg-muted", weekKey === selectedKey && "bg-accent text-accent-foreground")}
            >
              {cells}
            </Link>
          );
        }}
        weekCell={(weekKey) => {
          const week = weeks.get(weekKey);
          return (
            <>
              <span className={cn("text-xs font-medium", week === undefined && "text-muted-foreground/50")}>{weekKey.slice(5)}</span>
              {week ? <PeriodState node={week} /> : null}
            </>
          );
        }}
        dayCell={(weekKey, dayIndex) => {
          const count = weeks.get(weekKey)?.days[dayIndex] ?? 0;
          if (count === 0) return null;
          return (
            <span title={t("sessionsOnDay", { count })} className="rounded-full bg-[#236b86]/15 px-1.5 text-[11px] font-medium tabular-nums text-[#236b86] dark:bg-sky-400/15 dark:text-sky-300">
              {count}
            </span>
          );
        }}
      />
    </div>
  );
}

export function MemoryTimelineView({ server, token }: { server: string; token: string }) {
  const t = useTranslations("memory.timeline");
  const { status } = useMemoryStatus();
  const requestedKey = useSearchParams().get("period");
  const [tree, setTree] = useState<MemoryPeriodTree | null>(null);
  const [error, setError] = useState<string | null>(null);

  // `status` changes on every poll and after every action; see MemoryStatusProvider.
  useEffect(() => {
    let cancelled = false;
    getMemoryPeriods(server)
      .then((result) => {
        if (cancelled) return;
        setTree(result);
        setError(null);
      })
      .catch((loadError: unknown) => {
        if (!cancelled) setError(loadError instanceof Error ? loadError.message : String(loadError));
      });
    return () => {
      cancelled = true;
    };
  }, [server, status]);

  const selectedKey = requestedKey ?? tree?.months[0]?.key ?? null;

  return (
    <div className="grid min-h-0 flex-1 grid-rows-[auto_minmax(0,1fr)] lg:grid-cols-[22rem_minmax(0,1fr)] lg:grid-rows-[minmax(0,1fr)]">
      <nav aria-label={t("calendar")} className="min-h-0 overflow-y-auto border-b border-border p-3 lg:border-b-0 lg:border-r">
        {error ? (
          <p className="text-sm text-destructive">{error}</p>
        ) : tree === null ? (
          <Loader2 className="m-2 h-4 w-4 animate-spin text-muted-foreground" />
        ) : tree.months.length === 0 || selectedKey === null ? (
          <p className="p-2 text-sm text-muted-foreground">{t("empty")}</p>
        ) : (
          <PeriodCalendar months={tree.months} selectedKey={selectedKey} />
        )}
      </nav>

      <div className="min-h-0 overflow-y-auto">
        {selectedKey ? (
          <MemoryPeriodDetailView key={selectedKey} server={server} token={token} periodKey={selectedKey} />
        ) : tree !== null ? (
          <p className="p-5 text-sm text-muted-foreground">{t("pickPeriod")}</p>
        ) : null}
      </div>
    </div>
  );
}
