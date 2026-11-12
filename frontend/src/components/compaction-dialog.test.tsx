import assert from "node:assert/strict";
import test from "node:test";
import { NextIntlClientProvider } from "next-intl";

import messages from "../../messages/en.json";
import { click, installDom, renderReact, runInAct, setInputValue } from "../../test/react-test-utils";

import { CompactionDialog } from "./compaction-dialog";

const SERVER = "https://carapace.example.test";

const PREVIEW = {
  context_tokens: 150_000,
  threshold_tokens: 120_000,
  context_window_tokens: 200_000,
  thinking_dropped: 2,
  turns_folded: 5,
  fold_tokens: 80_000,
  tool_outputs: [{ tool_name: "exec", tokens: 12_000 }],
  estimated_tokens_without_summaries: 40_000,
};

test("the dialog shows the dry run and sends the trimmed focus", async () => {
  const restore = installDom();
  const originalFetch = globalThis.fetch;
  // jsdom has no <dialog> modality.
  window.HTMLDialogElement.prototype.showModal = function showModal(this: HTMLDialogElement) {
    this.open = true;
  };
  window.HTMLDialogElement.prototype.close = function close(this: HTMLDialogElement) {
    this.open = false;
  };
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    assert.equal(new URL(String(input)).pathname, "/api/sessions/s1/compaction/preview");
    return new Response(JSON.stringify(PREVIEW), { headers: { "Content-Type": "application/json" } });
  }) as typeof fetch;
  const compacted: string[] = [];

  try {
    const view = await renderReact(
      <NextIntlClientProvider locale="en" messages={messages} timeZone="UTC">
        <CompactionDialog server={SERVER} token="" sessionId="s1" onClose={() => {}} onCompact={(focus) => compacted.push(focus)} onUncompact={() => {}} />
      </NextIntlClientProvider>,
    );
    await runInAct(() => new Promise((resolve) => setTimeout(resolve, 0)));
    const text = view.container.textContent ?? "";

    assert.match(text, /drop 2 thinking parts/);
    assert.match(text, /fold 5 turns \(80K tokens\) into the summary/);
    assert.match(text, /summarize one exec output \(12K tokens\)/);
    assert.match(text, /About 40K tokens afterwards/);

    const input = view.container.querySelector("input")!;
    await setInputValue(input, "  the migration  ");
    const run = Array.from(view.container.querySelectorAll("button")).find((button) => button.textContent?.trim() === "Compact");
    await click(run!);

    assert.deepEqual(compacted, ["the migration"]);
    await view.unmount();
  } finally {
    globalThis.fetch = originalFetch;
    restore();
  }
});
