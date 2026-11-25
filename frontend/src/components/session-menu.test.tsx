import assert from "node:assert/strict";
import test from "node:test";
import { NextIntlClientProvider } from "next-intl";

import english from "../../messages/en.json";
import { click, dispatchDocumentEvent, installDom, renderReact } from "../../test/react-test-utils";
import { SessionMenu } from "./session-menu";

function renderMenu(overrides: Partial<Parameters<typeof SessionMenu>[0]> = {}, calls: string[] = []) {
  return renderReact(
    <NextIntlClientProvider locale="en" messages={english} timeZone="UTC">
      <SessionMenu
        sessionId="s 1"
        pinned={false}
        favorite={true}
        archived={false}
        canArchive={true}
        attributesDisabled={false}
        deleteDisabled={false}
        onTogglePinned={() => calls.push("pin")}
        onToggleFavorite={() => calls.push("favorite")}
        onToggleArchived={() => calls.push("archive")}
        onDelete={() => calls.push("delete")}
        {...overrides}
      />
    </NextIntlClientProvider>,
  );
}

const items = (container: Element) => Array.from(container.querySelectorAll('[role="menuitem"]'), (item) => item.textContent);

test("the session menu lists labelled actions with delete last and closes after one", async () => {
  const restore = installDom();
  try {
    const calls: string[] = [];
    const view = await renderMenu({}, calls);
    assert.deepEqual(items(view.container), []);

    await click(view.container.querySelector('button[aria-haspopup="menu"]')!);
    assert.deepEqual(items(view.container), ["Pin session", "Remove favorite", "Archive session", "Debug view", "Delete session"]);
    assert.equal(view.container.querySelector('a[role="menuitem"]')?.getAttribute("href"), "/?session=s%201&view=debug");

    await click(Array.from(view.container.querySelectorAll('[role="menuitem"]')).at(-1)!);
    assert.deepEqual(calls, ["delete"]);
    assert.deepEqual(items(view.container), []);
    await view.unmount();
  } finally {
    restore();
  }
});

test("the session menu hides archive when the session cannot be archived and closes on Escape", async () => {
  const restore = installDom();
  try {
    const view = await renderMenu({ canArchive: false, pinned: true });
    await click(view.container.querySelector('button[aria-haspopup="menu"]')!);
    assert.deepEqual(items(view.container), ["Unpin session", "Remove favorite", "Debug view", "Delete session"]);

    await dispatchDocumentEvent(new window.KeyboardEvent("keydown", { key: "Escape" }));
    assert.deepEqual(items(view.container), []);
    await view.unmount();
  } finally {
    restore();
  }
});
