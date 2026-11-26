import assert from "node:assert/strict";
import test from "node:test";

import type { ChatMessage, SpanUpdate } from "@/lib/types";

import {
  EXEC_LOCK_SPAN,
  applySpanToToolCall,
  applySpansToToolCalls,
  dropRunningSpans,
  runningExec,
  runningStep,
  stepTopic,
  toolCallStatus,
  trackRunningSpan,
} from "./tool-call-status";

const card = (toolCallId: string): ChatMessage => ({ kind: "tool_call", tool: "exec", args: {}, detail: "", loading: true, toolCallId });
const span = (span_id: string, kind: string, status: SpanUpdate["status"], tool_call_id: string | null = "call_0"): SpanUpdate => ({
  type: "span", turn_id: "t1", span_id, kind, name: kind === "domain" ? "pypi.org" : kind, status, started_at: "2026-11-26T12:00:00Z", tool_call_id, replayed: false,
});
const replayed = (span_id: string, kind: string, tool_call_id = "call_0"): SpanUpdate => ({ ...span(span_id, kind, "running", tool_call_id), replayed: true });
const loadingOf = (messages: ChatMessage[], index: number) => (messages[index] as Extract<ChatMessage, { kind: "tool_call" }>).loading;
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
  const messages = applySpansToToolCalls([stopped, done], [replayed("s1", "tool"), replayed("s2", "tool", "call_1")]);
  assert.equal(loadingOf(messages, 0), true);
  assert.equal(loadingOf(messages, 1), false);
});

test("a live step never revives a stopped card: it can be a new call's, heard before its own card, under a reused id", () => {
  // An earlier call_0 whose result the disconnect lost; the provider reuses call_0 for the next call.
  const earlier = { ...card("call_0"), loading: false } as ChatMessage;
  const messages = applySpanToToolCall([earlier], span("s9", "tool", "running"));
  assert.equal(loadingOf(messages, 0), false);
});

test("a disconnect takes the steps off the cards: one that ends offline would otherwise stay for good", () => {
  const messages = applySpanToToolCall([card("call_0")], span("s1", "wait", "running"));
  const dropped = dropRunningSpans(messages);
  assert.equal(spansOf(dropped, 0), undefined);
  assert.equal(dropRunningSpans(dropped), dropped);
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

test("nested steps of one bucket count from the outermost, a new bucket from its own start", () => {
  const at = (kind: string, name: string, startedAt: number) => ({ spanId: `${kind}:${name}`, kind, name, startedAt });
  const sandbox = toolCallStatus([at("tool", "exec", 0), at("sandbox", "ensure", 1_000), at("sandbox", "create", 3_000), at("sandbox", "wait_for_ready", 4_000)]);
  assert.deepEqual([sandbox?.name, sandbox?.startedAt], ["wait_for_ready", 1_000]);
  // The sentinel reviewing a domain is the domain check's bucket; the user's answer to it is a wait of its own.
  const review = toolCallStatus([at("domain", "pypi.org", 1_000), at("sentinel", "domain", 2_000)]);
  assert.deepEqual([review?.kind, review?.startedAt], ["sentinel", 1_000]);
  const escalated = toolCallStatus([at("domain", "pypi.org", 1_000), at("sentinel", "domain", 2_000), at("wait", "pypi.org", 5_000)]);
  assert.deepEqual([escalated?.kind, escalated?.startedAt], ["wait", 5_000]);
  const build = toolCallStatus([at("skill", "ensure_built", 1_000), at("skill", "build wait", 2_000)]);
  assert.deepEqual([build?.name, build?.startedAt], ["build wait", 2_000]);
});

test("a call waiting for the user outranks a newer call's step, such as one queued behind it on the exec lock", () => {
  const withSpan = (kind: string, name: string): ChatMessage => ({
    kind: "tool_call", tool: "exec", args: {}, detail: "", loading: true, runningSpans: [{ spanId: kind, kind, name, startedAt: 0 }],
  });
  const awaitsUser = withSpan("wait", "pypi.org");
  assert.equal(runningStep([awaitsUser, withSpan("wait", EXEC_LOCK_SPAN)])?.name, "pypi.org");
  assert.equal(runningStep([awaitsUser, withSpan("sandbox", "ensure")])?.name, "pypi.org");
  assert.equal(runningStep([withSpan("sandbox", "ensure"), withSpan("wait", EXEC_LOCK_SPAN)])?.name, EXEC_LOCK_SPAN);
});

test("the running command is the newest loading card's exec span", () => {
  const withSpans = (loading: boolean, ...kinds: string[]): ChatMessage => ({
    kind: "tool_call", tool: "exec", args: {}, detail: "", loading, runningSpans: kinds.map((kind, i) => ({ spanId: `${kind}${i}`, kind, name: kind, startedAt: i })),
  });
  assert.equal(runningExec([withSpans(true, "tool", "exec"), withSpans(true, "tool")])?.spanId, "exec1");
  assert.equal(runningExec([withSpans(false, "tool", "exec")]), null);
  assert.equal(runningExec([card("call_0")]), null);
});
