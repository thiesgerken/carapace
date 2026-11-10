import assert from "node:assert/strict";
import test from "node:test";
import { NextIntlClientProvider } from "next-intl";

import messages from "../../messages/en.json";
import { click, installDom, renderReact, runInAct } from "../../test/react-test-utils";
import type { DebugRole, LlmContext, LlmRequestRecord } from "@/lib/types";

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
    messages: [{ kind: "request", parts: [{ part_kind: "user-prompt", content: "Check the **backups**" }, { part_kind: "tool-return", tool_name: "exec", content: "**not** markdown", tool_call_id: "call-0" }] }],
    tool_definitions: [{ name: "exec", description: "Run a **shell** command", parameters_json_schema: { type: "object" } }],
    response: null,
    error: null,
    cost: null,
    ...overrides,
  };
}

function record(overrides: Partial<LlmRequestRecord>): LlmRequestRecord {
  return {
    ts: "2026-11-09T11:59:00Z",
    request_id: "r0",
    source: "agent",
    model_name: "anthropic:sonnet",
    outcome: "completed",
    input_tokens: 8000,
    output_tokens: 300,
    cache_read_tokens: null,
    cache_write_tokens: null,
    reasoning_tokens: null,
    cost: null,
    started_at: "2026-11-09T11:58:57Z",
    completed_at: "2026-11-09T11:59:00Z",
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
  const requests: LlmRequestRecord[] = [record({})];
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    const url = new URL(String(input));
    if (url.pathname === "/api/auth/ws-ticket") return Response.json({ ticket: "ticket-1" });
    if (url.pathname === "/api/sessions/s1/llm-requests") return Response.json(requests.filter((r) => r.source === url.searchParams.get("role")));
    const role = url.pathname.match(/^\/api\/sessions\/s1\/llm-contexts\/(\w+)$/)?.[1] as DebugRole | undefined;
    assert.ok(role, `unexpected request ${url.pathname}`);
    return Response.json(contexts[role]);
  }) as typeof fetch;

  try {
    const view = await renderReact(
      <NextIntlClientProvider locale="en" messages={messages} timeZone="UTC">
        <DebugView server={SERVER} token="" sessionId="s1" title="🥞 Pancakes" />
      </NextIntlClientProvider>,
    );
    const settle = () => runInAct(() => new Promise((resolve) => setTimeout(resolve, 0)));
    const text = () => view.container.textContent ?? "";
    // Shiki loads its highlighter asynchronously; the plain fallback renders first.
    const eventually = async (selector: string) => {
      for (let attempt = 0; attempt < 100 && !view.container.querySelector(selector); attempt++) {
        await runInAct(() => new Promise((resolve) => setTimeout(resolve, 20)));
      }
      assert.ok(view.container.querySelector(selector), `${selector} never rendered`);
    };
    await settle();
    await settle();

    assert.match(text(), /Running/);
    assert.match(text(), /Check the backups/);
    const bold = Array.from(view.container.querySelectorAll("strong"), (element) => element.textContent);
    assert.deepEqual(bold, ["shell", "backups"], "tool descriptions and prompts render as Markdown");
    assert.match(text(), /\*\*not\*\* markdown/);
    assert.match(text(), /Waiting for the response/);
    assert.doesNotMatch(text(), /Output tokens|Cost\$/);
    assert.match(text(), /Requests \(1\)/);
    const rows = () => Array.from(view.container.querySelectorAll("tbody tr"), (row) => Array.from(row.querySelectorAll("td"), (cell) => cell.textContent));
    // A record from before cache counts and costs were kept shows them as unknown.
    assert.deepEqual(rows(), [["11/9, 11:59:00 AM", "Completed", "8,000", "–", "–", "300", "–", "–", "–", "–", "3 s", "anthropic:sonnet"]]);
    assert.equal(view.container.querySelector('a[aria-current="page"]')?.getAttribute("href"), "/?session=s1&view=debug");

    contexts.agent = context({
      status: "completed",
      response: {
        kind: "response",
        parts: [{ part_kind: "tool-call", tool_name: "exec", args: '{"command": "ls /backups"}', tool_call_id: "call-1" }],
        usage: { input_tokens: 12345, output_tokens: 20, cache_read_tokens: 4000, cache_write_tokens: 0, input_audio_tokens: 0, details: { reasoning_tokens: 7 } },
        provider_details: { cost: 0.01 },
      },
      cost: { cost_usd: "0", equivalent_cost_usd: "0.0425", provider_cost_usd: "0.01" },
    });
    requests.push(
      record({
        ts: "2026-11-09T12:00:02Z",
        request_id: "r1",
        input_tokens: 12345,
        output_tokens: 20,
        cache_read_tokens: 4000,
        cache_write_tokens: 0,
        reasoning_tokens: 7,
        cost: { cost_usd: "0", equivalent_cost_usd: "0.0425", provider_cost_usd: "0.01" },
        started_at: "2026-11-09T12:00:00Z",
        completed_at: "2026-11-09T12:00:02.450Z",
      }),
    );
    const socket = FakeWebSocket.instances.at(-1);
    assert.ok(socket);
    assert.match(socket.url, /observe=true/);
    await runInAct(() => socket.onmessage?.({ data: JSON.stringify({ type: "llm_context", role: "agent", request_id: "r1", status: "completed" }) }));
    await settle();

    assert.match(text(), /Completed/);
    assert.deepEqual(rows()[0], ["11/9, 12:00:02 PM", "Completed", "12,345", "4,000", "0", "20", "7", "32%", "$0.00", "$0.043", "2.5 s", "anthropic:sonnet"]);
    assert.equal(rows().length, 2);
    assert.equal(view.container.querySelector("tbody a")?.getAttribute("href"), "#llm-context");
    assert.ok(view.container.querySelector("#llm-context"));
    assert.match(text(), /Input tokens12,345/);
    assert.match(text(), /Cache read4,000/);
    assert.match(text(), /reasoning_tokens7/);
    assert.doesNotMatch(text(), /Input audio/);
    assert.match(text(), /Cost\$0\.00 \(≈ \$0\.043 equivalent\)/);
    assert.match(text(), /Provider-reported\$0\.01/);
    assert.match(text(), /Tool call · exec/);
    assert.match(text(), /"command": "ls \/backups"/);
    await eventually('code[data-language="json"]');

    // A stopped turn saves the interrupted record only after the context's notification; the activity ending refetches.
    requests.push(record({ ts: "2026-11-09T12:00:09Z", request_id: "r2", outcome: "interrupted", input_tokens: 0, output_tokens: 0, completed_at: null }));
    await runInAct(() => socket.onmessage?.({ data: JSON.stringify({ type: "llm_activity", activity: null }) }));
    await settle();
    assert.equal(rows().length, 3);
    assert.equal(rows()[0][1], "Interrupted");

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
