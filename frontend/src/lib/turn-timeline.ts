import type { LlmPhases, Span } from "@/lib/types";

/** Where a turn's time went. `llm*` are the agent's own requests; sentinel requests count as `sentinel`. */
export const TIME_CATEGORIES = [
  "llmWaiting",
  "llmThinking",
  "llmOutput",
  "sentinel",
  "sandbox",
  "skill",
  "execFile",
  "credential",
  "other",
  "notCovered",
  "userWait",
] as const;
export type TimeCategory = (typeof TIME_CATEGORIES)[number];

export type LlmPhase = "llmWaiting" | "llmThinking" | "llmOutput";
export type Segment = { category: TimeCategory; start: number; end: number };

/** A span with its tree position and its times in ms, a running span ending at *now*. */
export type TimelineRow = { span: Span; depth: number; start: number; end: number };

export type TurnSummary = {
  wallMs: number;
  userWaitMs: number;
  systemMs: number;
  byCategory: Record<TimeCategory, number>;
};

const KIND_CATEGORY: Record<string, TimeCategory> = {
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

/** The category a span's own time counts as; agent LLM spans split further by phase (see *llmSegments*). */
export function spanCategory(span: Span): TimeCategory {
  if (span.kind === "llm") return span.llm?.role === "sentinel" ? "sentinel" : span.llm?.role === "agent" ? "llmOutput" : "other";
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
      rows.push({ span, depth, start, end: Math.max(start, Math.min(span.ended_at ? Date.parse(span.ended_at) : turnEnd, turnEnd)) });
      visit(span.span_id, depth + 1);
    }
  };
  visit(null, 0);
  return rows;
}

/**
 * Attributes every instant of the turn to the deepest span active then, so parallel work never counts twice.
 * Titler spans run beside the turn and are ignored with everything below them; ties between overlapping
 * siblings go to the earliest started. Instants only the root covers are "not covered", and instants inside
 * a wait span are user wait, whatever else runs then.
 */
export function summarizeTurn(rows: TimelineRow[], turnStart: number, turnEnd: number): TurnSummary {
  const titlerSubtrees = new Set<string>();
  for (const { span } of rows) {
    if (span.kind === "titler" || (span.parent_id !== null && titlerSubtrees.has(span.parent_id))) titlerSubtrees.add(span.span_id);
  }
  const counted = rows.filter(({ span }) => !titlerSubtrees.has(span.span_id));
  const byCategory = Object.fromEntries(TIME_CATEGORIES.map((category) => [category, 0])) as Record<TimeCategory, number>;
  const boundaries = [...new Set([turnStart, turnEnd, ...counted.flatMap((row) => [row.start, row.end])])]
    .filter((time) => time >= turnStart && time <= turnEnd)
    .sort((a, b) => a - b);

  // ponytail: O(boundaries × spans), fine for a turn's few hundred spans; a sweep line if turns grow to thousands.
  for (let index = 0; index + 1 < boundaries.length; index++) {
    const [start, end] = [boundaries[index], boundaries[index + 1]];
    const active = counted.filter((row) => row.start <= start && row.end >= end);
    if (active.some(({ span }) => span.kind === "wait")) {
      byCategory.userWait += end - start;
      continue;
    }
    const owner = active.reduce<TimelineRow | null>((best, row) => (best === null || row.depth > best.depth || (row.depth === best.depth && row.start < best.start) ? row : best), null);
    if (owner === null || owner.depth === 0) {
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
