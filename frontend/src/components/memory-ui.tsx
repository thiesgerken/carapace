"use client";

import { Fragment } from "react";
import { useLocale, useTranslations } from "next-intl";
import { formatAbsoluteTime } from "@/lib/format-time";
import { formatTokens, formatUsd } from "@/lib/memory";
import type { MemoryProvenance } from "@/lib/types";

export const controlClassName = "rounded-lg border border-border bg-background px-2.5 py-1.5 text-sm outline-none focus:border-ring focus:ring-2 focus:ring-ring/30 disabled:opacity-50";
export const buttonClassName = "inline-flex items-center gap-2 rounded-lg border border-border bg-background px-3 py-1.5 text-sm font-medium transition-colors hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50";

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
