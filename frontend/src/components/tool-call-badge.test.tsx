import assert from "node:assert/strict";
import test from "node:test";
import { NextIntlClientProvider } from "next-intl";

import messages from "../../messages/en.json";
import { click, installDom, renderReact } from "../../test/react-test-utils";

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
    const exec = { spanId: "e", kind: "exec", name: "exec", startedAt: 0 };
    const view = await renderReact(card({ loading: true, runningSpans: [exec, { spanId: "d", kind: "domain", name: "pypi.org", startedAt: 0 }] }));
    const status = () => view.container.querySelector('[role="status"]')?.textContent ?? null;
    assert.equal(status(), "Checking domain pypi.org…");

    await view.rerender(card({ loading: true, runningSpans: [exec, { spanId: "w", kind: "wait", name: "pypi.org", startedAt: 0 }] }));
    assert.equal(status(), "Waiting for approval…");
    await view.rerender(card({ loading: true, runningSpans: [exec, { spanId: "l", kind: "wait", name: "exec lock", startedAt: 0 }] }));
    assert.equal(status(), "Waiting for the previous command…");
    await view.rerender(card({ loading: true, runningSpans: [exec] }));
    assert.equal(status(), null, "the exec itself is the card's spinner");
    await view.rerender(card({ loading: false, runningSpans: [{ spanId: "s", kind: "sentinel", name: "tool_call", startedAt: 0 }] }));
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
    await view.rerender(card('{"title": "Average the ratings", "command": "cat > stats.py <<\'EOF\'\\nimport stat'));
    assert.equal(summary(), "Average the ratings");
    // The final card shows the same, so nothing jumps.
    await view.rerender(card('{"title": "Average the ratings", "command": "cat > stats.py <<\'EOF\'\\nEOF"}', false));
    assert.equal(summary(), "Average the ratings");
    await view.unmount();
  } finally {
    restore();
  }
});

test("an exec card shows its command as one block, heredoc bodies in their language, and the output apart, both named by role", async () => {
  const restore = installDom();
  try {
    const command = "python3 - <<'PY'\nprint(42)\nPY";
    const view = await renderReact(
      <NextIntlClientProvider locale="en" messages={messages}>
        <ToolCallBadge tool="exec" args={{ command }} detail="" result={"42\n[exit code: 0]\n"} exitCode={0} />
      </NextIntlClientProvider>,
    );
    let copied = "";
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText: async (text: string) => void (copied = text) } });
    await click(view.container.querySelector("button")!);

    const blockLabels = [...view.container.querySelectorAll(".exec-terminal-block > .md-code-block-shell > .md-code-block-toolbar .md-code-block-lang")];
    assert.deepEqual(blockLabels.map((label) => label.textContent), ["Command", "Output"]);
    const [commandBlock, outputBlock] = [...view.container.querySelectorAll(".exec-terminal-block .exec-block")];

    const fragments = [...commandBlock.querySelectorAll("pre")];
    assert.deepEqual(fragments.map((pre) => pre.textContent), ["❯ python3 - <<'PY'", "print(42)", "PY"]);
    assert.deepEqual([...commandBlock.querySelectorAll(".md-code-block-lang")].map((label) => label.textContent), ["shell", "python", "shell"]);
    assert.equal(outputBlock.querySelector("pre")?.textContent, "42\n[exit code: 0]", "the output is a block of its own");

    // The fragments' own copy buttons are hidden.
    const copyButtons = [...view.container.querySelectorAll(".exec-terminal-block .md-code-block-copy")].filter((button) => !button.closest(".code-fragments"));
    assert.equal(copyButtons.length, 2, "one copy button for the command, one for the output");
    await click(copyButtons[0]);
    assert.equal(copied, command, "the command's copy button copies it runnable, without the prompt");
    await click(copyButtons[1]);
    assert.equal(copied, "42\n[exit code: 0]");
    await view.unmount();
  } finally {
    restore();
  }
});

test("an exec card keeps the blank lines that end a heredoc body, so the line numbers match the command", async () => {
  const restore = installDom();
  try {
    const view = await renderReact(
      <NextIntlClientProvider locale="en" messages={messages}>
        <ToolCallBadge tool="exec" args={{ command: "python3 - <<'PY'\nprint(1)\n\n\nPY\n" }} detail="" result="1" exitCode={0} />
      </NextIntlClientProvider>,
    );
    await click(view.container.querySelector("button")!);
    const lineCounts = [...view.container.querySelector(".exec-block")!.querySelectorAll("code")].map((code) => code.querySelectorAll("[data-line]").length);
    assert.deepEqual(lineCounts, [1, 3, 1], "the body's two blank lines stay; the command's trailing newline adds none");
    await view.unmount();
  } finally {
    restore();
  }
});

test("a streaming exec highlights a heredoc once its opening line is complete", async () => {
  const restore = installDom();
  try {
    const card = (command: string) => (
      <NextIntlClientProvider locale="en" messages={messages}>
        <ToolCallBadge tool="exec" args={{ command }} argsText="" argsStreaming detail="" loading />
      </NextIntlClientProvider>
    );
    const view = await renderReact(card("python3 - <<'PY'"));
    assert.equal(view.container.querySelector(".streaming-code"), null, "plain until the interpreter is known");
    assert.equal(view.container.querySelector("pre")?.textContent, "$ python3 - <<'PY'");

    await view.rerender(card("python3 - <<'PY'\nimport js"));
    const labels = [...view.container.querySelectorAll(".streaming-code .md-code-block-lang")].map((label) => label.textContent);
    assert.deepEqual(labels, ["shell", "python"]);
    await view.unmount();
  } finally {
    restore();
  }
});

test("a long streaming write highlights only its last lines, with the rest plain above them", async () => {
  const restore = installDom();
  try {
    const content = Array.from({ length: 250 }, (_, i) => `x${i} = ${i}`).join("\n");
    const argsText = `{"path": "big.py", "content": ${JSON.stringify(content).slice(0, -1)}`;
    const view = await renderReact(
      <NextIntlClientProvider locale="en" messages={messages}>
        <ToolCallBadge tool="write" args={parseStreamingArgs(argsText)!} argsText={argsText} argsStreaming detail="" loading />
      </NextIntlClientProvider>,
    );
    const plain = view.container.querySelector("pre:not(.streaming-code pre)")?.textContent ?? "";
    const highlighted = view.container.querySelector(".streaming-code code")?.textContent ?? "";
    assert.equal(plain.split("\n").length, 50);
    assert.ok(plain.startsWith("x0 = 0\n") && plain.endsWith("x49 = 49"));
    assert.ok(highlighted.startsWith("x50 = 50\n") && highlighted.endsWith("x249 = 249"), "the last 200 lines, each shown once");
    await view.unmount();
  } finally {
    restore();
  }
});

test("read_skill names the skill, says what it waits for, and shows the skill once read", async () => {
  const restore = installDom();
  try {
    const card = (props: Partial<Parameters<typeof ToolCallBadge>[0]>) => (
      <NextIntlClientProvider locale="en" messages={messages}>
        <ToolCallBadge tool="read_skill" args={{ skill_name: "weather" }} detail="" {...props} />
      </NextIntlClientProvider>
    );
    const tool = { spanId: "t", kind: "tool", name: "read_skill", startedAt: 0 };
    const view = await renderReact(card({ loading: true, runningSpans: [tool, { spanId: "b", kind: "skill", name: "build wait", startedAt: 0 }] }));
    const text = () => view.container.textContent ?? "";
    assert.match(text(), /read skill/);
    assert.match(text(), /weather/);
    assert.match(text(), /Waiting for the skill build…/);

    await view.rerender(card({ loading: true, runningSpans: [tool, { spanId: "p", kind: "skill", name: "profile sync", startedAt: 0 }] }));
    assert.match(text(), /Installing the skill's commands…/);

    await view.rerender(card({ result: "# weather\n\n# Commands\n- `weather`: Current weather\n\nThe commands are on PATH." }));
    assert.doesNotMatch(text(), /Installing|Waiting/);
    (view.container.querySelector("button") as HTMLButtonElement).click();
    await new Promise((resolve) => setTimeout(resolve, 0));
    assert.match(text(), /The commands are on PATH\./);
    await view.unmount();
  } finally {
    restore();
  }
});

test("a finished read_skill without a result says so instead of opening an empty box", async () => {
  const restore = installDom();
  try {
    const view = await renderReact(
      <NextIntlClientProvider locale="en" messages={messages}>
        <ToolCallBadge tool="read_skill" args={{ skill_name: "weather" }} detail="" />
      </NextIntlClientProvider>,
    );
    await click(view.container.querySelector("button")!);
    assert.equal(view.container.querySelector(".tool-row-details")?.textContent, "No result was recorded for this call.");
    await view.unmount();
  } finally {
    restore();
  }
});

test("an open running card shows the step it waits for and how long it has run", async (t) => {
  t.mock.timers.enable({ apis: ["Date"], now: Date.parse("2026-01-01T12:00:00Z") });
  const restore = installDom();
  try {
    const build = { spanId: "b", kind: "skill", name: "build wait", startedAt: Date.now() - 95_000 };
    const view = await renderReact(
      <NextIntlClientProvider locale="en" messages={messages} timeZone="UTC">
        <ToolCallBadge tool="read_skill" args={{ skill_name: "ferret" }} detail="" loading runningSpans={[build]} />
      </NextIntlClientProvider>,
    );
    await click(view.container.querySelector("button")!);
    assert.equal(view.container.querySelector(".tool-row-details")?.textContent, "Waiting for the skill build…· 1 min 35 s");
    await view.unmount();
  } finally {
    restore();
  }
});

test("approval badges: none for an unreviewed call, an icon per verdict, and a tooltip that says who decided", async () => {
  const restore = installDom();
  try {
    const badge = async (props: Partial<Parameters<typeof ToolCallBadge>[0]>) => {
      const view = await renderReact(
        <NextIntlClientProvider locale="en" messages={messages}>
          <ToolCallBadge tool="exec" args={{ command: "ls" }} detail="" {...props} />
        </NextIntlClientProvider>,
      );
      const icon = [...view.container.querySelectorAll("[title] > svg")]
        .map((svg) => svg.getAttribute("class")?.match(/lucide-((?:shield|user|ban)[a-z-]*)/)?.[1])
        .find(Boolean);
      const shown = {
        title: icon ? view.container.querySelector(`[title] > svg.lucide-${icon}`)?.parentElement?.getAttribute("title") ?? null : null,
        icon: icon ?? null,
      };
      await view.unmount();
      return shown;
    };

    assert.deepEqual(await badge({}), { title: null, icon: null }, "an unreviewed tool call");
    assert.deepEqual(await badge({ approvalSource: "safe-list", approvalVerdict: "allow" }), { title: null, icon: null }, "stored by an older version");
    assert.deepEqual(
      await badge({ approvalSource: "sentinel", approvalVerdict: "allow", approvalExplanation: "Reads a public page." }),
      { title: "Allowed by the sentinel: Reads a public page.", icon: "shield-check" },
    );
    assert.deepEqual(await badge({ approvalSource: "sentinel", approvalVerdict: "deny", approvalExplanation: "Posts data." }), { title: "Denied by the sentinel: Posts data.", icon: "shield-x" });
    assert.deepEqual(await badge({ approvalSource: "sentinel", approvalVerdict: "escalate", approvalExplanation: "Unclear." }), { title: "The sentinel left this to you: Unclear.", icon: "shield-exclamation-point" });
    assert.deepEqual(await badge({ approvalSource: "user", approvalVerdict: "deny" }), { title: "Denied by you", icon: "user-x" });
    assert.deepEqual(
      await badge({ approvalSource: "policy", approvalVerdict: "deny", approvalExplanation: "10.0.0.5 is internal." }),
      { title: "Refused as an internal destination: 10.0.0.5 is internal.", icon: "ban" },
    );
  } finally {
    restore();
  }
});
