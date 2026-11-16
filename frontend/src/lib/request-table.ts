import type { LlmRequestCost, LlmRequestRecord } from "@/lib/types";

/** A count column that is 0 or unknown in every row tells nothing, so the request table leaves it out. */
export function isEmptyColumn(records: LlmRequestRecord[], value: (record: LlmRequestRecord) => number | null): boolean {
  return records.every((record) => !value(record));
}

/** Cache read ÷ input; null when the record has no cache count or no input. */
export function cacheHitRate(record: LlmRequestRecord): number | null {
  return record.cache_read_tokens === null || record.input_tokens === 0 ? null : record.cache_read_tokens / record.input_tokens;
}

/**
 * How a request's cost reads in one cell: the actual cost when it is the list price, only the
 * equivalent when a subscription made the actual cost zero, both when they differ otherwise.
 */
export function costShape(cost: LlmRequestCost | null): "none" | "actual" | "subscription" | "both" {
  if (cost?.cost_usd == null || cost.equivalent_cost_usd == null) return "none";
  const [actual, equivalent] = [Number(cost.cost_usd), Number(cost.equivalent_cost_usd)];
  if (actual === equivalent) return "actual";
  return actual === 0 ? "subscription" : "both";
}
