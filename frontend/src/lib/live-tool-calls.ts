import { Allow, MalformedJSON, parse } from "partial-json";

import type { ChatMessage } from "@/lib/types";

type ToolCallMessage = Extract<ChatMessage, { kind: "tool_call" }>;

/**
 * The args streamed so far as an object, so a streaming card renders like the final one. Null when
 * the text can't be read as an object (the model wrote malformed JSON): the card keeps what it had.
 */
export function parseStreamingArgs(text: string): Record<string, unknown> | null {
  if (!text.trim()) return {};
  try {
    const value: unknown = parse(text, Allow.ALL);
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
 * kept: they are never saved, but must not vanish seconds after their turn ended. Each goes after the
 * saved tool call it followed, or else after its turn's user message.
 */
export function keepUnrunCalls(live: ChatMessage[], projected: ChatMessage[]): ChatMessage[] {
  if (!live.some((m) => m.kind === "tool_call" && m.notRun)) return projected;
  const kept = [...projected];
  let insertAfter = -1;
  let users = 0;
  for (const message of live) {
    if (message.kind === "user") {
      users++;
      insertAfter = nthIndex(kept, (m) => m.kind === "user", users);
    } else if (message.kind === "tool_call" && message.notRun) {
      insertAfter = insertAfter === -1 ? kept.length : insertAfter + 1;
      kept.splice(insertAfter, 0, message);
    } else if (message.kind === "tool_call" && message.toolId) {
      const index = kept.findIndex((m) => m.kind === "tool_call" && m.toolId === message.toolId);
      if (index !== -1) insertAfter = index;
    }
  }
  return kept;
}

function nthIndex(messages: ChatMessage[], matches: (message: ChatMessage) => boolean, n: number): number {
  let seen = 0;
  return messages.findIndex((m) => matches(m) && ++seen === n);
}

function isOpen(message: ChatMessage): message is ToolCallMessage {
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
