import assert from "node:assert/strict";
import test from "node:test";
import { createTranslator } from "next-intl";
import { renderToStaticMarkup } from "react-dom/server";

import english from "../../messages/en.json";
import {
  SandboxHeaderStatus,
  appendEscalationCard,
  catchUpFromHistory,
  countSubmittedUserMessages,
  isTurnActionMessage,
  isUnattendedInputLocked,
  nextUnattendedInputLockBaseline,
  projectHistoryToMessages,
} from "./chat-view";
import { turnTimelineHref } from "./message";
import type { ChatMessage, HistoryMessage } from "@/lib/types";

test("countSubmittedUserMessages ignores slash commands", () => {
  assert.equal(
    countSubmittedUserMessages([
      { kind: "user", content: "/help" },
      { kind: "user", content: "build status" },
      { kind: "assistant", content: "ok" },
    ]),
    1,
  );
});

test("unattended toggle in an existing session waits for the next user message", () => {
  const baseline = nextUnattendedInputLockBaseline({
    previousSessionId: "session-1",
    sessionId: "session-1",
    previousUnattended: false,
    sessionUnattended: true,
    previousBaseline: null,
    submittedUserMessageCount: 2,
  });

  assert.equal(baseline, 2);
  assert.equal(isUnattendedInputLocked(true, 2, baseline), false);
  assert.equal(isUnattendedInputLocked(true, 3, baseline), true);
});

test("existing unattended sessions still lock after a submitted message already exists", () => {
  const baseline = nextUnattendedInputLockBaseline({
    previousSessionId: "session-1",
    sessionId: "session-2",
    previousUnattended: false,
    sessionUnattended: true,
    previousBaseline: null,
    submittedUserMessageCount: 4,
  });

  assert.equal(baseline, 0);
  assert.equal(isUnattendedInputLocked(true, 4, baseline), true);
});

test("user-approved tool call survives reload when the server rewrote the escalated event in place", () => {
  const args = { command: "git push" };
  const messages = projectHistoryToMessages([
    {
      role: "tool_call",
      content: "",
      tool: "exec",
      args,
      detail: "[user approved]",
      approval_source: "user",
      approval_verdict: "allow",
      tool_id: "tool-1",
    },
    { role: "approval_request", content: "", tool_call_id: "call-1", tool: "exec", args },
    { role: "approval_response", content: "", tool_call_id: "call-1", decision: "approved" },
    { role: "tool_result", content: "", tool: "exec", tool_id: "tool-1", result: "ok" },
  ]);

  assert.equal(messages.length, 1);
  const [toolCall] = messages;
  assert.equal(toolCall.kind, "tool_call");
  assert.equal(toolCall.approvalSource, "user");
  assert.equal(toolCall.approvalVerdict, "allow");
  assert.equal(toolCall.result, "ok");
});

test("a failed turn's persisted error renders as a turn-terminal error after reload", () => {
  const messages = projectHistoryToMessages([
    { role: "user", content: "go on", event_index: 0 },
    { role: "error", content: "Session budget reached: cost $1.0525 / $1.0000.", event_index: 1 },
  ]);

  assert.equal(messages.length, 2);
  const [, error] = messages;
  assert.deepEqual(error, {
    kind: "error",
    detail: "Session budget reached: cost $1.0525 / $1.0000.",
    eventIndex: 1,
    compaction: undefined,
    turnTerminal: true,
    turnId: undefined,
    traceback: undefined,
  });
});

test("an unexpected error keeps its traceback after reload", () => {
  const [error] = projectHistoryToMessages([
    {
      role: "error",
      content: "The turn stopped on an unexpected error: InvalidURL: too long",
      traceback: "Traceback …",
      event_index: 0,
    },
  ]);
  assert.equal(error.kind === "error" && error.traceback, "Traceback …");
});

test("turn-ending errors carry turn actions, other errors do not", () => {
  assert.equal(isTurnActionMessage({ kind: "error", detail: "budget", eventIndex: 1, turnTerminal: true }), true);
  assert.equal(isTurnActionMessage({ kind: "error", detail: "Agent is busy" }), false);
});

test("a provider compaction event renders as a marker with the provider's summary or its failure", () => {
  const messages = projectHistoryToMessages([
    { role: "user", content: "go", event_index: 0 },
    { role: "compaction", content: "", provider: "anthropic", summary: "the user asked to go", event_index: 1 },
    { role: "compaction", content: "", provider: "openai", event_index: 2 },
    { role: "compaction", content: "", provider: "openai-codex", failed: "did not compact; compacting locally instead", event_index: 3 },
    { role: "compaction", content: "", provider: "openai-codex", failed: "rejected compaction: Unknown parameter", rejected: true, event_index: 4 },
  ]);

  assert.deepEqual(messages.slice(1), [
    { kind: "provider_compaction", provider: "anthropic", summary: "the user asked to go", failed: undefined, rejected: undefined },
    { kind: "provider_compaction", provider: "openai", summary: undefined, failed: undefined, rejected: undefined },
    { kind: "provider_compaction", provider: "openai-codex", summary: undefined, failed: "did not compact; compacting locally instead", rejected: undefined },
    { kind: "provider_compaction", provider: "openai-codex", summary: undefined, failed: "rejected compaction: Unknown parameter", rejected: true },
  ]);
});

test("appendEscalationCard skips a request that history already shows", () => {
  const request = {
    type: "approval_request" as const,
    tool_call_id: "call-1",
    tool: "exec",
    args: {},
    explanation: "",
  };
  const once = appendEscalationCard([], { kind: "approval", request });
  assert.equal(once.length, 1);
  assert.equal(appendEscalationCard(once, { kind: "approval", request }), once);
  assert.equal(
    appendEscalationCard(once, { kind: "approval", request: { ...request, tool_call_id: "call-2" } }).length,
    2,
  );
});

test("a failed turn's error carries its turn id, like a successful turn's last bubble", () => {
  const [, error] = projectHistoryToMessages([
    { role: "user", content: "go on", event_index: 0, turn_id: "9c1e0a7f" },
    { role: "error", content: "The previous turn was interrupted before completion.", event_index: 1, turn_id: "9c1e0a7f" },
  ]);
  assert.equal(error.kind === "error" ? error.turnId : null, "9c1e0a7f");
});

test("only the bubble that ended a turn carries its turn id", () => {
  const messages = projectHistoryToMessages([
    { role: "user", content: "check the backups", event_index: 0, turn_id: "9c1e0a7f" },
    { role: "assistant", content: "Looking.", event_index: 1, partial: true },
    { role: "assistant", content: "All fine.", event_index: 2, turn_id: "9c1e0a7f" },
  ]);
  assert.deepEqual(messages.map((message) => (message.kind === "assistant" ? message.turnId : null)), [null, undefined, "9c1e0a7f"]);
});

test("the debug link opens the timeline tab on the turn", () => {
  assert.equal(turnTimelineHref("s 1", "9c1e0a7f"), "/?session=s%201&view=debug&tab=timeline&turn=9c1e0a7f");
});

test("the header's sandbox status shows liveness with details as tooltip, and nothing without a sandbox", () => {
  const t = createTranslator({ locale: "en", messages: english, namespace: "chatView" }) as never;
  const running = renderToStaticMarkup(
    <SandboxHeaderStatus
      sandbox={{ exists: true, status: "running", storage_present: true, sandbox_id: "sbx-1", last_measured_used_bytes: 5 * 1024 * 1024 }}
      t={t}
    />,
  );
  assert.match(running, /title="Running\n5\.0 MB used\nSandbox ID: sbx-1"/);
  assert.match(running, /bg-success/);
  assert.match(running, />Running<\/span>$/);

  assert.equal(renderToStaticMarkup(<SandboxHeaderStatus sandbox={{ exists: false, status: "missing", storage_present: false }} t={t} />), "");
  assert.equal(renderToStaticMarkup(<SandboxHeaderStatus sandbox={null} t={t} />), "");
});

test("after a reconnect the chat catches up from the history on a result the socket missed", () => {
  // The disconnect stopped the spinner; the result was broadcast while the socket was down.
  const live: ChatMessage[] = [
    { kind: "user", content: "read the weather skill" },
    { kind: "tool_call", tool: "read_skill", args: { skill_name: "weather" }, detail: "", loading: false, toolId: "tool-1" },
  ];
  const history: HistoryMessage[] = [
    { role: "user", content: "read the weather skill" },
    { role: "tool_call", content: "", tool: "read_skill", args: { skill_name: "weather" }, detail: "", tool_id: "tool-1", model_tool_call_id: "call_1" },
    { role: "tool_result", content: "", tool: "read_skill", tool_id: "tool-1", result: "# weather\n\nThe commands are on PATH." },
    { role: "tool_call", content: "", tool: "exec", args: { command: "weather" }, detail: "", tool_id: "tool-2", model_tool_call_id: "call_2" },
  ];
  const span = {
    type: "span", turn_id: "t1", span_id: "s1", kind: "sandbox", name: "ensure", status: "running",
    started_at: "2026-11-27T12:00:00Z", tool_call_id: "call_2", replayed: true,
  } as const;

  const [, skill, exec] = catchUpFromHistory(live, history, [span]);
  assert.equal(skill.kind === "tool_call" && skill.result, "# weather\n\nThe commands are on PATH.");
  assert.equal(skill.kind === "tool_call" && skill.loading, false);
  // The call that still runs spins again with its replayed step.
  assert.equal(exec.kind === "tool_call" && exec.loading, true);
  assert.equal(exec.kind === "tool_call" && exec.runningSpans?.[0]?.name, "ensure");
});
