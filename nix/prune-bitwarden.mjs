import { copyFileSync, existsSync, mkdirSync, readFileSync, readdirSync, statSync } from "node:fs";
import { createRequire, isBuiltin } from "node:module";
import { join, relative, resolve } from "node:path";

const [source, destination] = process.argv.slice(2).map((path) => resolve(path));
const copied = new Set();
const externals = new Set();

// cpSync gives copied directories the read-only mode of their store originals before
// filling them, which fails as soon as a directory has children. Fresh directories stay writable.
function copyTree(from, to, skip = () => false) {
  mkdirSync(to, { recursive: true });
  for (const entry of readdirSync(from)) {
    if (skip(entry)) continue;
    const [fromEntry, toEntry] = [join(from, entry), join(to, entry)];
    if (statSync(fromEntry).isDirectory()) copyTree(fromEntry, toEntry, skip);
    else copyFileSync(fromEntry, toEntry);
  }
}

function copyPackage(name, parent, optional = false) {
  const search = createRequire(join(parent, "package.json")).resolve.paths(`${name}/`);
  const directory = search?.map((path) => join(path, name)).find((path) => existsSync(join(path, "package.json")));
  if (!directory) {
    if (optional || isBuiltin(name)) return;
    throw new Error(`Cannot resolve required package ${name} from ${parent}`);
  }
  if (copied.has(directory)) return;
  const path = relative(source, directory);
  if (path.startsWith("../")) throw new Error(`Package ${name} resolved outside ${source}: ${directory}`);
  copied.add(directory);
  // Nested dependencies are copied separately, preserving Node's lookup layout.
  copyTree(directory, join(destination, path), (entry) => entry === "node_modules");
  const manifest = JSON.parse(readFileSync(join(directory, "package.json"), "utf8"));
  const dependencies = new Set([
    ...Object.keys(manifest.dependencies ?? {}),
    ...Object.keys(manifest.optionalDependencies ?? {}),
    ...Object.keys(manifest.peerDependencies ?? {}),
  ]);
  for (const dependency of dependencies) {
    const optional = Object.hasOwn(manifest.optionalDependencies ?? {}, dependency)
      || manifest.peerDependenciesMeta?.[dependency]?.optional === true;
    copyPackage(dependency, directory, optional);
  }
}

mkdirSync(destination, { recursive: true });
copyFileSync(join(source, "package.json"), join(destination, "package.json"));
copyTree(join(source, "build"), join(destination, "build"));
for (const file of readdirSync(join(source, "build"), { recursive: true }).filter((file) => file.endsWith(".js"))) {
  const bundle = readFileSync(join(source, "build", file), "utf8");
  for (const [, specifier] of bundle.matchAll(/\brequire\s*\(\s*["']([^"']+)["']\s*\)/g)) {
    if (!specifier.startsWith(".") && !isBuiltin(specifier)) externals.add(specifier);
  }
}
for (const specifier of [...externals].sort()) {
  const name = specifier.startsWith("@") ? specifier.split("/").slice(0, 2).join("/") : specifier.split("/")[0];
  copyPackage(name, source);
}
console.log(JSON.stringify([...externals].sort()));
console.error(`Pruned Bitwarden: ${externals.size} bundle externals, ${copied.size} runtime packages`);
