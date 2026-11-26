import type { ChatMessage, RunningSpan, SpanUpdate } from "@/lib/types";

type ToolCallMessage = Extract<ChatMessage, { kind: "tool_call" }>;

/** A card that waits for the user's answer: a tool approval or a sentinel escalation. */
export type EscalationCard = Extract<
  ChatMessage,
  { kind: "approval" | "domain_access_approval" | "git_push_approval" | "credential_approval" }
>;

export function isEscalationCard(message: ChatMessage): message is EscalationCard {
  return (
    message.kind === "approval"
    || message.kind === "domain_access_approval"
    || message.kind === "git_push_approval"
    || message.kind === "credential_approval"
  );
}

/** The span kinds a card names while they run; the others (the gate, the exec itself) are the card's own spinner. */
export const STATUS_SPAN_KINDS = ["sentinel", "sandbox", "skill", "credential", "domain", "wait"] as const;
export type StatusSpanKind = (typeof STATUS_SPAN_KINDS)[number];
export type RunningStep = RunningSpan & { kind: StatusSpanKind };
/** A card's running command: the waiting line's step when the card names none, never a label of the card's own. */
export type ExecStep = RunningSpan & { kind: "exec" };

// Span names are protocol: see "Span names clients match on" in docs/websocket-session.md.

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

/** Steps that read as one: a domain check is the sentinel's review of it, so they share a bucket. */
export type StepBucket = Exclude<StepTopic, "domain">;

export function stepBucket(step: RunningStep): StepBucket {
  const topic = stepTopic(step);
  return topic === "domain" ? "sentinel" : topic;
}

/** A step that waits for the user's answer, unlike the exec lock's wait behind another command. */
export function isUserWait(step: RunningStep): boolean {
  return step.kind === "wait" && step.name !== EXEC_LOCK_SPAN;
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
  // A replayed step proves the call still runs: the disconnect stopped every spinner, so it spins again. Only a
  // replay: the live start of a new call's step can precede that call's card and hit an older one of the same id.
  const loading = card.loading || (span.replayed && span.status === "running" && card.result === undefined);
  return messages.with(index, { ...card, runningSpans, loading });
}

/** Every span of *spans* applied in order; for cards that arrive after their spans (the history load on a reload). */
export function applySpansToToolCalls(messages: ChatMessage[], spans: Iterable<SpanUpdate>): ChatMessage[] {
  let applied = messages;
  for (const span of spans) applied = applySpanToToolCall(applied, span);
  return applied;
}

/** Without the steps on the cards: on a disconnect, since the server replays the ones still running on the reconnect. */
export function dropRunningSpans(messages: ChatMessage[]): ChatMessage[] {
  if (!messages.some((m) => m.kind === "tool_call" && m.runningSpans?.length)) return messages;
  return messages.map((m) => (m.kind === "tool_call" && m.runningSpans?.length ? { ...m, runningSpans: undefined } : m));
}

/** Keeps *running* (by span id, in start order) at the spans that have started and not ended yet. */
export function trackRunningSpan(running: Map<string, SpanUpdate>, span: SpanUpdate): void {
  if (span.status === "running") running.set(span.span_id, span);
  else running.delete(span.span_id);
}

const isStatusSpan = (span: RunningSpan): span is RunningStep => (STATUS_SPAN_KINDS as readonly string[]).includes(span.kind);

/**
 * The running step the card names: the innermost one, as spans nest in start order. It counts from the
 * outermost running span of its bucket, so nested steps (a sandbox start's stages, the sentinel inside a
 * domain check) keep one counter instead of restarting with each.
 */
export function toolCallStatus(spans: RunningSpan[] | undefined): RunningStep | null {
  const named = spans?.filter(isStatusSpan) ?? [];
  const innermost = named.at(-1);
  if (!innermost) return null;
  const bucket = stepBucket(innermost);
  const outermost = named.find((s) => stepBucket(s) === bucket) ?? innermost;
  return { ...innermost, startedAt: outermost.startedAt };
}

/**
 * The step the running cards wait on, if any; *messages* may also be just a tool group's. A wait for the
 * user beats every other step, since a call queued behind it would hide that the user has to act; otherwise
 * the newest card's step.
 */
export function runningStep(messages: ChatMessage[]): RunningStep | null {
  let newest: RunningStep | null = null;
  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i];
    const step = m.kind === "tool_call" && m.loading ? toolCallStatus(m.runningSpans) : null;
    if (step && isUserWait(step)) return step;
    newest ??= step;
  }
  return newest;
}

/**
 * What the waiting line acts out: whether the current turn waits for the user, else the step it waits on.
 * Only the turn's own cards count (those after the last user message), so a card left open by an earlier
 * turn can't claim the line. The open card is what says the user has to act: a user wait's span outlives
 * the answer for a moment, so the line skips those spans and falls through to the next step.
 */
export function waitingLineState(messages: ChatMessage[]): { awaitsUser: boolean; step: RunningStep | ExecStep | null } {
  const turn = messages.slice(messages.findLastIndex((m) => m.kind === "user") + 1);
  if (turn.some(isEscalationCard)) return { awaitsUser: true, step: null };
  for (let i = turn.length - 1; i >= 0; i--) {
    const m = turn[i];
    const step = m.kind === "tool_call" && m.loading ? toolCallStatus(m.runningSpans) : null;
    if (step && !isUserWait(step)) return { awaitsUser: false, step };
  }
  return { awaitsUser: false, step: runningExec(turn) };
}

/** The command the newest running card runs, for the waiting line when no card names a step. */
function runningExec(messages: ChatMessage[]): ExecStep | null {
  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i];
    const exec = m.kind === "tool_call" && m.loading ? m.runningSpans?.findLast((s): s is ExecStep => s.kind === "exec") : undefined;
    if (exec) return exec;
  }
  return null;
}
