import type {
  MemoryBudgetWindowStatus,
  MemoryDigestLevel,
  MemoryMonthNode,
  MemoryPeriodNode,
  MemoryEstimateTotal,
  MemoryExtractionState,
  MemoryOutdatedReason,
  MemorySessionFilter,
  MemorySessionRow,
  MemoryTaskSpawnRequest,
  MemoryStatus,
  MemoryTaskFilter,
  MemoryTaskKind,
  MemoryTaskSelection,
  MemoryTaskStatus,
} from "./types";

export const MEMORY_TASK_STATUSES: readonly MemoryTaskStatus[] = ["pending", "queued", "running", "done", "failed", "cancelled"];
export const MEMORY_TASK_KINDS: readonly MemoryTaskKind[] = ["session_extract", "week_digest", "month_digest", "mirror"];

/** Budget-blocked tasks stay queued until the budget moves, so they don't count as progress to poll for. */
export function hasActiveTasks(status: MemoryStatus): boolean {
  return status.queue.queued - status.blocked + status.queue.running > 0;
}

/** True when the estimate exceeds the tightest remaining cost or input-token headroom. */
export function exceedsBudget(estimate: MemoryEstimateTotal, status: MemoryStatus): boolean {
  const remaining = remainingBudget(status);
  return (remaining.usd !== null && Number(estimate.cost_usd) > remaining.usd)
    || (remaining.tokens !== null && estimate.input_tokens > remaining.tokens);
}

/** Decimal strings from the API; tiny per-task costs need a third digit to not read as $0.00. */
export function formatUsd(value: string | number, locale: string): string {
  const amount = Number(value);
  return new Intl.NumberFormat(locale, {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: amount !== 0 && Math.abs(amount) < 1 ? 3 : 2,
  }).format(amount);
}

export function formatTokens(value: number, locale: string): string {
  return new Intl.NumberFormat(locale, { notation: "compact" }).format(value);
}

export type BudgetGauge =
  | { unit: "usd"; spent: number; limit: number | null }
  | { unit: "tokens"; spent: number; limit: number };

/** A cost limit wins over a token limit; without either the gauge shows spend only. */
export function budgetGauge(window: MemoryBudgetWindowStatus): BudgetGauge {
  if (window.limit_cost_usd === null && window.limit_input_tokens !== null) {
    return { unit: "tokens", spent: window.spent_input_tokens, limit: window.limit_input_tokens };
  }
  return {
    unit: "usd",
    spent: Number(window.spent_cost_usd),
    limit: window.limit_cost_usd === null ? null : Number(window.limit_cost_usd),
  };
}

/** Tightest headroom across the day and month windows; null when neither window limits it. */
export function remainingBudget(status: MemoryStatus): { usd: number | null; tokens: number | null } {
  const windows = [status.day, status.month];
  const headroom = (limits: (number | null)[]): number | null => {
    const set = limits.filter((limit): limit is number => limit !== null);
    return set.length === 0 ? null : Math.max(0, Math.min(...set));
  };
  return {
    usd: headroom(windows.map((w) => (w.limit_cost_usd === null ? null : Number(w.limit_cost_usd) - Number(w.spent_cost_usd)))),
    tokens: headroom(windows.map((w) => (w.limit_input_tokens === null ? null : w.limit_input_tokens - w.spent_input_tokens))),
  };
}

export interface TaskFilterForm {
  status: MemoryTaskStatus | "";
  kind: MemoryTaskKind | "";
  /** Month key from <input type="month">, e.g. 2026-09. */
  period: string;
  model: string;
}

export function toTaskFilter(form: TaskFilterForm): MemoryTaskFilter {
  return {
    status: form.status ? [form.status] : null,
    kind: form.kind ? [form.kind] : null,
    period: form.period || null,
    model: form.model || null,
  };
}

/** Either explicit rows or everything the current filter matches (across all pages). */
export type TaskPick = { kind: "ids"; ids: number[] } | { kind: "matching" };

export function toTaskSelection(pick: TaskPick, filter: MemoryTaskFilter): MemoryTaskSelection {
  return pick.kind === "ids" ? { ids: pick.ids } : { filter };
}

export const MEMORY_EXTRACTION_STATES: readonly MemoryExtractionState[] = ["missing", "current", "outdated"];
export const MEMORY_OUTDATED_REASONS: readonly MemoryOutdatedReason[] = ["prompt_version", "model", "input_format_version"];

export interface SessionFilterForm {
  /** ISO week key from <input type="week">, e.g. 2026-W36. */
  week: string;
  state: MemoryExtractionState | "";
  /** Only applies while state is "outdated". */
  outdatedReason: MemoryOutdatedReason | "";
  taskStatus: MemoryTaskStatus | "";
  model: string;
  channel: string;
}

export function toSessionFilter(form: SessionFilterForm): MemorySessionFilter {
  return {
    week: form.week || null,
    state: form.state ? [form.state] : null,
    outdated_reason: form.state === "outdated" && form.outdatedReason ? [form.outdatedReason] : null,
    task_status: form.taskStatus ? [form.taskStatus] : null,
    model: form.model || null,
    channel: form.channel || null,
  };
}

/** Either explicit sessions or everything the current filter matches (across all pages). */
export type SessionPick = { kind: "ids"; ids: string[] } | { kind: "matching" };

export function toSpawnRequest(pick: SessionPick, filter: MemorySessionFilter): MemoryTaskSpawnRequest {
  return pick.kind === "ids"
    ? { kind: "session_extract", targets: pick.ids }
    : { kind: "session_extract", filter };
}

/** Task ids behind the picked rows; sessions without a task have nothing to run. */
export function runnableTaskIds(rows: MemorySessionRow[], ids: string[]): number[] {
  return rows.flatMap((row) => (row.task && ids.includes(row.session_id) ? [row.task.id] : []));
}

/** Week keys are ISO weeks (2026-W36), month keys calendar months (2026-09). */
export function periodLevel(key: string): MemoryDigestLevel {
  return key.includes("-W") ? "week" : "month";
}

export type PeriodBadge =
  | { kind: "current" }
  | { kind: "stale"; reasons: ("sources" | MemoryOutdatedReason)[] }
  | { kind: "notRun" };

export function periodBadge(node: MemoryPeriodNode): PeriodBadge {
  if (node.digest === null) return { kind: "notRun" };
  const reasons = [...(node.stale ? (["sources"] as const) : []), ...node.digest.outdated];
  return reasons.length > 0 ? { kind: "stale", reasons } : { kind: "current" };
}

/** Months arrive newest first; years keep that order. */
export function groupMonthsByYear(months: MemoryMonthNode[]): [string, MemoryMonthNode[]][] {
  const years = new Map<string, MemoryMonthNode[]>();
  for (const month of months) {
    const year = month.key.slice(0, 4);
    years.set(year, [...(years.get(year) ?? []), month]);
  }
  return [...years];
}
