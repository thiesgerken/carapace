"use client";

import { useEffect, useState, type ReactNode } from "react";
import Link from "next/link";
import { ArrowUpRight, Loader2 } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useMemorySessionDetail } from "@/components/memory-extraction-detail";
import { DetailList } from "@/components/memory-ui";
import { getMemoryPeriod } from "@/lib/api";
import { formatAbsoluteTime } from "@/lib/format-time";
import { formatTokens, formatUsd, monthLabel, taskRunModel } from "@/lib/memory";
import type { MemoryDigestLevel, MemoryModelRole, MemoryPeriodDetail, MemoryTaskView } from "@/lib/types";

/**
 * The expanded task row, most important first: the error, what the task is about (with the
 * record it produced inline), its numbers, then the provenance collapsed.
 */
export function MemoryTaskDetail({ server, task, models }: {
  server: string;
  task: MemoryTaskView;
  /** Effective role models, so an open task names the model it would run with now. */
  models: Record<MemoryModelRole, string> | null;
}) {
  const t = useTranslations("memory.tasks.detail");
  const tProvenance = useTranslations("memory.provenance");
  const locale = useLocale();
  const time = (iso: string | null) => (iso ? formatAbsoluteTime(iso, locale) : "—");
  const provenance = task.provenance;

  return (
    <div className="space-y-3 pt-2 text-sm">
      {task.error ? (
        <pre className="whitespace-pre-wrap rounded-md border border-destructive/40 bg-background p-2 font-mono text-xs text-destructive">{task.error}</pre>
      ) : null}
      {task.kind === "session_extract" ? <SessionTaskSubject server={server} task={task} /> : null}
      {task.kind === "week_digest" || task.kind === "month_digest" ? <DigestTaskSubject server={server} task={task} /> : null}
      <p className="text-xs tabular-nums text-muted-foreground">{taskNumbers(task, taskRunModel(task, models), locale, t)}</p>
      <details className="text-xs">
        <summary className="cursor-pointer text-muted-foreground hover:text-foreground">{t("details")}</summary>
        <div className="pt-2">
          <DetailList
            rows={[
              [t("id"), `#${task.id}`],
              [t("spawnedBy"), t(`spawnedByValue.${task.spawned_by}`)],
              [t("created"), time(task.created_at)],
              [t("queuedAt"), time(task.queued_at)],
              [t("started"), time(task.started_at)],
              [t("finished"), time(task.finished_at)],
              ...(provenance
                ? ([
                  [tProvenance("prompt"), provenance.prompt_version],
                  [tProvenance("inputFormat"), String(provenance.input_format_version)],
                  [tProvenance("inputHash"), provenance.input_hash.slice(0, 12)],
                  [tProvenance("carapace"), provenance.carapace_version],
                ] satisfies [string, string][])
                : []),
            ]}
          />
        </div>
      </details>
    </div>
  );
}

function taskNumbers(task: MemoryTaskView, model: string | null, locale: string, t: ReturnType<typeof useTranslations>): string {
  const attempts = t("attempts", { count: task.attempts });
  const { provenance, estimate } = task;
  if (provenance) {
    return [
      model,
      provenance.cost_usd === null ? null : formatUsd(provenance.cost_usd, locale),
      `${formatTokens(provenance.input_tokens, locale)} in · ${formatTokens(provenance.output_tokens, locale)} out`,
      `${(provenance.duration_ms / 1000).toFixed(1)} s`,
      attempts,
    ].filter(Boolean).join(" · ");
  }
  if (estimate) {
    return [
      model,
      estimate.cost_usd === null ? null : `~${formatUsd(estimate.cost_usd, locale)}`,
      `${t("estimate")} ${formatTokens(estimate.input_tokens, locale)} in · ≤${formatTokens(estimate.output_tokens_cap, locale)} out`,
      attempts,
    ].filter(Boolean).join(" · ");
  }
  return [model, attempts].filter(Boolean).join(" · ");
}

/** A task's own output, which after a regenerate is no longer the current record. */
function producedRecord<R extends { id: number }>(task: MemoryTaskView, current: R | null, history: R[]): R | null | undefined {
  if (task.result_id === null) return undefined;
  return [current, ...history].find((record) => record?.id === task.result_id) ?? null;
}

function SubjectHeader({ href, label, children }: { href: string; label: string; children?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
      <Link href={href} className="inline-flex items-center gap-1 font-medium hover:text-foreground/80">
        {label}
        <ArrowUpRight aria-hidden="true" className="h-3.5 w-3.5 text-muted-foreground" />
      </Link>
      {children}
    </div>
  );
}

function ResultNote({ produced, isCurrent }: { produced: unknown; isCurrent: boolean }) {
  const t = useTranslations("memory.tasks.detail");
  if (produced === null) return <p className="text-xs text-muted-foreground">{t("resultGone")}</p>;
  if (produced !== undefined && !isCurrent) return <p className="text-xs text-amber-700 dark:text-amber-400">{t("superseded")}</p>;
  return null;
}

function SessionTaskSubject({ server, task }: { server: string; task: MemoryTaskView }) {
  const t = useTranslations("memory.tasks.detail");
  const tSessions = useTranslations("memory.sessions");
  const { detail, error } = useMemorySessionDetail(server, task.target, task.status);
  const href = `/memory/sessions?session=${encodeURIComponent(task.target)}`;

  if (error) return <p className="text-xs text-destructive">{error}</p>;
  if (detail === undefined) return <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />;
  if (detail === null) return <SubjectHeader href={href} label={task.target_label} />;

  const produced = producedRecord(task, detail.current, detail.history);
  const facts = produced?.extraction.facts ?? [];
  const counts = {
    user: facts.filter((fact) => fact.category === "user").length,
    social: facts.filter((fact) => fact.category === "social").length,
    surroundings: facts.filter((fact) => fact.category === "surroundings").length,
  };

  return (
    <div className="space-y-1.5">
      <SubjectHeader href={href} label={detail.session.title?.trim() || task.target_label}>
        {produced ? (
          <span className="text-xs text-muted-foreground" title={tSessions("factsBreakdown", counts)}>{t("facts", { count: facts.length })}</span>
        ) : null}
      </SubjectHeader>
      <ResultNote produced={produced} isCurrent={produced?.is_current ?? true} />
      {produced ? <p className="leading-relaxed">{produced.extraction.abstract}</p> : null}
    </div>
  );
}

function DigestTaskSubject({ server, task }: { server: string; task: MemoryTaskView }) {
  const t = useTranslations("memory.timeline");
  const locale = useLocale();
  const level: MemoryDigestLevel = task.kind === "week_digest" ? "week" : "month";
  const { detail, error } = usePeriodDetail(server, level, task.target, task.status);
  const href = `/memory/timeline?period=${encodeURIComponent(task.target)}`;
  const label = level === "week" ? t("weekTitle", { key: task.target }) : monthLabel(task.target, locale, true);

  if (error) return <p className="text-xs text-destructive">{error}</p>;
  if (detail === undefined) return <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />;
  if (detail === null) return <SubjectHeader href={href} label={label} />;

  const produced = producedRecord(task, detail.current, detail.history);
  const { node } = detail;
  const sessionTitles = new Map(detail.sessions.map((row) => [row.session_id, row.title?.trim() || row.session_id]));
  const sources = produced
    ? produced.coverage.map(({ source_id }) => level === "week"
      ? { id: source_id, label: sessionTitles.get(source_id) ?? source_id, href: `/memory/sessions?session=${encodeURIComponent(source_id)}` }
      : { id: source_id, label: source_id, href: `/memory/timeline?period=${encodeURIComponent(source_id)}` })
    : [];

  return (
    <div className="space-y-2">
      <SubjectHeader href={href} label={label}>
        <span className="text-xs text-muted-foreground">
          {produced
            ? t(level === "week" ? "sourceSessions" : "sourceWeeks", { count: sources.length })
            : t(level === "week" ? "coverageSessions" : "coverageWeeks", { covered: node.covered, total: node.total })}
        </span>
      </SubjectHeader>
      <ResultNote produced={produced} isCurrent={produced?.is_current ?? true} />
      {sources.length > 0 ? (
        <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs">
          {sources.map((source) => (
            <Link key={source.id} href={source.href} className="text-muted-foreground hover:text-foreground">{source.label}</Link>
          ))}
        </div>
      ) : null}
      {produced ? (
        <>
          <p className="leading-relaxed">{produced.digest.summary}</p>
          {produced.digest.on_my_mind.length > 0 ? (
            <ul className="list-disc space-y-0.5 pl-5 text-muted-foreground">
              {produced.digest.on_my_mind.slice(0, 3).map((theme) => <li key={theme.theme}>{theme.theme}</li>)}
            </ul>
          ) : null}
        </>
      ) : null}
    </div>
  );
}

type PeriodOutcome = { key: string } & ({ detail: MemoryPeriodDetail | null } | { error: string });

/** Like useMemorySessionDetail: refetches when `refreshKey` changes, keyed by period. */
function usePeriodDetail(server: string, level: MemoryDigestLevel, key: string, refreshKey: unknown) {
  const [outcome, setOutcome] = useState<PeriodOutcome | null>(null);
  const outcomeKey = `${level}:${key}`;

  useEffect(() => {
    let cancelled = false;
    getMemoryPeriod(server, level, key)
      .then((detail) => {
        if (!cancelled) setOutcome({ key: outcomeKey, detail });
      })
      .catch((loadError: unknown) => {
        if (!cancelled) setOutcome({ key: outcomeKey, error: loadError instanceof Error ? loadError.message : String(loadError) });
      });
    return () => {
      cancelled = true;
    };
  }, [server, level, key, outcomeKey, refreshKey]);

  if (outcome === null || outcome.key !== outcomeKey) return { detail: undefined, error: null };
  return "error" in outcome ? { detail: undefined, error: outcome.error } : { detail: outcome.detail, error: null };
}
