import type { ChatMessage, RunningSpan, SpanUpdate } from "@/lib/types";

type ToolCallMessage = Extract<ChatMessage, { kind: "tool_call" }>;

/** The span kinds a card names while they run; the others (the gate, the exec itself) are the card's own spinner. */
export const STATUS_SPAN_KINDS = ["sentinel", "sandbox", "skill", "credential", "domain", "wait"] as const;
export type StatusSpanKind = (typeof STATUS_SPAN_KINDS)[number];

/** The `wait` span of a call queued behind another command in the sandbox: system time, not the user's. */
export const EXEC_LOCK_SPAN = "exec lock";

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
  const runningSpans = span.status === "running" ? [...others, { spanId: span.span_id, kind: span.kind, name: span.name }] : others;
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
export function toolCallStatus(spans: RunningSpan[] | undefined): (RunningSpan & { kind: StatusSpanKind }) | null {
  const named = spans?.findLast((s): s is RunningSpan & { kind: StatusSpanKind } =>
    (STATUS_SPAN_KINDS as readonly string[]).includes(s.kind),
  );
  return named ?? null;
}
