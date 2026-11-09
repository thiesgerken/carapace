import assert from "node:assert/strict";
import test from "node:test";
import { NextIntlClientProvider } from "next-intl";

import messages from "../../messages/en.json";
import { click, installDom, renderReact, runInAct } from "../../test/react-test-utils";
import type { DebugRole, LlmContext } from "@/lib/types";

import { DebugView } from "./debug-view";

const SERVER = "https://carapace.example.test";

class FakeWebSocket {
  static readonly OPEN = 1;
  static instances: FakeWebSocket[] = [];
  readyState = 0;
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;

  constructor(readonly url: string) {
    FakeWebSocket.instances.push(this);
  }

  close(): void {}
}

function context(overrides: Partial<LlmContext>): LlmContext {
  return {
    request_id: "r1",
    role: "agent",
    compaction_target: null,
    model_name: "anthropic:sonnet",
    status: "running",
    started_at: "2026-11-09T12:00:00Z",
    completed_at: null,
    instructions: [{ content: "You are carapace.", dynamic: false, name: null }],
    messages: [{ kind: "request", parts: [{ part_kind: "user-prompt", content: "Check the backups" }] }],
    tool_definitions: [{ name: "exec", description: "Run a command", parameters_json_schema: { type: "object" } }],
    response: null,
    error: null,
    ...overrides,
  };
}

test("the debug view shows each role's latest context and refetches on WebSocket notifications", async () => {
  const restore = installDom();
  const originalFetch = globalThis.fetch;
  const originalWebSocket = globalThis.WebSocket;
  globalThis.WebSocket = FakeWebSocket as unknown as typeof WebSocket;
  const contexts: Record<DebugRole, LlmContext | null> = {
    agent: context({}),
    sentinel: context({ role: "sentinel", status: "failed", error: "Automatic sentinel review timed out after 600s." }),
    titler: null,
    compaction: null,
  };
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    const url = new URL(String(input));
    if (url.pathname === "/api/auth/ws-ticket") return Response.json({ ticket: "ticket-1" });
    const role = url.pathname.match(/^\/api\/sessions\/s1\/llm-contexts\/(\w+)$/)?.[1] as DebugRole | undefined;
    assert.ok(role, `unexpected request ${url.pathname}`);
    return Response.json(contexts[role]);
  }) as typeof fetch;

  try {
    const view = await renderReact(
      <NextIntlClientProvider locale="en" messages={messages} timeZone="UTC">
        <DebugView server={SERVER} token="" sessionId="s1" />
      </NextIntlClientProvider>,
    );
    const settle = () => runInAct(() => new Promise((resolve) => setTimeout(resolve, 0)));
    const text = () => view.container.textContent ?? "";
    await settle();
    await settle();

    assert.match(text(), /Running/);
    assert.match(text(), /Check the backups/);
    assert.match(text(), /Waiting for the response/);

    contexts.agent = context({
      status: "completed",
      response: {
        kind: "response",
        parts: [{ part_kind: "tool-call", tool_name: "exec", args: '{"command": "ls /backups"}', tool_call_id: "call-1" }],
        usage: { input_tokens: 12345, output_tokens: 20 },
        provider_details: { cost: 0.01 },
      },
    });
    const socket = FakeWebSocket.instances.at(-1);
    assert.ok(socket);
    await runInAct(() => socket.onmessage?.({ data: JSON.stringify({ type: "llm_context", role: "agent", request_id: "r1", status: "completed" }) }));
    await settle();

    assert.match(text(), /Completed/);
    assert.match(text(), /12,345/);
    assert.match(text(), /Tool call · exec/);
    assert.match(text(), /"command": "ls \/backups"/);

    const rawToggles = Array.from(view.container.querySelectorAll("button[aria-pressed]"));
    await click(rawToggles.at(-1)!);
    assert.match(text(), /"provider_details"/);

    const pill = (label: string) => Array.from(view.container.querySelectorAll('[role="radio"]')).find((element) => element.textContent === label)!;
    await click(pill("Sentinel"));
    await settle();
    assert.match(text(), /Failed/);
    assert.match(text(), /timed out after 600s/);

    await click(pill("Titler"));
    await settle();
    assert.match(text(), /has not sent a request/);

    await view.unmount();
  } finally {
    globalThis.fetch = originalFetch;
    globalThis.WebSocket = originalWebSocket;
    restore();
  }
});
