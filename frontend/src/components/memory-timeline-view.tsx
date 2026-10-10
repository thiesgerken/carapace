"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Loader2 } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { MemoryPeriodDetailView, PeriodBadgeMark, periodHref } from "@/components/memory-period-detail";
import { useMemoryStatus } from "@/components/memory-status";
import { getMemoryPeriods } from "@/lib/api";
import { groupMonthsByYear, monthLabel, periodBadge } from "@/lib/memory";
import type { MemoryPeriodNode, MemoryPeriodTree } from "@/lib/types";
import { cn } from "@/lib/utils";

function NodeLink({ node, label, selected }: { node: MemoryPeriodNode; label: string; selected: boolean }) {
  return (
    <Link
      href={periodHref(node.key)}
      aria-current={selected ? "page" : undefined}
      className={cn(
        "flex flex-1 items-center gap-2 rounded-md px-2 py-1 text-sm transition-colors hover:bg-muted",
        selected && "bg-accent text-accent-foreground",
      )}
    >
      <span className="flex-1 truncate">{label}</span>
      <span className="tabular-nums text-xs text-muted-foreground">{node.digest || node.covered > 0 ? `${node.covered}/${node.total}` : null}</span>
      <PeriodBadgeMark badge={periodBadge(node)} />
    </Link>
  );
}

export function MemoryTimelineView({ server, token }: { server: string; token: string }) {
  const t = useTranslations("memory.timeline");
  const locale = useLocale();
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
    <div className="grid min-h-0 flex-1 lg:grid-cols-[18rem_minmax(0,1fr)]">
      <nav aria-label={t("tree")} className="min-h-0 overflow-y-auto border-b border-border p-3 lg:border-b-0 lg:border-r">
        {error ? (
          <p className="text-sm text-destructive">{error}</p>
        ) : tree === null ? (
          <Loader2 className="m-2 h-4 w-4 animate-spin text-muted-foreground" />
        ) : tree.months.length === 0 ? (
          <p className="p-2 text-sm text-muted-foreground">{t("empty")}</p>
        ) : groupMonthsByYear(tree.months).map(([year, months], yearIndex) => (
          <details key={year} open={yearIndex === 0 || months.some((month) => month.key === selectedKey || month.weeks.some((week) => week.key === selectedKey))}>
            <summary className="cursor-pointer px-2 py-1 text-sm font-semibold">{year}</summary>
            <ul className="ml-2 space-y-0.5">
              {months.map((month) => (
                <li key={month.key}>
                  <details open={month.key === selectedKey || month.weeks.some((week) => week.key === selectedKey)}>
                    <summary className="flex cursor-pointer items-center">
                      <NodeLink node={month} label={monthLabel(month.key, locale, false)} selected={month.key === selectedKey} />
                    </summary>
                    <ul className="ml-4 space-y-0.5">
                      {month.weeks.map((week) => (
                        <li key={week.key}>
                          <NodeLink node={week} label={week.key.slice(5)} selected={week.key === selectedKey} />
                        </li>
                      ))}
                    </ul>
                  </details>
                </li>
              ))}
            </ul>
          </details>
        ))}
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
