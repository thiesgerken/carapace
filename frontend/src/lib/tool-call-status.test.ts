import assert from "node:assert/strict";
import test from "node:test";

import type { ChatMessage, SpanUpdate } from "@/lib/types";

import { applySpanToToolCall, toolCallStatus } from "./tool-call-status";

const card = (toolCallId: string): ChatMessage => ({ kind: "tool_call", tool: "exec", args: {}, detail: "", loading: true, toolCallId });
const span = (span_id: string, kind: string, status: SpanUpdate["status"], tool_call_id: string | null = "call_0"): SpanUpdate => ({
  type: "span", turn_id: "t1", span_id, kind, name: kind === "domain" ? "pypi.org" : kind, status, tool_call_id,
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
  assert.deepEqual(toolCallStatus(spansOf(messages, 1)), { spanId: "s3", kind: "domain", name: "pypi.org" });

  // Spans outside a tool call, or of a call without a card, change nothing.
  assert.equal(applySpanToToolCall(messages, span("s4", "sandbox", "running", null)), messages);
  assert.equal(applySpanToToolCall(messages, span("s4", "sandbox", "running", "call_9")), messages);
});

test("only steps a card names make its status, the innermost one first", () => {
  assert.equal(toolCallStatus([{ spanId: "a", kind: "tool", name: "exec" }, { spanId: "b", kind: "gate", name: "exec" }]), null);
  assert.equal(toolCallStatus([{ spanId: "a", kind: "sandbox", name: "ensure" }, { spanId: "b", kind: "exec", name: "exec" }])?.kind, "sandbox");
  assert.equal(toolCallStatus(undefined), null);
});
