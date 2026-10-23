import assert from "node:assert/strict";
import { existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import test from "node:test";

const script = fileURLToPath(new URL("./prune-bitwarden.mjs", import.meta.url));

function write(path, content) {
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, content);
}

function packageAt(path, manifest, code) {
  write(join(path, "package.json"), JSON.stringify(manifest));
  write(join(path, "index.js"), code);
}

test("pruning preserves nested versions and required peers, skips unused packages, and fails on missing dependencies", () => {
  const temporary = mkdtempSync(join(tmpdir(), "bitwarden-prune-"));
  try {
    const source = join(temporary, "source");
    const target = join(temporary, "target");
    write(join(source, "package.json"), JSON.stringify({ name: "bundle", dependencies: { unused: "1" } }));
    write(join(source, "build/bw.js"), 'require("node:fs"); console.log(require("alpha"), require("@scope/peer"), require("buffer/"));');
    packageAt(join(source, "node_modules/alpha"), {
      name: "alpha",
      dependencies: { shared: "1" },
      peerDependencies: { "@scope/peer": "1", optional: "1" },
      peerDependenciesMeta: { optional: { optional: true } },
    }, 'module.exports = require("shared");');
    packageAt(join(source, "node_modules/alpha/node_modules/shared"), { name: "shared" }, 'module.exports = "nested";');
    packageAt(join(source, "node_modules/@scope/peer"), {
      name: "@scope/peer", dependencies: { shared: "2" },
    }, 'module.exports = require("shared");');
    packageAt(join(source, "node_modules/shared"), { name: "shared" }, 'module.exports = "root";');
    packageAt(join(source, "node_modules/buffer"), { name: "buffer" }, 'module.exports = "polyfill";');
    packageAt(join(source, "node_modules/unused"), { name: "unused" }, 'throw new Error("unused");');
    packageAt(join(source, "node_modules/alpha/node_modules/unused"), { name: "unused" }, 'throw new Error("unused");');

    const pruned = spawnSync(process.execPath, [script, source, target], { encoding: "utf8" });
    assert.equal(pruned.status, 0, pruned.stderr);
    const executed = spawnSync(process.execPath, [join(target, "build/bw.js")], { encoding: "utf8" });
    assert.equal(executed.status, 0, executed.stderr);
    assert.equal(executed.stdout.trim(), "nested root polyfill");
    assert.equal(existsSync(join(target, "node_modules/unused")), false);
    assert.equal(existsSync(join(target, "node_modules/alpha/node_modules/unused")), false);

    rmSync(join(source, "node_modules/shared"), { recursive: true });
    const missing = spawnSync(process.execPath, [script, source, join(temporary, "missing")], { encoding: "utf8" });
    assert.notEqual(missing.status, 0);
    assert.match(missing.stderr, /Cannot resolve required package shared/);
  } finally {
    rmSync(temporary, { recursive: true, force: true });
  }
});
