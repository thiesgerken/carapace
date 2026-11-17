import assert from "node:assert/strict";
import test from "node:test";
import { NextIntlClientProvider } from "next-intl";

import messages from "../../messages/en.json";
import { installDom, renderReact } from "../../test/react-test-utils";

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
