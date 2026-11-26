import assert from "node:assert/strict";
import test from "node:test";
import { NextIntlClientProvider } from "next-intl";

import english from "../../messages/en.json";
import { installDom, renderReact } from "../../test/react-test-utils";
import { SessionOptionSwitches } from "./session-option-tiles";

test("the option switches carry the tiles' icons, tinted by state, with YOLO warning when on", async () => {
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
    const switches = Array.from(view.container.querySelectorAll('[role="switch"]'));
    assert.deepEqual(switches.map((row) => row.getAttribute("aria-checked")), ["true", "false", "true", "false"]);
    const iconTone = (row: Element) => Array.from(row.querySelector("svg")?.classList ?? []).find((name) => name.startsWith("text-"));
    assert.deepEqual(switches.map(iconTone), ["text-primary", "text-muted-foreground", "text-warning", "text-muted-foreground"]);
    await view.unmount();
  } finally {
    restore();
  }
});
