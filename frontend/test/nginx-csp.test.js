import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const CSP_HEADER = "add_header Content-Security-Policy $csp_img_src always;";

function directives(block) {
  return block.split("\n").map((line) => line.trim()).filter((line) => line && !line.startsWith("#"));
}

async function renderTemplate(extraOrigins) {
  const template = await readFile(new URL("../nginx.conf.template", import.meta.url), "utf-8");
  // What the nginx image's envsubst step does with the variable the Dockerfile defines.
  return template.replaceAll("${CARAPACE_CSP_IMG_SRC_EXTRA}", extraOrigins);
}

test("the image CSP allows our own origin, data: and blob:, plus configured origins", async () => {
  assert.match(await renderTemplate(""), /set \$csp_img_src "img-src 'self' data: blob: ";/);
  assert.match(
    await renderTemplate("https://api.example.com https://cdn.example.com"),
    /set \$csp_img_src "img-src 'self' data: blob: https:\/\/api\.example\.com https:\/\/cdn\.example\.com";/,
  );
});

test("every location that sets its own headers repeats the CSP", async () => {
  const config = await renderTemplate("");
  const locations = config.split(/\n\s*location /).slice(1);
  assert.ok(locations.length > 0);
  for (const location of locations) {
    // A location's own add_header replaces the server-level ones instead of adding to them.
    const lines = directives(location);
    if (lines.some((line) => line.startsWith("add_header"))) assert.ok(lines.includes(CSP_HEADER), location);
  }
  assert.ok(directives(config.split(/\n\s*location /)[0]).includes(CSP_HEADER));
});
