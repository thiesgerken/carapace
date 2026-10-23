import assert from "node:assert/strict";
import test from "node:test";

import type { ChatMessage } from "@/lib/types";
import { groupRenderItems } from "./tool-call-group";

function tool(tool: string, path: string): ChatMessage {
  return { kind: "tool_call", tool, args: { path }, detail: "" };
}

test("sent files split completed and active tool groups rather than disappearing inside them", () => {
  const messages: ChatMessage[] = [
    { kind: "thinking", content: "Preparing files" },
    tool("write", "/workspace/artifacts/report/index.html"),
    tool("send_file", "/workspace/artifacts/report/index.html"),
    tool("send_file", "/workspace/chart.png"),
    tool("send_file", "/workspace/data.csv"),
    tool("exec", "/workspace"),
    { kind: "thinking_streaming", content: "Checking results" },
  ];
  assert.deepEqual(groupRenderItems(messages), [
    { type: "group", start: 0, indices: [0, 1], inProgress: false },
    { type: "message", index: 2 },
    { type: "message", index: 3 },
    { type: "message", index: 4 },
    { type: "group", start: 5, indices: [5, 6], inProgress: true },
  ]);
});
