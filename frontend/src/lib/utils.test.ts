import assert from "node:assert/strict";
import test from "node:test";

import { splitOnMatches } from "./utils";

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
