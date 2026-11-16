import type { LlmPhases, LlmRequestRecord, Span } from "@/lib/types";

/** Where a turn's time went. `llm*` are the agent's own requests; sentinel requests count as `sentinel`. */
export const TIME_CATEGORIES = [
  "preparation",
  "llmWaiting",
  "llmThinking",
  "llmOutput",
  "sentinel",
  "sandbox",
  "skill",
  "execFile",
  "credential",
  "compaction",
  "other",
  "notCovered",
  "userWait",
] as const;
export type TimeCategory = (typeof TIME_CATEGORIES)[number];

export type LlmPhase = "llmWaiting" | "llmThinking" | "llmOutput";
export type Segment = { category: TimeCategory; start: number; end: number };

/** A span with its tree position (*parentId* resolved, see *timelineRows*) and its times in ms, a running span ending at *now*. */
export type TimelineRow = { span: Span; parentId: string | null; depth: number; start: number; end: number };

export type TimeBreakdown = {
  wallMs: number;
  userWaitMs: number;
  systemMs: number;
  byCategory: Record<TimeCategory, number>;
};

// Preparation and compaction get their own categories: both are prime suspects for a slow turn start.
const KIND_CATEGORY: Record<string, TimeCategory> = {
  "turn.prepare": "preparation",
  compaction: "compaction",
  gate: "sentinel",
  sentinel: "sentinel",
  // Proxy domain checks are security gating that runs inside an exec.
  domain: "sentinel",
  sandbox: "sandbox",
  skill: "skill",
  exec: "execFile",
  file: "execFile",
  credential: "credential",
  wait: "userWait",
};

const LLM_ROLE_CATEGORY: Record<string, TimeCategory> = { agent: "llmOutput", sentinel: "sentinel", compaction: "compaction" };

/** The category a span's own time counts as; agent LLM spans split further by phase (see *llmSegments*). */
export function spanCategory(span: Span): TimeCategory {
  if (span.kind === "llm") return LLM_ROLE_CATEGORY[span.llm?.role ?? ""] ?? "other";
  return KIND_CATEGORY[span.kind] ?? "other";
}

/**
 * An LLM request's phases: waiting for the first token (prefill, network, queue), thinking, output.
 * A missing timestamp collapses its phase: without any token yet, the whole request is waiting.
 */
export function llmSegments(llm: LlmPhases, start: number, end: number): Segment[] {
  const at = (iso: string | null) => (iso === null ? null : Math.min(Math.max(Date.parse(iso), start), end));
  const firstThinking = at(llm.first_thinking_at);
  const waitEnd = at(llm.first_token_at) ?? firstThinking ?? at(llm.first_text_at) ?? end;
  const segments: Segment[] = [{ category: "llmWaiting", start, end: waitEnd }];
  let outputStart = waitEnd;
  if (firstThinking !== null) {
    const thinkingStart = Math.max(firstThinking, waitEnd);
    const thinkingEnd = Math.max(at(llm.last_thinking_at) ?? at(llm.first_text_at) ?? end, thinkingStart);
    segments.push({ category: "llmOutput", start: waitEnd, end: thinkingStart }, { category: "llmThinking", start: thinkingStart, end: thinkingEnd });
    outputStart = thinkingEnd;
  }
  segments.push({ category: "llmOutput", start: outputStart, end });
  return segments.filter((segment) => segment.end > segment.start);
}

/** The spans in tree order (children by start), each clipped to the turn and with its depth; the root has depth 0. */
export function timelineRows(spans: Span[], turnEnd: number): TimelineRow[] {
  const children = new Map<string | null, Span[]>();
  const ids = new Set(spans.map((span) => span.span_id));
  for (const span of spans) {
    // A span whose parent is missing hangs under the root rather than disappearing.
    const parent = span.parent_id === null || ids.has(span.parent_id) ? span.parent_id : (spans.find((s) => s.parent_id === null)?.span_id ?? null);
    children.set(parent, [...(children.get(parent) ?? []), span]);
  }
  const rows: TimelineRow[] = [];
  const visit = (parent: string | null, depth: number) => {
    for (const span of (children.get(parent) ?? []).sort((a, b) => Date.parse(a.started_at) - Date.parse(b.started_at))) {
      const start = Date.parse(span.started_at);
      rows.push({ span, parentId: parent, depth, start, end: Math.max(start, Math.min(span.ended_at ? Date.parse(span.ended_at) : turnEnd, turnEnd)) });
      visit(span.span_id, depth + 1);
    }
  };
  visit(null, 0);
  return rows;
}

/**
 * Attributes every instant of the turn to the sequential main path, so parallel work never counts twice:
 * from the root, step into the earliest started active child, level by level; the instant belongs to
 * where that stops. Instants that stop at the root are "not covered", and instants inside a wait span
 * are user wait, whatever else runs then.
 */
export function summarizeTurn(rows: TimelineRow[], turnStart: number, turnEnd: number): TimeBreakdown {
  const byCategory = Object.fromEntries(TIME_CATEGORIES.map((category) => [category, 0])) as Record<TimeCategory, number>;
  const boundaries = [...new Set([turnStart, turnEnd, ...rows.flatMap((row) => [row.start, row.end])])]
    .filter((time) => time >= turnStart && time <= turnEnd)
    .sort((a, b) => a - b);

  // ponytail: O(boundaries × spans), fine for a turn's few hundred spans; a sweep line if turns grow to thousands.
  for (let index = 0; index + 1 < boundaries.length; index++) {
    const [start, end] = [boundaries[index], boundaries[index + 1]];
    const active = rows.filter((row) => row.start <= start && row.end >= end);
    if (active.some(({ span }) => span.kind === "wait")) {
      byCategory.userWait += end - start;
      continue;
    }
    // Rows list siblings by start, so the first active child is the earliest started one.
    const firstActiveChild = (parentId: string | null) => active.find((row) => row.parentId === parentId);
    let owner = firstActiveChild(null);
    for (let next = owner; next; next = firstActiveChild(next.span.span_id)) owner = next;
    if (owner === undefined || owner.depth === 0) {
      byCategory.notCovered += end - start;
    } else if (owner.span.llm?.role === "agent") {
      for (const segment of llmSegments(owner.span.llm, owner.start, owner.end)) {
        byCategory[segment.category] += Math.max(0, Math.min(segment.end, end) - Math.max(segment.start, start));
      }
    } else {
      byCategory[spanCategory(owner.span)] += end - start;
    }
  }

  const wallMs = Math.max(0, turnEnd - turnStart);
  return { wallMs, userWaitMs: byCategory.userWait, systemMs: wallMs - byCategory.userWait, byCategory };
}

/** An only child that covers at least this share of its parent tells nothing the parent doesn't: the gap is call overhead. */
const CHAIN_COVER = 0.75;

/** One line of the waterfall: a chain of spans shown as one (see *waterfallLines*), and its place in the drawn tree. */
export type WaterfallLine = {
  chain: TimelineRow[];
  depth: number;
  /** Whether the chain's last span has children; they follow unless it is collapsed. */
  hasChildren: boolean;
  /** Whether this is its parent's last line, so its tree guide ends here. */
  last: boolean;
  /** Per ancestor below the root, outermost first: whether its guide runs on past this line. */
  rails: boolean[];
};

/**
 * The waterfall's lines in tree order. A span whose only child covers nearly all of it merges with
 * that child into one line (a gate, its sentinel call and the sentinel's LLM request take the same
 * second), and so on down, as long as both have ended `ok`. The root never merges, since its
 * children are the turn's steps. Lines
 * below a collapsed span (keyed by the chain's last span) are left out.
 */
export function waterfallLines(rows: TimelineRow[], collapsed: ReadonlySet<string>): WaterfallLine[] {
  const children = new Map<string | null, TimelineRow[]>();
  for (const row of rows) children.set(row.parentId, [...(children.get(row.parentId) ?? []), row]);
  const childrenOf = (row: TimelineRow) => children.get(row.span.span_id) ?? [];

  const chainFrom = (head: TimelineRow) => {
    const chain = [head];
    for (let tail = head, next = childrenOf(tail); tail.parentId !== null && next.length === 1; tail = next[0], next = childrenOf(tail)) {
      // Only settled spans merge: running ones would fold and split as they grow, and an error or
      // interruption must keep its own red or grey bar instead of hiding behind its child's.
      if (tail.span.status !== "ok" || next[0].span.status !== "ok") break;
      if (next[0].end - next[0].start < CHAIN_COVER * (tail.end - tail.start)) break;
      chain.push(next[0]);
    }
    return chain;
  };

  const lines: WaterfallLine[] = [];
  const visit = (siblings: TimelineRow[], depth: number, rails: boolean[]) =>
    siblings.forEach((head, index) => {
      const chain = chainFrom(head);
      const tail = chain[chain.length - 1];
      const last = index === siblings.length - 1;
      lines.push({ chain, depth, hasChildren: childrenOf(tail).length > 0, last, rails });
      if (!collapsed.has(tail.span.span_id)) visit(childrenOf(tail), depth + 1, depth === 0 ? [] : [...rails, !last]);
    });
  visit(children.get(null) ?? [], 0, []);
  return lines;
}

export type RequestGroup = { turnId: string | null; records: LlmRequestRecord[] };

/**
 * A role's requests (oldest first, as the API sends them) grouped by turn, newest first in and
 * across groups. Requests outside a turn form one group, placed by its newest request.
 */
export function groupRequestsByTurn(records: LlmRequestRecord[]): RequestGroup[] {
  const groups = new Map<string | null, LlmRequestRecord[]>();
  for (const record of [...records].reverse()) groups.set(record.turn_id, [...(groups.get(record.turn_id) ?? []), record]);
  return [...groups].map(([turnId, grouped]) => ({ turnId, records: grouped }));
}
