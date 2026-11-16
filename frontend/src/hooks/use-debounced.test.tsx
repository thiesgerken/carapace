import assert from "node:assert/strict";
import { setTimeout as sleep } from "node:timers/promises";
import test from "node:test";
import { installDom, renderReact, runInAct } from "../../test/react-test-utils";
import { useDebounced } from "./use-debounced";

function Probe({ value }: { value: number }) {
  return <span>{useDebounced(value, 60, 150)}</span>;
}

test("a debounced value settles after a pause, and at the latest after the max wait in a steady stream", async () => {
  const restore = installDom();
  try {
    const view = await renderReact(<Probe value={0} />);
    const shown = () => view.container.textContent;

    await view.rerender(<Probe value={1} />);
    assert.equal(shown(), "0");
    await runInAct(() => sleep(100));
    assert.equal(shown(), "1", "settles once the value holds still");

    // A change every 30 ms never pauses for 60 ms; the max wait still lets one through.
    let value = 1;
    const started = Date.now();
    while (shown() === String(1) && Date.now() - started < 400) {
      await view.rerender(<Probe value={++value} />);
      await runInAct(() => sleep(30));
    }
    assert.notEqual(shown(), "1");
    assert.ok(Date.now() - started < 300, "the max wait caps the delay");
    await view.unmount();
  } finally {
    restore();
  }
});
