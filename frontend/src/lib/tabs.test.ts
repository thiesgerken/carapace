import assert from "node:assert/strict";
import test from "node:test";
import type { KeyboardEvent } from "react";

import { installDom } from "../../test/react-test-utils";

import { handleTabListKeyDown } from "./tabs";

function press(tablist: HTMLElement, key: string): void {
  handleTabListKeyDown({ key, currentTarget: tablist, preventDefault: () => {} } as unknown as KeyboardEvent<HTMLElement>);
}

test("arrow keys, Home and End move focus across tabs and wrap", () => {
  const restore = installDom();
  try {
    document.body.innerHTML = `<div role="tablist"><a role="tab" id="a" href="#">A</a><div><a role="tab" id="b" href="#">B</a><a role="tab" id="c" href="#">C</a></div></div>`;
    const tablist = document.querySelector<HTMLElement>('[role="tablist"]')!;
    document.getElementById("a")!.focus();

    const focused = (): string => (document.activeElement as HTMLElement).id;
    press(tablist, "ArrowRight");
    assert.equal(focused(), "b");
    press(tablist, "End");
    assert.equal(focused(), "c");
    press(tablist, "ArrowRight");
    assert.equal(focused(), "a");
    press(tablist, "ArrowLeft");
    assert.equal(focused(), "c");
    press(tablist, "Home");
    assert.equal(focused(), "a");
    press(tablist, "Enter");
    assert.equal(focused(), "a");
  } finally {
    restore();
  }
});
