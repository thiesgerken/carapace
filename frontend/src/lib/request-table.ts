import type { LlmRequestCost, LlmRequestRecord } from "@/lib/types";

/** A count column that is 0 or unknown in every row tells nothing, so the request table leaves it out. */
export function isEmptyColumn(records: LlmRequestRecord[], value: (record: LlmRequestRecord) => number | null): boolean {
  return records.every((record) => !value(record));
}

/** How long the request took, in ms; null when it has no completion time (interrupted, or recorded before timing). */
export function requestDurationMs(record: LlmRequestRecord): number | null {
  return record.started_at && record.completed_at ? Date.parse(record.completed_at) - Date.parse(record.started_at) : null;
}

/** Cache read ÷ input; null when the record has no cache count or no input. */
export function cacheHitRate(record: LlmRequestRecord): number | null {
  return record.cache_read_tokens === null || record.input_tokens === 0 ? null : record.cache_read_tokens / record.input_tokens;
}

/**
 * How a request's cost reads in one cell: the actual cost, or only the equivalent when a
 * subscription made the actual cost zero. The server prices nothing else: the actual cost is the
 * list price or zero.
 */
export function costShape(cost: LlmRequestCost | null): "none" | "actual" | "subscription" {
  if (cost?.cost_usd == null || cost.equivalent_cost_usd == null) return "none";
  return Number(cost.cost_usd) === 0 && Number(cost.equivalent_cost_usd) !== 0 ? "subscription" : "actual";
}

/**
 * A count as "12.3k" or "1.2M" in the locale's digits. German Intl compact notation leaves
 * thousands unabbreviated, so the suffixes are fixed instead.
 */
export function compactCount(value: number, formatNumber: (value: number, maximumFractionDigits: number) => string): string {
  if (Math.abs(value) >= 1_000_000) return `${formatNumber(value / 1_000_000, 1)}M`;
  if (Math.abs(value) >= 1000) return `${formatNumber(value / 1000, 1)}k`;
  return formatNumber(value, 0);
}
