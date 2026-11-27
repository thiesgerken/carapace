import assert from "node:assert/strict";
import test from "node:test";

import { nixError } from "./skill-config-form";

test("the form leads with Nix's last error, without the trace or the ignored cache noise", () => {
  const log = [
    "error (ignored): SQLite database '/tmp/.cache/nix/eval-cache-v6/x.sqlite' is busy",
    "error:",
    "       … in the condition of the assert statement",
    "         at «github:thiesgerken/carapace/1bf14e5»/nix/skills/default.nix:82:11:",
    "       error: skill ferret: no value for its setting FERRET_URL; set it in skills/config.json",
  ].join("\n");

  assert.equal(nixError(log), "skill ferret: no value for its setting FERRET_URL; set it in skills/config.json");
  assert.equal(nixError("The skill has no valid manifest; see docs/skill-flakes.md."), "The skill has no valid manifest; see docs/skill-flakes.md.");
});
