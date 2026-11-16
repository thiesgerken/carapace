import assert from "node:assert/strict";
import test from "node:test";

import type { LlmPhases, Span } from "./types";
import { llmSegments, summarizeTurn, timelineRows } from "./turn-timeline";

const T0 = Date.parse("2026-11-16T12:00:00Z");
const at = (ms: number) => new Date(T0 + ms).toISOString();

function llm(overrides: Partial<LlmPhases>): LlmPhases {
  return {
    role: "agent",
    request_id: "r1",
    model_name: "anthropic:sonnet",
    first_token_at: null,
    first_thinking_at: null,
    last_thinking_at: null,
    first_text_at: null,
    input_tokens: 0,
    output_tokens: 0,
    cache_read_tokens: null,
    cache_write_tokens: null,
    cost: null,
    ...overrides,
  };
}

function span(span_id: string, parent_id: string | null, kind: string, start: number, end: number | null, extra: Partial<Span> = {}): Span {
  return { span_id, parent_id, kind, name: kind, started_at: at(start), ended_at: end === null ? null : at(end), status: end === null ? "running" : "ok", attrs: {}, llm: null, ...extra };
}

test("every instant of a turn goes to its deepest span, by category", () => {
  const spans = [
    span("turn", null, "turn", 0, 10_000),
    span("prepare", "turn", "turn.prepare", 0, 500),
    span("llm1", "turn", "llm", 500, 4500, { llm: llm({ first_token_at: at(1500), first_thinking_at: at(1500), last_thinking_at: at(2500), first_text_at: at(2500) }) }),
    span("tool", "turn", "tool", 4500, 9000),
    span("gate", "tool", "gate", 4500, 5500),
    span("llm2", "gate", "llm", 4600, 5400, { llm: llm({ role: "sentinel" }) }),
    span("wait", "tool", "wait", 5500, 7000, { attrs: { reason: "approval" } }),
    span("exec", "tool", "exec", 7000, 8500),
    span("domain", "exec", "domain", 7200, 7400),
  ];

  const summary = summarizeTurn(timelineRows(spans, T0 + 10_000), T0, T0 + 10_000);

  assert.deepEqual(summary.byCategory, {
    preparation: 500,
    llmWaiting: 1000,
    llmThinking: 1000,
    llmOutput: 2000,
    sentinel: 1200,
    sandbox: 0,
    skill: 0,
    execFile: 1300,
    credential: 0,
    compaction: 0,
    other: 500,
    notCovered: 1000,
    userWait: 1500,
  });
  assert.equal(summary.wallMs, 10_000);
  assert.equal(summary.userWaitMs, 1500);
  assert.equal(summary.systemMs, 8500);
});

test("compaction counts as compaction, its own LLM request included", () => {
  const spans = [
    span("turn", null, "turn", 0, 3000),
    span("compaction", "turn", "compaction", 0, 3000),
    span("llm", "compaction", "llm", 500, 2500, { llm: llm({ role: "compaction" }) }),
  ];
  assert.equal(summarizeTurn(timelineRows(spans, T0 + 3000), T0, T0 + 3000).byCategory.compaction, 3000);
});

test("overlapping siblings: the earliest started owns the overlap, and a wait wins over anything", () => {
  const spans = [
    span("turn", null, "turn", 0, 3000),
    span("sandbox", "turn", "sandbox", 0, 2000),
    span("skill", "turn", "skill", 1000, 3000),
    span("wait", "turn", "wait", 2500, 3000),
  ];
  const { byCategory } = summarizeTurn(timelineRows(spans, T0 + 3000), T0, T0 + 3000);
  assert.equal(byCategory.sandbox, 2000);
  assert.equal(byCategory.skill, 500);
  assert.equal(byCategory.userWait, 500);
});

test("parallel branches: the main path follows the earliest started branch, however deep the other one is", () => {
  const spans = [
    span("turn", null, "turn", 0, 3000),
    span("a", "turn", "tool", 0, 2000),
    span("a.gate", "a", "gate", 0, 2000),
    span("b", "turn", "tool", 500, 3000),
    span("b.exec", "b", "exec", 500, 3000),
    span("b.domain", "b.exec", "domain", 1000, 1500),
  ];
  const { byCategory } = summarizeTurn(timelineRows(spans, T0 + 3000), T0, T0 + 3000);
  // While A runs, B's deeper domain check doesn't take the time; once A ends, B's exec owns it.
  assert.equal(byCategory.sentinel, 2000);
  assert.equal(byCategory.execFile, 1000);
});

test("running spans grow to now, and spans run in tree order with their depth", () => {
  const spans = [span("exec", "tool", "exec", 200, null), span("tool", "turn", "tool", 100, null), span("turn", null, "turn", 0, null)];
  const rows = timelineRows(spans, T0 + 1000);
  assert.deepEqual(rows.map((row) => [row.span.span_id, row.depth, row.end - T0]), [["turn", 0, 1000], ["tool", 1, 1000], ["exec", 2, 1000]]);
  assert.equal(summarizeTurn(rows, T0, T0 + 1000).byCategory.execFile, 800);
});

test("LLM phases collapse when their timestamps are missing", () => {
  const phases = (overrides: Partial<LlmPhases>) => llmSegments(llm(overrides), T0, T0 + 1000).map((s) => [s.category, s.end - s.start]);
  assert.deepEqual(phases({}), [["llmWaiting", 1000]]);
  assert.deepEqual(phases({ first_text_at: at(400) }), [["llmWaiting", 400], ["llmOutput", 600]]);
  // Still thinking: thinking runs to the end.
  assert.deepEqual(phases({ first_token_at: at(100), first_thinking_at: at(100) }), [["llmWaiting", 100], ["llmThinking", 900]]);
  assert.deepEqual(phases({ first_token_at: at(100), first_thinking_at: at(100), last_thinking_at: at(700) }), [["llmWaiting", 100], ["llmThinking", 600], ["llmOutput", 300]]);
});
