import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const CSP_HEADER = "add_header Content-Security-Policy $csp_img_src always;";

function directives(block) {
  return block.split("\n").map((line) => line.trim()).filter((line) => line && !line.startsWith("#"));
}

test("every location that sets its own headers repeats the CSP", async () => {
  const config = await readFile(new URL("../nginx.conf", import.meta.url), "utf-8");
  const locations = config.split(/\n\s*location /).slice(1);
  assert.ok(locations.length > 0);
  for (const location of locations) {
    // A location's own add_header replaces the server-level ones instead of adding to them.
    const lines = directives(location);
    if (lines.some((line) => line.startsWith("add_header"))) assert.ok(lines.includes(CSP_HEADER), location);
  }
  assert.ok(directives(config.split(/\n\s*location /)[0]).includes(CSP_HEADER));
});
