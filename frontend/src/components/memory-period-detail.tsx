"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Loader2, RefreshCw } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { MemoryRunDialog } from "@/components/memory-run-dialog";
import { useMemoryStatus } from "@/components/memory-status";
import { buttonClassName, MemoryProvenanceList } from "@/components/memory-ui";
import { getMemoryPeriod, spawnMemoryTasks } from "@/lib/api";
import { formatAbsoluteTime } from "@/lib/format-time";
import { formatUsd, monthLabel, periodBadge, periodLevel, summarizeSkips, type PeriodBadge } from "@/lib/memory";
import type {
  MemoryDigestFact,
  MemoryDigestRecord,
  MemoryFactCategory,
  MemoryPeriodDetail,
  MemoryTaskSelection,
} from "@/lib/types";
import { cn } from "@/lib/utils";

const FACT_CATEGORIES: readonly MemoryFactCategory[] = ["user", "social", "surroundings"];

export function periodHref(key: string): string {
  return `/memory/timeline?period=${encodeURIComponent(key)}`;
}

function sessionHref(sessionId: string): string {
  return `/memory/sessions?session=${encodeURIComponent(sessionId)}`;
}

export function PeriodBadgeMark({ badge }: { badge: PeriodBadge }) {
  const t = useTranslations("memory.timeline.badges");
  const tReasons = useTranslations("memory.timeline.staleReasons");
  switch (badge.kind) {
    case "current":
      return <span title={t("current")} className="text-[#236b86]">✓</span>;
    case "stale":
      return (
        <span title={badge.reasons.map((reason) => tReasons(reason)).join(", ")} className="text-amber-700 dark:text-amber-400">
          ⚠<span className="sr-only"> {t("stale")}</span>
        </span>
      );
    case "notRun":
      return <span title={t("notRun")} className="text-muted-foreground">—</span>;
  }
}

/** Week digests cite sessions, month digests cite weeks. */
function Refs({ refs, detail }: { refs: string[]; detail: MemoryPeriodDetail }) {
  if (refs.length === 0) return null;
  const titles = new Map(detail.sessions.map((session) => [session.session_id, session.title?.trim() || session.session_id]));
  return (
    <span className="ml-1.5 text-xs text-muted-foreground">
      ({refs.map((ref, index) => (
        <span key={ref}>
          {index > 0 ? ", " : null}
          <Link
            href={detail.node.level === "week" ? sessionHref(ref) : periodHref(ref)}
            className="underline-offset-2 hover:text-foreground hover:underline"
          >
            {detail.node.level === "week" ? titles.get(ref) ?? ref : ref}
          </Link>
        </span>
      ))})
    </span>
  );
}

export function MemoryPeriodDetailView({ server, token, periodKey }: { server: string; token: string; periodKey: string }) {
  const t = useTranslations("memory.timeline");
  const locale = useLocale();
  const { status, refreshStatus } = useMemoryStatus();
  const [detail, setDetail] = useState<MemoryPeriodDetail | null | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);
  const [runSelection, setRunSelection] = useState<MemoryTaskSelection | null>(null);
  const [spawning, setSpawning] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const level = periodLevel(periodKey);

  // `status` changes on every poll and after every action; see MemoryStatusProvider.
  useEffect(() => {
    let cancelled = false;
    getMemoryPeriod(server, level, periodKey)
      .then((result) => {
        if (cancelled) return;
        setDetail(result);
        setError(null);
      })
      .catch((loadError: unknown) => {
        if (!cancelled) setError(loadError instanceof Error ? loadError.message : String(loadError));
      });
    return () => {
      cancelled = true;
    };
  }, [server, level, periodKey, status]);

  /** The spawned digest task starts pending; the run dialog shows its estimate before anything is billed. */
  async function regenerate(): Promise<void> {
    setSpawning(true);
    setError(null);
    setNotice(null);
    try {
      const { task_ids, skipped } = await spawnMemoryTasks(server, {
        kind: level === "week" ? "week_digest" : "month_digest",
        targets: [periodKey],
      });
      if (task_ids.length > 0) setRunSelection({ ids: task_ids });
      else if (skipped.every((skip) => skip.reason === "already_open")) setNotice(t("alreadyQueued"));
      else setNotice(t("notSpawned", { reasons: summarizeSkips(skipped) }));
      await refreshStatus();
    } catch (spawnError) {
      setError(spawnError instanceof Error ? spawnError.message : String(spawnError));
    } finally {
      setSpawning(false);
    }
  }

  if (error) return <p className="p-5 text-sm text-destructive">{error}</p>;
  if (detail === undefined) return <Loader2 className="m-5 h-5 w-5 animate-spin text-muted-foreground" />;
  if (detail === null) return <p className="p-5 text-sm text-muted-foreground">{t("unknownPeriod")}</p>;

  const { node, current } = detail;
  const dateRange = new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeZone: "UTC" }).formatRange(Date.parse(node.start), Date.parse(node.end));

  return (
    <div className="space-y-5 p-5">
      <header className="space-y-1">
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <h2 className="text-lg font-semibold tracking-tight">
            {node.level === "week" ? t("weekTitle", { key: node.key }) : monthLabel(node.key, locale, true)}
          </h2>
          <button type="button" onClick={() => void regenerate()} disabled={spawning} className={buttonClassName}>
            {spawning ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            {current ? t("regenerate") : t("generate")}
          </button>
        </div>
        <div className="flex flex-wrap items-center gap-x-2 text-sm text-muted-foreground">
          <span>{dateRange}</span>
          <span>·</span>
          <span>{t(node.level === "week" ? "coverageSessions" : "coverageWeeks", { covered: node.covered, total: node.total })}</span>
          <span>·</span>
          <PeriodBadgeMark badge={periodBadge(node)} />
          {node.task && node.task.status !== "done" ? <span>· {t("task", { status: node.task.status })}</span> : null}
        </div>
        {notice ? <p className="text-sm text-muted-foreground">{notice}</p> : null}
        {current ? (
          <div className="font-mono text-xs text-muted-foreground">
            {current.provenance.model} · {t("prompt", { version: current.provenance.prompt_version })} · carapace {current.provenance.carapace_version}
            {current.provenance.cost_usd !== null ? ` · ${formatUsd(current.provenance.cost_usd, locale)}` : null}
            {` · ${formatAbsoluteTime(current.provenance.created_at, locale)}`}
          </div>
        ) : null}
      </header>

      {current ? <DigestBody record={current} detail={detail} /> : <p className="text-sm text-muted-foreground">{t("noDigest")}</p>}

      <section>
        <h3 className="mb-2 text-xs font-medium uppercase tracking-[0.16em] text-muted-foreground">
          {node.level === "week" ? t("sourceSessions", { count: detail.sessions.length }) : t("sourceWeeks", { count: detail.weeks.length })}
        </h3>
        <ul className="divide-y divide-border/60 rounded-lg border border-border text-sm">
          {node.level === "week"
            ? detail.sessions.map((session) => (
              <li key={session.session_id} className="flex gap-3 px-3 py-2">
                <span className={cn("shrink-0", session.extraction ? "text-[#236b86]" : "text-muted-foreground")}>{session.extraction ? "✓" : "○"}</span>
                <span className="shrink-0 tabular-nums text-muted-foreground">
                  {new Intl.DateTimeFormat(locale, { month: "short", day: "numeric" }).format(Date.parse(session.created_at))}
                </span>
                <Link href={sessionHref(session.session_id)} className="min-w-0 flex-1 truncate hover:underline">
                  {session.title?.trim() || session.session_id}
                </Link>
                <span className="hidden min-w-0 max-w-[50%] truncate text-xs text-muted-foreground sm:block">
                  {session.extraction?.abstract ?? t("notExtracted")}
                </span>
              </li>
            ))
            : detail.weeks.map((week) => (
              <li key={week.key} className="flex items-center gap-3 px-3 py-2">
                <PeriodBadgeMark badge={periodBadge(week)} />
                <Link href={periodHref(week.key)} className="flex-1 hover:underline">{week.key}</Link>
                <span className="tabular-nums text-muted-foreground">{week.covered}/{week.total}</span>
              </li>
            ))}
        </ul>
      </section>

      {detail.history.length > 0 ? (
        <details className="group">
          <summary className="cursor-pointer text-xs font-medium uppercase tracking-[0.16em] text-muted-foreground">
            {t("history", { count: detail.history.length })}
          </summary>
          <div className="mt-2 space-y-2">
            {detail.history.map((record) => (
              <details key={record.id} className="rounded-lg border border-border px-3 py-2">
                <summary className="cursor-pointer text-sm">
                  <span className="font-mono text-xs">{record.provenance.model} · carapace {record.provenance.carapace_version}</span>
                  <span className="ml-2 text-xs text-muted-foreground">{formatAbsoluteTime(record.created_at, locale)}</span>
                </summary>
                <div className="space-y-2 pt-2">
                  <MemoryProvenanceList provenance={record.provenance} />
                  <p className="text-xs text-muted-foreground">{t("historyCoverage", { count: record.coverage.length })}</p>
                  <p className="text-sm leading-relaxed">{record.digest.summary}</p>
                </div>
              </details>
            ))}
          </div>
        </details>
      ) : null}

      {runSelection ? (
        <MemoryRunDialog
          server={server}
          token={token}
          selection={runSelection}
          onClose={() => setRunSelection(null)}
          onQueued={() => void refreshStatus()}
        />
      ) : null}
    </div>
  );
}

function DigestBody({ record, detail }: { record: MemoryDigestRecord; detail: MemoryPeriodDetail }) {
  const t = useTranslations("memory.timeline");
  const { digest } = record;
  const lists: [string, string[]][] = [
    [t("highlights"), digest.highlights],
    [t("openLoops"), digest.open_loops],
  ];

  return (
    <div className="space-y-4 text-sm">
      <section>
        <h3 className="mb-1 text-xs font-medium text-muted-foreground">{t("summary")}</h3>
        <p className="leading-relaxed">{digest.summary}</p>
      </section>

      <div className="grid gap-5 md:grid-cols-2">
        <div className="space-y-4">
          {digest.on_my_mind.length > 0 ? (
            <section>
              <h3 className="mb-1 text-xs font-medium text-muted-foreground">{t("onMyMind")}</h3>
              <ul className="list-disc space-y-1 pl-5">
                {digest.on_my_mind.map((theme) => (
                  <li key={theme.theme}>{theme.theme}<Refs refs={theme.refs} detail={detail} /></li>
                ))}
              </ul>
            </section>
          ) : null}
          {lists.filter(([, items]) => items.length > 0).map(([label, items]) => (
            <section key={label}>
              <h3 className="mb-1 text-xs font-medium text-muted-foreground">{label}</h3>
              <ul className="list-disc space-y-1 pl-5">
                {items.map((item) => <li key={item}>{item}</li>)}
              </ul>
            </section>
          ))}
        </div>

        <section>
          <h3 className="mb-1 text-xs font-medium text-muted-foreground">{t("learned")}</h3>
          {FACT_CATEGORIES.map((category) => {
            const facts = digest.learned.filter((fact) => fact.category === category);
            if (facts.length === 0) return null;
            return (
              <div key={category} className="mb-3">
                <h4 className="text-xs font-medium">{t(`factCategories.${category}`)}</h4>
                <ul className="mt-1 space-y-1.5">
                  {facts.map((fact) => <LearnedItem key={`${fact.subject}-${fact.statement}`} fact={fact} detail={detail} />)}
                </ul>
              </div>
            );
          })}
        </section>
      </div>
    </div>
  );
}

function LearnedItem({ fact, detail }: { fact: MemoryDigestFact; detail: MemoryPeriodDetail }) {
  const t = useTranslations("memory.drawer");
  return (
    <li>
      {fact.subject ? <span className="font-medium">{fact.subject}: </span> : null}
      {fact.statement}
      <Refs refs={fact.refs} detail={detail} />
      <div className="text-[11px] text-muted-foreground/80">
        {t(`confidence.${fact.confidence}`)} · {t(`sourceKind.${fact.source_kind}`)}
      </div>
    </li>
  );
}
