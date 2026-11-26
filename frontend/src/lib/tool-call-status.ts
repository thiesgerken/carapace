import type { ChatMessage, RunningSpan, SpanUpdate } from "@/lib/types";

type ToolCallMessage = Extract<ChatMessage, { kind: "tool_call" }>;

/** The span kinds a card names while they run; the others (the gate, the exec itself) are the card's own spinner. */
export const STATUS_SPAN_KINDS = ["sentinel", "sandbox", "skill", "credential", "domain", "wait"] as const;
export type StatusSpanKind = (typeof STATUS_SPAN_KINDS)[number];
export type RunningStep = RunningSpan & { kind: StatusSpanKind };

/** The `wait` span of a call queued behind another command in the sandbox: system time, not the user's. */
export const EXEC_LOCK_SPAN = "exec lock";

/**
 * What a running step is about, for its label and the tortoise. Steps with a name of their own get a
 * topic of their own; any other name, such as a span added later, falls back to its kind.
 */
export type StepTopic = StatusSpanKind | "skillBuild" | "skillProfile" | "execLock";

const NAMED_TOPICS: Partial<Record<StatusSpanKind, Record<string, StepTopic>>> = {
  skill: { "build wait": "skillBuild", "profile sync": "skillProfile" },
  wait: { [EXEC_LOCK_SPAN]: "execLock" },
};

export function stepTopic(step: RunningStep): StepTopic {
  return NAMED_TOPICS[step.kind]?.[step.name] ?? step.kind;
}

/**
 * The span listed on its tool call's card while it runs. The newest card with that call id gets it,
 * since some providers reuse ids such as `call_0` across responses.
 */
export function applySpanToToolCall(messages: ChatMessage[], span: SpanUpdate): ChatMessage[] {
  const toolCallId = span.tool_call_id;
  if (!toolCallId) return messages;
  const index = messages.findLastIndex((m) => m.kind === "tool_call" && m.toolCallId === toolCallId);
  if (index === -1) return messages;
  const card = messages[index] as ToolCallMessage;
  const others = (card.runningSpans ?? []).filter((s) => s.spanId !== span.span_id);
  const runningSpans =
    span.status === "running"
      ? [...others, { spanId: span.span_id, kind: span.kind, name: span.name, startedAt: Date.parse(span.started_at) }]
      : others;
  // A running step proves the call still runs: after a reconnect, whose disconnect stopped every spinner, it spins again.
  const loading = card.loading || (span.status === "running" && card.result === undefined);
  return messages.with(index, { ...card, runningSpans, loading });
}

/** Every span of *spans* applied in order; for cards that arrive after their spans (the history load on a reload). */
export function applySpansToToolCalls(messages: ChatMessage[], spans: Iterable<SpanUpdate>): ChatMessage[] {
  let applied = messages;
  for (const span of spans) applied = applySpanToToolCall(applied, span);
  return applied;
}

/** Keeps *running* (by span id, in start order) at the spans that have started and not ended yet. */
export function trackRunningSpan(running: Map<string, SpanUpdate>, span: SpanUpdate): void {
  if (span.status === "running") running.set(span.span_id, span);
  else running.delete(span.span_id);
}

/** The newest running step the card names: the innermost one, as spans nest in start order. */
export function toolCallStatus(spans: RunningSpan[] | undefined): RunningStep | null {
  const named = spans?.findLast((s): s is RunningStep => (STATUS_SPAN_KINDS as readonly string[]).includes(s.kind));
  return named ?? null;
}

/** The step the newest running card waits on, if any; *messages* may also be just a tool group's. */
export function runningStep(messages: ChatMessage[]): RunningStep | null {
  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i];
    const step = m.kind === "tool_call" && m.loading ? toolCallStatus(m.runningSpans) : null;
    if (step) return step;
  }
  return null;
}
