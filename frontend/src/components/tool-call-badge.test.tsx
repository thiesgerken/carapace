import assert from "node:assert/strict";
import test from "node:test";
import { NextIntlClientProvider } from "next-intl";

import messages from "../../messages/en.json";
import { installDom, renderReact } from "../../test/react-test-utils";

import { parseStreamingArgs } from "@/lib/live-tool-calls";

import { ToolCallBadge } from "./tool-call-badge";

test("a streaming call shows its args growing, then becomes the final card in place", async () => {
  const restore = installDom();
  try {
    const card = (props: Partial<Parameters<typeof ToolCallBadge>[0]>) => (
      <NextIntlClientProvider locale="en" messages={messages}>
        <ToolCallBadge tool="write" args={{}} detail="" {...props} />
      </NextIntlClientProvider>
    );
    const argsText = '{"path": "notes.md", "content": "# Plan\\n- one';
    const view = await renderReact(card({ args: { path: "notes.md", content: "# Plan\n- one" }, argsText, argsStreaming: true, loading: true }));
    const row = view.container.firstElementChild;
    assert.equal(view.container.querySelector("pre")?.textContent, "# Plan\n- one", "file content with real line breaks");
    assert.match(view.container.textContent ?? "", /notes\.md/);

    await view.rerender(card({ args: { path: "notes.md", content: "# Plan\n- one\n- two" }, approvalSource: "sentinel", loading: true }));
    assert.equal(view.container.firstElementChild, row, "the same card, not a new one");
    assert.equal(view.container.querySelector("pre"), null, "the preview goes once the args are complete");

    await view.rerender(card({ args: { command: "rm -rf /tmp/x" }, tool: "exec", argsText: '{"command": "rm -rf /tmp/x"}', notRun: true }));
    assert.match(view.container.textContent ?? "", /not run/);
    await view.unmount();
  } finally {
    restore();
  }
});

test("a loading card names the step it waits for, and drops it once done", async () => {
  const restore = installDom();
  try {
    const card = (props: Partial<Parameters<typeof ToolCallBadge>[0]>) => (
      <NextIntlClientProvider locale="en" messages={messages} timeZone="UTC">
        <ToolCallBadge tool="exec" args={{ command: "pip install rich" }} detail="" {...props} />
      </NextIntlClientProvider>
    );
    const exec = { spanId: "e", kind: "exec", name: "exec" };
    const view = await renderReact(card({ loading: true, runningSpans: [exec, { spanId: "d", kind: "domain", name: "pypi.org" }] }));
    const status = () => view.container.querySelector('[role="status"]')?.textContent ?? null;
    assert.equal(status(), "Checking domain pypi.org…");

    await view.rerender(card({ loading: true, runningSpans: [exec, { spanId: "w", kind: "wait", name: "pypi.org" }] }));
    assert.equal(status(), "Waiting for approval…");
    await view.rerender(card({ loading: true, runningSpans: [exec] }));
    assert.equal(status(), null, "the exec itself is the card's spinner");
    await view.rerender(card({ loading: false, runningSpans: [{ spanId: "s", kind: "sentinel", name: "tool_call" }] }));
    assert.equal(status(), null, "a finished card shows no step");
    await view.unmount();
  } finally {
    restore();
  }
});

test("the card being written shows its request's time and approximate tokens in the header", async () => {
  const restore = installDom();
  try {
    const startedAt = new Date(Date.now() - 30_500).toISOString();
    const view = await renderReact(
      <NextIntlClientProvider locale="en" messages={messages} timeZone="UTC">
        <ToolCallBadge
          tool="exec"
          args={{}}
          detail=""
          loading
          argsText=""
          argsStreaming
          streamingActivity={{ request_id: "r1", source: "agent", phase: "tool_call", tool_name: "exec", started_at: startedAt, streamed_chars: 5_200 }}
        />
      </NextIntlClientProvider>,
    );
    assert.match(view.container.querySelector("button")?.textContent ?? "", /30 s · 1\.3k tokens/);
    await view.unmount();
  } finally {
    restore();
  }
});

test("a multi-line command shows only its first line in the row, a one-line command all of it", async () => {
  const restore = installDom();
  try {
    const row = async (command: string) => {
      const view = await renderReact(
        <NextIntlClientProvider locale="en" messages={messages}>
          <ToolCallBadge tool="exec" args={{ command }} detail="" result="4.2" />
        </NextIntlClientProvider>,
      );
      const summary = view.container.querySelector("button span.font-mono")?.textContent;
      await view.unmount();
      return summary;
    };
    assert.equal(await row("cat > stats.py <<'EOF'\nimport statistics\nEOF\npython3 stats.py"), "cat > stats.py <<'EOF' …");
    assert.equal(await row("ls -la /workspace"), "ls -la /workspace");
  } finally {
    restore();
  }
});

test("a streaming exec shows its title once the model finished it, the command's first line until then", async () => {
  const restore = installDom();
  try {
    const card = (argsText: string, argsStreaming = true) => (
      <NextIntlClientProvider locale="en" messages={messages}>
        <ToolCallBadge tool="exec" args={parseStreamingArgs(argsText)!} argsText={argsText} argsStreaming={argsStreaming} detail="" loading />
      </NextIntlClientProvider>
    );
    const summary = () => view.container.querySelector("button span.font-mono")?.textContent ?? null;
    const view = await renderReact(card('{"title": "Average the rat'));
    assert.equal(summary(), null, "nothing half-written, and no missing-command fallback");
    await view.rerender(card('{"command": "cat > stats.py <<\'EOF\'\\nimport stat'));
    assert.equal(summary(), "cat > stats.py <<'EOF' …", "an untitled call shows its command's first line");
    await view.rerender(card('{"title": "Average the ratings", "contexts": [], "command": "cat > stats.py <<\'EOF\'\\nimport stat'));
    assert.equal(summary(), "Average the ratings");
    // The final card shows the same, so nothing jumps.
    await view.rerender(card('{"title": "Average the ratings", "contexts": [], "command": "cat > stats.py <<\'EOF\'\\nEOF"}', false));
    assert.equal(summary(), "Average the ratings");
    await view.unmount();
  } finally {
    restore();
  }
});
