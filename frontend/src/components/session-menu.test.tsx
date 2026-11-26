import assert from "node:assert/strict";
import test from "node:test";
import { NextIntlClientProvider } from "next-intl";

import english from "../../messages/en.json";
import { click, dispatchDocumentEvent, installDom, renderReact, runInAct } from "../../test/react-test-utils";
import { SessionMenu, SessionRowMenu } from "./session-menu";

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
        busy={false}
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
    assert.deepEqual(items(view.container), ["Pin session", "Remove favorite", "Archive session", "Debug view", "Copy session ID", "Delete session"]);
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
    assert.deepEqual(items(view.container), ["Unpin session", "Remove favorite", "Debug view", "Copy session ID", "Delete session"]);

    await dispatchDocumentEvent(new window.KeyboardEvent("keydown", { key: "Escape" }));
    assert.deepEqual(items(view.container), []);
    await view.unmount();
  } finally {
    restore();
  }
});

test("the session menu trigger spins while an action from it runs", async () => {
  const restore = installDom();
  try {
    for (const busy of [false, true]) {
      const view = await renderMenu({ busy });
      assert.equal(view.container.querySelector('button[aria-haspopup="menu"] .animate-spin') !== null, busy);
      await view.unmount();
    }
  } finally {
    restore();
  }
});

test("the session menu copies the session id", async () => {
  const restore = installDom();
  const copied: string[] = [];
  Object.defineProperty(window.navigator, "clipboard", {
    configurable: true,
    value: { writeText: async (text: string) => void copied.push(text) },
  });
  try {
    const view = await renderMenu();
    await click(view.container.querySelector('button[aria-haspopup="menu"]')!);
    const copy = Array.from(view.container.querySelectorAll('[role="menuitem"]')).find((item) => item.textContent === "Copy session ID");
    await click(copy!);
    assert.deepEqual(copied, ["s 1"]);
    assert.deepEqual(items(view.container), []);
    await view.unmount();
  } finally {
    restore();
  }
});

test("a sidebar row's menu offers the attribute actions and delete, and its clicks never open the row", async () => {
  const restore = installDom();
  try {
    const calls: string[] = [];
    const view = await renderReact(
      <NextIntlClientProvider locale="en" messages={english} timeZone="UTC">
        <div onClick={() => calls.push("row")}>
          <SessionRowMenu
            className=""
            pinned={true}
            favorite={false}
            archived={false}
            canArchive={true}
            attributesDisabled={false}
            onTogglePinned={() => calls.push("pin")}
            onToggleFavorite={() => calls.push("favorite")}
            onToggleArchived={() => calls.push("archive")}
            onDelete={(event) => calls.push(event.shiftKey ? "delete+shift" : "delete")}
          />
        </div>
      </NextIntlClientProvider>,
    );
    const trigger = view.container.querySelector('button[aria-haspopup="menu"]')!;
    const menuItem = (label: string) => Array.from(view.container.querySelectorAll('[role="menuitem"]')).find((item) => item.textContent === label)!;

    await click(trigger);
    assert.deepEqual(items(view.container), ["Unpin session", "Favorite session", "Archive session", "Delete session"]);
    assert.ok(view.container.querySelector("[data-open]"), "the open menu keeps its button revealed");

    await click(menuItem("Archive session"));
    assert.deepEqual(items(view.container), []);

    await click(trigger);
    await runInAct(() => {
      menuItem("Delete session").dispatchEvent(new window.MouseEvent("click", { bubbles: true, shiftKey: true }));
    });
    assert.deepEqual(calls, ["archive", "delete+shift"]);
    await view.unmount();
  } finally {
    restore();
  }
});
