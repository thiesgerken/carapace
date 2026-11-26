import assert from "node:assert/strict";
import test from "node:test";

import type { ChatMessage, SpanUpdate } from "@/lib/types";

import { EXEC_LOCK_SPAN, applySpanToToolCall, applySpansToToolCalls, runningStep, stepTopic, toolCallStatus, trackRunningSpan } from "./tool-call-status";

const card = (toolCallId: string): ChatMessage => ({ kind: "tool_call", tool: "exec", args: {}, detail: "", loading: true, toolCallId });
const span = (span_id: string, kind: string, status: SpanUpdate["status"], tool_call_id: string | null = "call_0"): SpanUpdate => ({
  type: "span", turn_id: "t1", span_id, kind, name: kind === "domain" ? "pypi.org" : kind, status, started_at: "2026-11-26T12:00:00Z", tool_call_id,
});
const spansOf = (messages: ChatMessage[], index: number) => (messages[index] as Extract<ChatMessage, { kind: "tool_call" }>).runningSpans;

test("a call's running spans land on its newest card and leave it when they end", () => {
  // The provider reused call_0: the older card is done and must not pick up the new call's steps.
  let messages = [card("call_0"), card("call_0")];
  for (const update of [span("s1", "tool", "running"), span("s2", "sentinel", "running"), span("s2", "sentinel", "ok"), span("s3", "domain", "running")]) {
    messages = applySpanToToolCall(messages, update);
  }
  assert.equal(spansOf(messages, 0), undefined);
  assert.deepEqual(spansOf(messages, 1)?.map((s) => s.spanId), ["s1", "s3"]);
  assert.deepEqual(toolCallStatus(spansOf(messages, 1)), { spanId: "s3", kind: "domain", name: "pypi.org", startedAt: Date.parse("2026-11-26T12:00:00Z") });

  // Spans outside a tool call, or of a call without a card, change nothing.
  assert.equal(applySpanToToolCall(messages, span("s4", "sandbox", "running", null)), messages);
  assert.equal(applySpanToToolCall(messages, span("s4", "sandbox", "running", "call_9")), messages);
});

test("only steps a card names make its status, the innermost one first", () => {
  assert.equal(toolCallStatus([{ spanId: "a", kind: "tool", name: "exec", startedAt: 0 }, { spanId: "b", kind: "gate", name: "exec", startedAt: 0 }]), null);
  assert.equal(toolCallStatus([{ spanId: "a", kind: "sandbox", name: "ensure", startedAt: 0 }, { spanId: "b", kind: "exec", name: "exec", startedAt: 0 }])?.kind, "sandbox");
  assert.equal(toolCallStatus(undefined), null);
});

test("after a reconnect a replayed running step makes its card spin again, unless the call has its result", () => {
  // The disconnect stopped every spinner.
  const stopped = { ...card("call_0"), loading: false } as ChatMessage;
  const done = { ...card("call_1"), loading: false, result: "ok" } as ChatMessage;
  const messages = applySpansToToolCalls([stopped, done], [span("s1", "tool", "running"), span("s2", "tool", "running", "call_1")]);
  assert.equal((messages[0] as Extract<ChatMessage, { kind: "tool_call" }>).loading, true);
  assert.equal((messages[1] as Extract<ChatMessage, { kind: "tool_call" }>).loading, false);
});

test("spans heard before their card exists reach it once it does, the ended ones not", () => {
  const running = new Map<string, SpanUpdate>();
  for (const update of [span("s1", "tool", "running"), span("s2", "sentinel", "running"), span("s2", "sentinel", "ok"), span("s3", "skill", "running")]) {
    trackRunningSpan(running, update);
  }
  // The history load brings the card after the replay on connect.
  const messages = applySpansToToolCalls([card("call_0")], running.values());
  assert.deepEqual(spansOf(messages, 0)?.map((s) => s.spanId), ["s1", "s3"]);
});

test("a step's start is the server's, also when its running notice comes again after a reconnect", () => {
  let messages = applySpanToToolCall([card("call_0")], span("s1", "skill", "running"));
  messages = applySpanToToolCall(messages, span("s1", "skill", "running"));
  assert.equal(spansOf(messages, 0)?.[0].startedAt, Date.parse("2026-11-26T12:00:00Z"));
});

test("a step's topic comes from its name where the chat knows it, else from its kind", () => {
  const topic = (kind: "skill" | "wait", name: string) => stepTopic({ spanId: "s", kind, name, startedAt: 0 });
  assert.equal(topic("skill", "build wait"), "skillBuild");
  assert.equal(topic("skill", "profile sync"), "skillProfile");
  assert.equal(topic("wait", EXEC_LOCK_SPAN), "execLock");
  // Names it doesn't know, like a span added later or an approval's subject, fall back to the kind.
  assert.equal(topic("skill", "ensure_built"), "skill");
  assert.equal(topic("wait", "pypi.org"), "wait");
});

test("the running step is the one of the newest loading card that names a step", () => {
  const withSpans = (loading: boolean, kind: string, name: string): ChatMessage => ({
    kind: "tool_call", tool: "exec", args: {}, detail: "", loading, runningSpans: [{ spanId: kind, kind, name, startedAt: 0 }],
  });
  const messages = [withSpans(true, "sandbox", "ensure"), withSpans(true, "skill", "build wait"), withSpans(true, "exec", "exec"), withSpans(false, "wait", "approval")];
  assert.equal(runningStep(messages)?.name, "build wait");
  assert.equal(runningStep(messages.slice(0, 1))?.kind, "sandbox");
  assert.equal(runningStep([]), null);
});
