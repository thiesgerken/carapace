import assert from "node:assert/strict";
import test from "node:test";

import { shouldConfirmArchiveSession, splitOnMatches } from "./utils";

test("shouldConfirmArchiveSession returns false when sandbox was never used", () => {
  assert.equal(
    shouldConfirmArchiveSession({
      sandbox: {
        exists: false,
        status: "missing",
        storage_present: false,
      },
    }),
    false,
  );
});

test("shouldConfirmArchiveSession returns true when sandbox storage exists", () => {
  assert.equal(
    shouldConfirmArchiveSession({
      sandbox: {
        exists: false,
        status: "missing",
        storage_present: true,
      },
    }),
    true,
  );
});

test("shouldConfirmArchiveSession returns true when sandbox is active or tracked", () => {
  assert.equal(
    shouldConfirmArchiveSession({
      sandbox: {
        exists: true,
        status: "running",
        storage_present: true,
      },
    }),
    true,
  );
});

test("shouldConfirmArchiveSession returns false without sandbox metadata", () => {
  assert.equal(shouldConfirmArchiveSession({ sandbox: null }), false);
  assert.equal(shouldConfirmArchiveSession(null), false);
});

test("splitOnMatches marks every case-insensitive occurrence", () => {
  assert.deepEqual(splitOnMatches("Buttermilk pancakes need buttermilk", "BUTTERMILK"), [
    { text: "Buttermilk", match: true },
    { text: " pancakes need ", match: false },
    { text: "buttermilk", match: true },
  ]);
});

test("splitOnMatches treats the query literally", () => {
  assert.deepEqual(splitOnMatches("save 100% (now)", "% (n"), [
    { text: "save 100", match: false },
    { text: "% (n", match: true },
    { text: "ow)", match: false },
  ]);
});

test("splitOnMatches leaves text without a query as one plain part", () => {
  assert.deepEqual(splitOnMatches("pancakes", "  "), [{ text: "pancakes", match: false }]);
});
