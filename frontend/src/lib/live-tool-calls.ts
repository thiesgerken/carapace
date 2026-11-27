import { Allow, MalformedJSON, parse } from "partial-json";

import type { ChatMessage, LlmActivity } from "@/lib/types";

type ToolCallMessage = Extract<ChatMessage, { kind: "tool_call" }>;

/**
 * The args streamed so far as an object, so a streaming card renders like the final one. Null when
 * the text can't be read as an object (the model wrote malformed JSON): the card keeps what it had.
 * Without *partialStrings*, a string the model is still writing is left out, for a label that must
 * not show half-written.
 */
export function parseStreamingArgs(text: string, partialStrings = true): Record<string, unknown> | null {
  if (!text.trim()) return {};
  try {
    const value: unknown = parse(text, partialStrings ? Allow.ALL : Allow.ALL & ~Allow.STR);
    return value !== null && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
  } catch (error) {
    if (error instanceof MalformedJSON) return null;
    throw error;
  }
}

/**
 * The index of the streamed card still waiting for *toolCallId*'s final tool_call. Only open cards
 * count: some providers reuse ids such as `call_0` across responses, which must not reach older cards.
 */
function openStreamedCallIndex(messages: ChatMessage[], toolCallId: string): number {
  return messages.findLastIndex((m) => isOpen(m) && m.toolCallId === toolCallId);
}

/**
 * The open streamed card of *toolCallId* replaced in place by what it became (its final tool call,
 * or the approval card asking for it), so nothing jumps or shows twice. Null without such a card.
 */
export function replaceStreamedCall(messages: ChatMessage[], toolCallId: string | null | undefined, replacement: ChatMessage): ChatMessage[] | null {
  const index = toolCallId ? openStreamedCallIndex(messages, toolCallId) : -1;
  return index === -1 ? null : messages.with(index, replacement);
}

/**
 * A new card for the call. A card still open under the same id is from an earlier response (some
 * providers reuse ids such as `call_0`); that response's calls all ran or failed before this one
 * started, so it was not run.
 */
export function startStreamedCall(messages: ChatMessage[], toolCallId: string, tool: string): ChatMessage[] {
  const card: ChatMessage = { kind: "tool_call", tool, args: {}, detail: "", loading: true, toolCallId, argsText: "", argsStreaming: true };
  return [...updateOpenCall(messages, toolCallId, (stale) => ({ ...stale, argsStreaming: false, loading: false, notRun: true })), card];
}

export function appendStreamedArgs(messages: ChatMessage[], toolCallId: string, delta: string): ChatMessage[] {
  return updateOpenCall(messages, toolCallId, (card) => {
    const argsText = card.argsText + delta;
    return { ...card, argsText, args: parseStreamingArgs(argsText) ?? card.args };
  });
}

/**
 * The result of a streamed call that never sent its final tool_call (`list_skills` sends none): the
 * card is done. Null without an open card for *toolCallId*.
 */
export function completeStreamedCall(
  messages: ChatMessage[],
  toolCallId: string | null | undefined,
  outcome: Pick<ToolCallMessage, "result" | "files" | "exitCode" | "toolId">,
): ChatMessage[] | null {
  const index = toolCallId ? openStreamedCallIndex(messages, toolCallId) : -1;
  if (index === -1) return null;
  return messages.with(index, { ...(messages[index] as ToolCallMessage), ...outcome, loading: false, argsText: undefined, argsStreaming: undefined });
}

/** The model finished the args (the card waits for the gate), or the request ended while it wrote them. */
export function endStreamedCall(messages: ChatMessage[], toolCallId: string, aborted: boolean): ChatMessage[] {
  return updateOpenCall(messages, toolCallId, (card) => ({ ...card, argsStreaming: false, ...(aborted && { loading: false, notRun: true }) }));
}

/**
 * At the end of a turn, a streamed card whose final tool_call never came was not run (rejected args,
 * or a lost end message); it stays visible as such instead of spinning.
 */
export function markUnrunCalls(messages: ChatMessage[]): ChatMessage[] {
  if (!messages.some(isOpen)) return messages;
  return messages.map((m) => (isOpen(m) ? { ...m, argsStreaming: false, loading: false, notRun: true } : m));
}

/**
 * The chat re-rendered from the saved history (*projected*) with the not-run cards of the *live* one
 * kept: they are never saved, but must not vanish seconds after their turn ended. Each goes before
 * what followed it: the next saved call or user message, or else the end of the chat. A not-run card
 * is almost always the last thing its turn did, so this keeps it below the thinking and text before it.
 */
export function keepUnrunCalls(live: ChatMessage[], projected: ChatMessage[]): ChatMessage[] {
  if (!live.some((m) => m.kind === "tool_call" && m.notRun)) return projected;
  const kept = [...projected];
  for (const [index, message] of live.entries()) {
    if (message.kind !== "tool_call" || !message.notRun) continue;
    let before = -1;
    for (let next = index + 1; next < live.length && before === -1; next++) before = savedIndex(kept, live, next);
    kept.splice(before === -1 ? kept.length : before, 0, message);
  }
  return kept;
}

/** Where the message at *index* of *live* is in the saved chat, if it is a saved call or a user message. */
function savedIndex(kept: ChatMessage[], live: ChatMessage[], index: number): number {
  const message = live[index];
  if (message.kind === "tool_call" && message.toolId) return kept.findIndex((m) => m.kind === "tool_call" && m.toolId === message.toolId);
  if (message.kind === "user") return nthIndex(kept, (m) => m.kind === "user", live.slice(0, index + 1).filter((m) => m.kind === "user").length);
  return -1;
}

/** Without the streamed cards still waiting: after a reconnect, the server sends those calls as tool_call. */
export function dropOpenCalls(messages: ChatMessage[]): ChatMessage[] {
  return messages.some(isOpen) ? messages.filter((m) => !isOpen(m)) : messages;
}

function nthIndex(messages: ChatMessage[], matches: (message: ChatMessage) => boolean, n: number): number {
  let seen = 0;
  return messages.findIndex((m) => matches(m) && ++seen === n);
}

/**
 * The card the agent's request is writing right now, which carries the request's counter: the newest
 * card still streaming args. -1 outside a tool call phase or before its card arrived.
 */
export function streamingCallIndex(messages: ChatMessage[], activity: LlmActivity | null): number {
  if (activity?.source !== "agent" || activity.phase !== "tool_call") return -1;
  // ponytail: parallel calls stream one after another, so the newest open card is the one being written.
  return messages.findLastIndex((m) => isOpen(m) && m.argsStreaming === true);
}

/** A card whose args the model is still writing: only the live transcript has it, the history doesn't yet. */
export function isOpen(message: ChatMessage): message is ToolCallMessage {
  return message.kind === "tool_call" && message.argsText !== undefined && !message.notRun;
}

function updateOpenCall(
  messages: ChatMessage[],
  toolCallId: string,
  update: (card: ToolCallMessage & { argsText: string }) => ToolCallMessage,
): ChatMessage[] {
  const index = openStreamedCallIndex(messages, toolCallId);
  if (index === -1) return messages;
  const next = [...messages];
  next[index] = update(messages[index] as ToolCallMessage & { argsText: string });
  return next;
}
