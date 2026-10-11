"use client";

import { Fragment, type ReactNode } from "react";
import { Ban, CheckCircle2, ChevronRight, Clock, Hourglass, Loader2, XCircle, type LucideIcon } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { formatAbsoluteTime } from "@/lib/format-time";
import { formatTokens, formatUsd } from "@/lib/memory";
import type { MemoryProvenance, MemoryTaskStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

export const controlClassName = "rounded-lg border border-border bg-background px-2.5 py-1.5 text-sm outline-none focus:border-ring focus:ring-2 focus:ring-ring/30 disabled:opacity-50";
export const buttonClassName = "inline-flex items-center gap-2 rounded-lg border border-border bg-background px-3 py-1.5 text-sm font-medium transition-colors hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50";

const TASK_STATUS_LOOKS: Record<MemoryTaskStatus, { icon: LucideIcon; className: string }> = {
  pending: { icon: Clock, className: "text-muted-foreground" },
  queued: { icon: Hourglass, className: "text-sky-700 dark:text-sky-400" },
  running: { icon: Loader2, className: "text-sky-700 dark:text-sky-400" },
  done: { icon: CheckCircle2, className: "text-emerald-700 dark:text-emerald-400" },
  failed: { icon: XCircle, className: "text-destructive" },
  cancelled: { icon: Ban, className: "text-muted-foreground line-through" },
};

export function TaskStatusBadge({ status }: { status: MemoryTaskStatus }) {
  const t = useTranslations("memory.taskStatuses");
  const { icon: Icon, className } = TASK_STATUS_LOOKS[status];
  return (
    <span className={cn("inline-flex items-center gap-1 whitespace-nowrap", className)}>
      <Icon aria-hidden="true" className={cn("h-3.5 w-3.5 shrink-0", status === "running" && "animate-spin")} />
      {t(status)}
    </span>
  );
}

/** A `t.rich` tag rendering the badge, for sentences like "task <status></status>". */
export function taskStatusTag(status: MemoryTaskStatus) {
  return function TaskStatusTag() {
    return <TaskStatusBadge status={status} />;
  };
}

/** Shown above a table only while rows are selected, so the bulk actions never sit there disabled. */
export function SelectionBar({ count, onClear, children }: { count: number; onClear: () => void; children: ReactNode }) {
  const t = useTranslations("memory.pick");
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border bg-muted/40 px-3 py-1.5 text-sm">
      <span className="font-medium tabular-nums">{t("selected", { count })}</span>
      {children}
      <button type="button" onClick={onClear} className="ml-auto text-xs text-muted-foreground hover:text-foreground">{t("clear")}</button>
    </div>
  );
}

/** The chevron that expands a table row; `controls` is the id of the expanded detail row. */
export function ExpandButton({ expanded, controls, label, onToggle }: { expanded: boolean; controls: string; label: string; onToggle: () => void }) {
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-expanded={expanded}
      aria-controls={expanded ? controls : undefined}
      aria-label={label}
      title={label}
      className="inline-flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground"
    >
      <ChevronRight className={cn("h-4 w-4 transition-transform", expanded && "rotate-90")} />
    </button>
  );
}

/** Row clicks expand the row, except on controls that have their own action. */
export function togglesRow(target: EventTarget): boolean {
  return !(target instanceof Element && target.closest("a, button, input, label, select"));
}

/** Table header row offering to widen a full-page selection to everything the filter matches. */
export function PickMatchingRow({ colSpan, total, matching, onPickMatching, onClear }: {
  colSpan: number;
  total: number;
  matching: boolean;
  onPickMatching: () => void;
  onClear: () => void;
}) {
  const t = useTranslations("memory.pick");
  return (
    <tr>
      <td colSpan={colSpan} className="bg-muted/50 px-3 py-1.5 text-center text-xs">
        {matching ? (
          <>
            {t("pickedMatching", { count: total })}{" "}
            <button type="button" onClick={onClear} className="font-medium underline underline-offset-2">{t("clear")}</button>
          </>
        ) : (
          <button type="button" onClick={onPickMatching} className="font-medium underline underline-offset-2">
            {t("pickMatching", { count: total })}
          </button>
        )}
      </td>
    </tr>
  );
}

const detailListClassName = "grid grid-cols-[max-content_1fr] gap-x-6 gap-y-1 text-xs sm:grid-cols-[max-content_1fr_max-content_1fr]";

export function DetailList({ rows }: { rows: [string, string][] }) {
  return (
    <dl className={detailListClassName}>
      {rows.map(([label, value]) => (
        <Fragment key={label}>
          <dt className="text-muted-foreground">{label}</dt>
          <dd className="break-all font-mono">{value}</dd>
        </Fragment>
      ))}
    </dl>
  );
}

export function MemoryProvenanceList({ provenance }: { provenance: MemoryProvenance }) {
  const t = useTranslations("memory.provenance");
  const locale = useLocale();
  return (
    <DetailList
      rows={[
        [t("model"), provenance.model],
        [t("prompt"), provenance.prompt_version],
        [t("inputFormat"), String(provenance.input_format_version)],
        [t("carapace"), provenance.carapace_version],
        [t("inputHash"), provenance.input_hash.slice(0, 12)],
        [t("usage"), `${formatTokens(provenance.input_tokens, locale)} in · ${formatTokens(provenance.output_tokens, locale)} out`],
        [t("cost"), provenance.cost_usd === null ? t("unpriced") : formatUsd(provenance.cost_usd, locale)],
        [t("duration"), `${(provenance.duration_ms / 1000).toFixed(1)} s`],
        [t("created"), formatAbsoluteTime(provenance.created_at, locale)],
        [t("task"), `#${provenance.task_id}`],
      ]}
    />
  );
}
