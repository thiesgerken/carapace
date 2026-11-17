import assert from "node:assert/strict";
import test from "node:test";

import { appendStreamedArgs, completeStreamedCall, endStreamedCall, markUnrunCalls, parseStreamingArgs, replaceStreamedCall, startStreamedCall } from "./live-tool-calls";
import type { ChatMessage } from "./types";

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
