import assert from "node:assert/strict";
import test from "node:test";

import { appendStreamedArgs, completeStreamedCall, dropOpenCalls, endStreamedCall, keepUnrunCalls, markUnrunCalls, parseStreamingArgs, replaceStreamedCall, startStreamedCall, streamingCallIndex } from "./live-tool-calls";
import type { ChatMessage, LlmActivity } from "./types";

test("streamed args parse as far as they go; malformed JSON keeps what the card had", () => {
  assert.deepEqual(parseStreamingArgs(""), {});
  assert.deepEqual(parseStreamingArgs('{"comm'), {});
  assert.deepEqual(parseStreamingArgs('{"path": "a.md", "content": "# Title\\nfirst li'), { path: "a.md", content: "# Title\nfirst li" });
  assert.equal(parseStreamingArgs("nonsense"), null);
  assert.equal(parseStreamingArgs("[1, 2"), null);

  let messages = startStreamedCall([], "c1", "exec");
  messages = appendStreamedArgs(messages, "c1", '{"command": "ls');
  messages = appendStreamedArgs(messages, "c1", '"}}');
  assert.deepEqual(messages[0], { kind: "tool_call", tool: "exec", args: { command: "ls" }, detail: "", loading: true, toolCallId: "c1", argsText: '{"command": "ls"}}', argsStreaming: true });
});

test("parallel calls each fill their own card, and each final call replaces its card in place", () => {
  let messages: ChatMessage[] = [{ kind: "user", content: "go" }];
  messages = startStreamedCall(messages, "a", "exec");
  messages = startStreamedCall(messages, "b", "write");
  messages = appendStreamedArgs(messages, "b", '{"path": "x"');
  messages = appendStreamedArgs(messages, "a", '{"command": "pwd"}');
  messages = endStreamedCall(messages, "a", false);
  assert.deepEqual(messages.map((m) => m.kind === "tool_call" && [m.args, m.argsStreaming, m.loading]), [false, [{ command: "pwd" }, false, true], [{ path: "x" }, true, true]]);

  const final: ChatMessage = { kind: "tool_call", tool: "exec", args: { command: "pwd" }, detail: "", toolId: "t-a", toolCallId: "a" };
  messages = replaceStreamedCall(messages, "a", final)!;
  assert.equal(messages[1], final);
  assert.equal(messages.length, 3);
  // A final card is no longer open: the next call is placed by its tool_id, not by the provider id.
  assert.equal(replaceStreamedCall(messages, "a", final), null);
  assert.equal(replaceStreamedCall(messages, null, final), null);
});

test("a call aborted mid-args, or never run by turn end, stays visible as not run", () => {
  let messages = startStreamedCall([], "a", "exec");
  messages = startStreamedCall(messages, "b", "exec");
  messages = endStreamedCall(messages, "a", true);
  messages = endStreamedCall(messages, "b", false);
  assert.deepEqual(messages.map((m) => m.kind === "tool_call" && [m.notRun, m.loading]), [[true, false], [undefined, true]]);

  messages = markUnrunCalls(messages);
  assert.deepEqual(messages.map((m) => m.kind === "tool_call" && [m.notRun, m.loading, m.argsStreaming]), [[true, false, false], [true, false, false]]);
  const settled = markUnrunCalls(messages);
  assert.equal(settled, messages, "nothing left to settle");
});

test("a provider reusing an id across responses reaches only the open card", () => {
  let messages = startStreamedCall([], "call_0", "exec");
  messages = endStreamedCall(messages, "call_0", true);
  messages = startStreamedCall(messages, "call_0", "read");
  messages = appendStreamedArgs(messages, "call_0", '{"path": "a"}');
  assert.deepEqual(messages.map((m) => m.kind === "tool_call" && m.args), [{}, { path: "a" }]);
});

test("a result completes a streamed call that sent no tool_call of its own", () => {
  let messages = startStreamedCall([], "s", "list_skills");
  messages = appendStreamedArgs(messages, "s", "{}");
  messages = endStreamedCall(messages, "s", false);
  messages = completeStreamedCall(messages, "s", { result: "pancakes: recipes", exitCode: 0, toolId: "t-s", files: undefined })!;
  assert.deepEqual(messages, [{ kind: "tool_call", tool: "list_skills", args: {}, detail: "", loading: false, toolCallId: "s", argsText: undefined, argsStreaming: undefined, result: "pancakes: recipes", exitCode: 0, toolId: "t-s", files: undefined }]);
  assert.equal(markUnrunCalls(messages), messages, "done, so the turn end leaves it alone");
  assert.equal(completeStreamedCall(messages, "s", { result: "again" }), null);
});

test("a repeated start opens a new card; the earlier open one under that id was not run", () => {
  let messages = startStreamedCall([], "call_0", "write");
  messages = endStreamedCall(messages, "call_0", false);
  messages = startStreamedCall(messages, "call_0", "exec");
  messages = appendStreamedArgs(messages, "call_0", '{"command": "ls"}');
  assert.deepEqual(messages.map((m) => m.kind === "tool_call" && [m.tool, m.notRun, m.loading, m.args]), [["write", true, false, {}], ["exec", undefined, true, { command: "ls" }]]);
});

test("not-run cards outlive the re-render from saved history, before what followed them", () => {
  const user = (content: string): ChatMessage => ({ kind: "user", content });
  const saved = (toolId: string): ChatMessage => ({ kind: "tool_call", tool: "exec", args: {}, detail: "", toolId });
  const notRun = (toolCallId: string): ChatMessage => ({ kind: "tool_call", tool: "exec", args: {}, detail: "", toolCallId, argsText: "{}", notRun: true });
  const thinking: ChatMessage = { kind: "thinking", content: "…" };
  const text = (content: string): ChatMessage => ({ kind: "assistant", content, partial: true });
  const error: ChatMessage = { kind: "error", detail: "Cancelled by user.", turnTerminal: true };
  // Turn one: a call rejected mid-turn, narration after a saved call, then a cancel mid-write.
  // Turn two: a call whose final tool_call never came, after the answer.
  const live = [user("one"), thinking, notRun("rejected"), saved("a"), text("next"), notRun("x"), notRun("y"), error, user("two"), saved("b"), text("answer"), notRun("late")];
  // The saved history has fresh objects, never the not-run cards.
  const projected = [user("one"), thinking, saved("a"), text("next"), error, user("two"), saved("b"), text("answer")];
  const kept = keepUnrunCalls(live, projected);
  const label = (m: ChatMessage) => (m.kind === "tool_call" ? m.toolId ?? m.toolCallId : m.kind === "assistant" ? m.content : m.kind);
  assert.deepEqual(kept.map(label), ["user", "thinking", "rejected", "a", "next", "error", "x", "y", "user", "b", "answer", "late"]);
  assert.equal(keepUnrunCalls([user("one"), saved("a")], projected), projected);
});

test("a dropped socket drops the cards still streaming: the call comes back as one tool_call", () => {
  let messages = startStreamedCall([{ kind: "user", content: "go" }], "c", "exec");
  messages = appendStreamedArgs(messages, "c", '{"command": "make"}');
  const done: ChatMessage = { kind: "tool_call", tool: "exec", args: {}, detail: "", toolId: "t-d", toolCallId: "d", notRun: true };
  messages = dropOpenCalls([...messages, done]);
  assert.deepEqual(messages.map((m) => m.kind), ["user", "tool_call"], "a not-run card stays; only open ones go");
  // After the reconnect the server sends the call itself; there is no card to replace, so it is placed once.
  const final: ChatMessage = { kind: "tool_call", tool: "exec", args: { command: "make" }, detail: "", toolId: "t-c", toolCallId: "c" };
  assert.equal(replaceStreamedCall(messages, "c", final), null);
  assert.equal(markUnrunCalls(messages), messages, "nothing left for the turn end to mark");
});

test("the request's counter goes on the newest card still being written", () => {
  const writing: LlmActivity = { request_id: "r1", source: "agent", phase: "tool_call", tool_name: "exec", started_at: "2026-01-01T00:00:00Z" };
  let messages: ChatMessage[] = [{ kind: "user", content: "go" }];
  assert.equal(streamingCallIndex(messages, writing), -1);
  messages = startStreamedCall(messages, "a", "exec");
  messages = startStreamedCall(messages, "b", "exec");
  assert.equal(streamingCallIndex(messages, writing), 2);
  messages = endStreamedCall(messages, "b", false);
  assert.equal(streamingCallIndex(messages, writing), 1);
  messages = endStreamedCall(messages, "a", false);
  assert.equal(streamingCallIndex(messages, writing), -1);
  // Other phases, and other roles' requests, have no card.
  messages = startStreamedCall(messages, "c", "exec");
  assert.equal(streamingCallIndex(messages, { ...writing, phase: "generating" }), -1);
  assert.equal(streamingCallIndex(messages, { ...writing, source: "sentinel" }), -1);
  assert.equal(streamingCallIndex(messages, null), -1);
});
