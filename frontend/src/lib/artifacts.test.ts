import assert from "node:assert/strict";
import test from "node:test";

import type { ChatMessage } from "@/lib/types";
import { artifactReferences } from "./artifacts";

function show(slug: string, exitCode?: number): ChatMessage {
  return { kind: "tool_call", tool: "show_artifact", args: { slug }, detail: "", exitCode };
}

test("the first successful reference to a slug is the card, later ones are updates sharing the slug's revision", () => {
  const messages: ChatMessage[] = [
    show("report", 1),
    show("report", 0),
    { kind: "tool_call", tool: "send_file", args: { path: "/workspace/artifacts/report/index.html" }, detail: "", exitCode: 0 },
    show("dashboard", 0),
    show("report"),
    show("report", 0),
  ];
  assert.deepEqual([...artifactReferences(messages)], [
    [1, { slug: "report", update: false, revision: 2 }],
    [3, { slug: "dashboard", update: false, revision: 1 }],
    [5, { slug: "report", update: true, revision: 2 }],
  ]);
});
