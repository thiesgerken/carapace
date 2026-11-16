import assert from "node:assert/strict";
import test from "node:test";

import { cacheHitRate, compactCount, costShape, isEmptyColumn } from "./request-table";
import type { LlmRequestRecord } from "./types";

const record = (overrides: Partial<LlmRequestRecord>) => ({ input_tokens: 1000, cache_read_tokens: null, reasoning_tokens: null, ...overrides }) as LlmRequestRecord;

test("a column is empty when every row is 0 or unknown", () => {
  const reasoning = (r: LlmRequestRecord) => r.reasoning_tokens;
  assert.equal(isEmptyColumn([record({ reasoning_tokens: 0 }), record({})], reasoning), true);
  assert.equal(isEmptyColumn([record({ reasoning_tokens: 0 }), record({ reasoning_tokens: 12 })], reasoning), false);
});

test("the cache hit rate needs a cache count and some input", () => {
  assert.equal(cacheHitRate(record({ cache_read_tokens: 250 })), 0.25);
  assert.equal(cacheHitRate(record({ cache_read_tokens: 0 })), 0);
  assert.equal(cacheHitRate(record({})), null);
  assert.equal(cacheHitRate(record({ input_tokens: 0, cache_read_tokens: 0 })), null);
});

test("cost reads as actual, subscription equivalent, or both", () => {
  const cost = (cost_usd: string | null, equivalent_cost_usd: string | null) => ({ cost_usd, equivalent_cost_usd, provider_cost_usd: null });
  assert.equal(costShape(null), "none");
  assert.equal(costShape(cost(null, null)), "none");
  assert.equal(costShape(cost("0.02", "0.02")), "actual");
  assert.equal(costShape(cost("0", "0.0054")), "subscription");
  assert.equal(costShape(cost("0.01", "0.0425")), "both");
});

test("counts compact to k and M in the locale's digits", () => {
  const de = (value: number, maximumFractionDigits: number) => new Intl.NumberFormat("de", { maximumFractionDigits }).format(value);
  assert.equal(compactCount(840, de), "840");
  assert.equal(compactCount(8412, de), "8,4k");
  assert.equal(compactCount(1_250_000, de), "1,3M");
});
