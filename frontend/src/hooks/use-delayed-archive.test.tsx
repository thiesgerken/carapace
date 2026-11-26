import assert from "node:assert/strict";
import test, { type TestContext } from "node:test";
import { installDom, renderReact, runInAct } from "../../test/react-test-utils";
import { ARCHIVE_UNDO_DELAY_MS, useDelayedArchive, type DelayedArchive } from "./use-delayed-archive";

async function renderProbe(t: TestContext) {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const archived: string[] = [];
  const probe: { current: DelayedArchive | null } = { current: null };
  function Probe() {
    probe.current = useDelayedArchive(async (sessionId) => {
      archived.push(sessionId);
    });
    return null;
  }
  const view = await renderReact(<Probe />);
  const delayed = () => probe.current!;
  const tick = (ms: number) => runInAct(() => t.mock.timers.tick(ms));
  return { view, archived, delayed, tick };
}

test("an archive reaches the server only after the undo window", async (t) => {
  const restore = installDom();
  try {
    const { view, archived, delayed, tick } = await renderProbe(t);
    let settled = false;
    await runInAct(() => void delayed().schedule("s1").then(() => { settled = true; }));
    assert.equal(delayed().pendingSessionId, "s1");
    assert.deepEqual(delayed().archivingSessionIds, ["s1"]);

    await tick(ARCHIVE_UNDO_DELAY_MS - 1);
    assert.deepEqual(archived, []);

    await tick(1);
    assert.deepEqual(archived, ["s1"]);
    assert.equal(delayed().pendingSessionId, null);
    assert.equal(settled, true);
    assert.deepEqual(delayed().archivingSessionIds, [], "the session's own state takes over once the request finished");
    await view.unmount();
  } finally {
    restore();
  }
});

test("undo in the window means the archive request never happens", async (t) => {
  const restore = installDom();
  try {
    const { view, archived, delayed, tick } = await renderProbe(t);
    let settled = false;
    await runInAct(() => void delayed().schedule("s1").then(() => { settled = true; }));
    await tick(1_000);
    await runInAct(() => delayed().undo());
    assert.equal(delayed().pendingSessionId, null);
    assert.equal(settled, true);

    await tick(ARCHIVE_UNDO_DELAY_MS);
    assert.deepEqual(archived, []);
    await view.unmount();
  } finally {
    restore();
  }
});

test("a second archive sends the waiting one first, and closing the toast sends it right away", async (t) => {
  const restore = installDom();
  try {
    const { view, archived, delayed } = await renderProbe(t);
    await runInAct(() => void delayed().schedule("s1"));
    await runInAct(() => void delayed().schedule("s2"));
    assert.deepEqual(archived, ["s1"]);
    assert.equal(delayed().pendingSessionId, "s2");

    await runInAct(() => delayed().commitNow());
    assert.deepEqual(archived, ["s1", "s2"]);
    assert.equal(delayed().pendingSessionId, null);
    await view.unmount();
  } finally {
    restore();
  }
});

test("leaving the page in the window drops the archive", async (t) => {
  const restore = installDom();
  try {
    const { view, archived, delayed, tick } = await renderProbe(t);
    await runInAct(() => void delayed().schedule("s1"));
    await view.unmount();
    await tick(ARCHIVE_UNDO_DELAY_MS);
    assert.deepEqual(archived, []);
  } finally {
    restore();
  }
});
