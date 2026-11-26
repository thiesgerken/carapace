import assert from "node:assert/strict";
import test from "node:test";
import { NextIntlClientProvider } from "next-intl";

import english from "../../messages/en.json";
import { installDom, renderReact } from "../../test/react-test-utils";
import { SessionOptionSwitches } from "./session-option-tiles";

test("the option switches are one line per option, with a warning line only for an active safeguard-lowering one", async () => {
  const restore = installDom();
  try {
    const view = await renderReact(
      <NextIntlClientProvider locale="en" messages={english} timeZone="UTC">
        <SessionOptionSwitches
          items={[
            { key: "private", active: true },
            { key: "ask_mode", active: false },
            { key: "yolo_mode", active: true },
            { key: "unattended", active: false },
          ]}
        />
      </NextIntlClientProvider>,
    );
    const copy = english.newSessionButton;
    const switches = Array.from(view.container.querySelectorAll('[role="switch"]'));
    assert.deepEqual(switches.map((row) => row.getAttribute("aria-checked")), ["true", "false", "true", "false"]);
    assert.deepEqual(
      switches.map((row) => row.textContent),
      [copy.private.enabledTitle, copy.ask.enabledTitle, `${copy.yolo.enabledTitle}${copy.yolo.enabledDescription}`, copy.unattended.enabledTitle],
    );
    assert.deepEqual(
      switches.map((row) => row.getAttribute("title")),
      [copy.private.enabledDescription, copy.ask.enabledDescription, copy.yolo.enabledDescription, copy.unattended.enabledDescription],
    );
    const iconTone = (row: Element) => Array.from(row.querySelector("svg")?.classList ?? []).find((name) => name.startsWith("text-"));
    assert.deepEqual(switches.map(iconTone), ["text-primary", "text-muted-foreground", "text-warning", "text-muted-foreground"]);
    await view.unmount();
  } finally {
    restore();
  }
});
