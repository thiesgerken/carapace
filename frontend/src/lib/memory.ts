import type {
  MemoryBudgetWindowStatus,
  MemoryDependencySummary,
  MemorySpawnSkip,
  MemoryFactView,
  MemoryDigestLevel,
  MemoryMonthNode,
  MemoryPeriodNode,
  MemoryEstimateTotal,
  MemoryExtractionState,
  MemoryModelRole,
  MemoryOutdatedReason,
  MemorySessionFilter,
  MemorySessionRow,
  MemoryTaskSpawnRequest,
  MemoryStatus,
  MemoryTask,
  MemoryTaskFilter,
  MemoryTaskKind,
  MemoryTaskSelection,
  MemoryTaskStatus,
} from "./types";

export const MEMORY_TASK_STATUSES: readonly MemoryTaskStatus[] = ["pending", "queued", "running", "done", "failed", "cancelled"];
/** Failed counts as unfinished: it still needs attention. */
export const UNFINISHED_TASK_STATUSES: readonly MemoryTaskStatus[] = ["pending", "queued", "running", "failed"];
export const MEMORY_TASK_KINDS: readonly MemoryTaskKind[] = ["session_extract", "week_digest", "month_digest", "mirror"];

const TASK_MODEL_ROLES: Record<MemoryTaskKind, MemoryModelRole | null> = {
  session_extract: "memory_low",
  week_digest: "memory_high",
  month_digest: "memory_high",
  mirror: null,
};

/** The model(s) a run of these task kinds resolves to without an override; null when none needs a model. */
export function roleDefaultModels(kinds: readonly MemoryTaskKind[], models: Record<MemoryModelRole, string>): string | null {
  const roles = (["memory_low", "memory_high"] as const).filter((role) => kinds.some((kind) => TASK_MODEL_ROLES[kind] === role));
  if (roles.length === 0) return null;
  if (roles.length === 1 || models.memory_low === models.memory_high) return models[roles[0]];
  return `low: ${models.memory_low} · high: ${models.memory_high}`;
}

/**
 * The model a task ran with, or would run with now. Not the estimate's model: that is the role
 * default at spawn time, and the worker resolves the role again when the task runs.
 */
export function taskRunModel(task: MemoryTask, models: Record<MemoryModelRole, string> | null): string | null {
  if (task.provenance) return task.provenance.model;
  if (task.model_override) return task.model_override;
  const role = TASK_MODEL_ROLES[task.kind];
  return role && models ? models[role] : null;
}

/** When the task last changed: the timestamp the "activity" sort orders by. */
export function taskActivityAt(task: MemoryTask): string {
  return task.finished_at ?? task.started_at ?? task.queued_at ?? task.created_at;
}

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

/**
 * Decimal strings from the API. A typical extraction costs fractions of a cent, so sub-cent amounts
 * keep two significant digits ($0.0021, never $0.00). Exact zero and budgets stay at two decimals.
 */
export function formatUsd(value: string | number, locale: string): string {
  const amount = Number(value);
  const magnitude = Math.abs(amount);
  const digits = amount !== 0 && magnitude < 0.01
    ? { maximumSignificantDigits: 2 }
    : { minimumFractionDigits: 2, maximumFractionDigits: amount !== 0 && magnitude < 1 ? 3 : 2 };
  return new Intl.NumberFormat(locale, { style: "currency", currency: "USD", ...digits }).format(amount);
}

export function formatTokens(value: number, locale: string): string {
  return new Intl.NumberFormat(locale, { notation: "compact" }).format(value);
}

/** What a run may consume when cost is unknown (models without pricing): exact input, capped output. */
export function formatTokenEstimate(inputTokens: number, outputTokensCap: number, locale: string): string {
  return `${formatTokens(inputTokens, locale)} in · ≤${formatTokens(outputTokensCap, locale)} out`;
}

/** Skip reasons of a spawn, counted: "no_handler" or "private ×3, already_open". */
export function summarizeSkips(skipped: MemorySpawnSkip[]): string {
  const counts = new Map<string, number>();
  for (const { reason } of skipped) counts.set(reason, (counts.get(reason) ?? 0) + 1);
  return [...counts].map(([reason, count]) => (count > 1 ? `${reason} ×${count}` : reason)).join(", ");
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
  status: MemoryTaskStatus | "unfinished" | "";
  kind: MemoryTaskKind | "";
  /** Month key from <input type="month">, e.g. 2026-09, or a week key set by a digest's source link. */
  period: string;
  model: string;
}

/** The filter listing a digest's source tasks: a week's extractions, or everything in a month. */
export function sourceTasksForm(digest: Pick<MemoryTask, "kind" | "target">): TaskFilterForm {
  return { status: "", kind: digest.kind === "week_digest" ? "session_extract" : "", period: digest.target, model: "" };
}

/** Sources a digest would run without: pending ones, plus failed or cancelled ones without a current record. */
export function missingSourceCount(dependencies: MemoryDependencySummary): number {
  return dependencies.pending_ids.length + dependencies.failed;
}

export function toTaskFilter(form: TaskFilterForm): MemoryTaskFilter {
  return {
    status: form.status === "unfinished" ? [...UNFINISHED_TASK_STATUSES] : form.status ? [form.status] : null,
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
    outdated_reason: form.state === "outdated" && form.outdatedReason ? form.outdatedReason : null,
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

/** Month nodes start on the Monday of their first week, so the name comes from the key. */
export function monthLabel(key: string, locale: string, withYear: boolean): string {
  const [year, month] = key.split("-").map(Number);
  return new Intl.DateTimeFormat(locale, { month: "long", ...(withYear ? { year: "numeric" } : {}), timeZone: "UTC" })
    .format(Date.UTC(year, month - 1, 1));
}

const DAY_MS = 86_400_000;

/** Monday to Sunday of an ISO week key, and the month its digest rolls into: the month of its Thursday (periods.month_key_for_week). */
export function isoWeek(key: string): { start: Date; end: Date; monthKey: string } {
  const match = /^(\d{4})-W(\d{2})$/.exec(key);
  if (match === null) throw new Error(`invalid week key ${key}`);
  // Week 1 is the week containing January 4th.
  const jan4 = new Date(Date.UTC(Number(match[1]), 0, 4));
  const start = jan4.getTime() - ((jan4.getUTCDay() + 6) % 7) * DAY_MS + (Number(match[2]) - 1) * 7 * DAY_MS;
  const thursday = new Date(start + 3 * DAY_MS);
  return {
    start: new Date(start),
    end: new Date(start + 6 * DAY_MS),
    monthKey: `${thursday.getUTCFullYear()}-${String(thursday.getUTCMonth() + 1).padStart(2, "0")}`,
  };
}

/** E.g. "July 2026 · Jul 27 – Aug 2": the week's month first, since a boundary week can sit in the other one. */
export function weekLabel(key: string, locale: string, withMonth: boolean): string {
  const { start, end, monthKey } = isoWeek(key);
  const range = new Intl.DateTimeFormat(locale, { day: "numeric", month: "short", timeZone: "UTC" }).formatRange(start, end);
  return withMonth ? `${monthLabel(monthKey, locale, true)} · ${range}` : range;
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

/** The same fact from several sessions, merged by normalized statement + subject. */
export interface FactGroup {
  key: string;
  latest: MemoryFactView;
  occurrences: MemoryFactView[];
  firstSeen: string;
  lastSeen: string;
}

function normalizeFactText(value: string | null): string {
  return (value ?? "").trim().toLowerCase().replace(/\s+/g, " ").replace(/[.!]+$/, "");
}

/** ponytail: exact normalized match only; fuzzy dedup is a planned follow-up. */
export function groupFacts(facts: MemoryFactView[]): FactGroup[] {
  const groups = new Map<string, MemoryFactView[]>();
  for (const fact of facts) {
    const key = `${normalizeFactText(fact.subject)}\u0000${normalizeFactText(fact.statement)}`;
    groups.set(key, [...(groups.get(key) ?? []), fact]);
  }
  return [...groups].map(([key, occurrences]) => {
    // ISO week keys are zero-padded, so they sort chronologically as strings.
    const sorted = [...occurrences].sort((a, b) => a.week_key.localeCompare(b.week_key) || a.created_at.localeCompare(b.created_at));
    const latest = sorted[sorted.length - 1];
    return { key, latest, occurrences: sorted, firstSeen: sorted[0].week_key, lastSeen: latest.week_key };
  }).sort((a, b) => b.lastSeen.localeCompare(a.lastSeen));
}

/** Dated facts stop being true after valid_until (an ISO date). */
export function isExpiredFact(fact: MemoryFactView, today: string): boolean {
  return fact.durability === "dated" && fact.valid_until !== null && fact.valid_until < today;
}

export function factMatchesText(group: FactGroup, query: string): boolean {
  const needle = query.trim().toLowerCase();
  if (!needle) return true;
  return [group.latest.statement, group.latest.subject, ...group.occurrences.map((fact) => fact.session_title)]
    .some((text) => text?.toLowerCase().includes(needle));
}
