import assert from "node:assert/strict";
import test from "node:test";

import { NextIntlClientProvider } from "next-intl";

import messages from "../../messages/en.json";
import { installDom, renderReact } from "../../test/react-test-utils";
import type { ChatMessage } from "@/lib/types";
import { ToolCallGroup, groupRenderItems } from "./tool-call-group";

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

test("a group's summary counts calls that never ran apart from the ones that did", async () => {
  const restore = installDom();
  try {
    const items: ChatMessage[] = [tool("exec", "/workspace"), { kind: "tool_call", tool: "exec", args: {}, detail: "", notRun: true }, tool("write", "/workspace/a.md")];
    const view = await renderReact(
      <NextIntlClientProvider locale="en" messages={messages}>
        <ToolCallGroup items={items} inProgress={false}>{null}</ToolCallGroup>
      </NextIntlClientProvider>,
    );
    assert.equal(view.container.textContent, "Ran 1 command, wrote 1 file, 1 not run");
    await view.unmount();
  } finally {
    restore();
  }
});
