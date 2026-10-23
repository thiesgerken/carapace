import { chmodSync, cpSync, existsSync, mkdirSync, readFileSync, readdirSync } from "node:fs";
import { createRequire, isBuiltin } from "node:module";
import { basename, dirname, join, relative, resolve } from "node:path";

const [source, destination] = process.argv.slice(2).map((path) => resolve(path));
const copied = new Set();
const externals = new Set();

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
  const target = join(destination, path);
  mkdirSync(dirname(target), { recursive: true });
  cpSync(directory, target, {
    recursive: true,
    dereference: true,
    // Nested dependencies are copied separately, preserving Node's lookup layout.
    filter: (entry) => basename(entry) !== "node_modules",
  });
  // Store inputs are read-only; nested node_modules must remain creatable.
  chmodSync(target, 0o755);
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
cpSync(join(source, "package.json"), join(destination, "package.json"));
cpSync(join(source, "build"), join(destination, "build"), { recursive: true });
for (const file of readdirSync(join(source, "build"), { recursive: true }).filter((file) => file.endsWith(".js"))) {
  const bundle = readFileSync(join(source, "build", file), "utf8");
  for (const [, specifier] of bundle.matchAll(/\brequire\s*\(\s*["']([^"']+)["']\s*\)/g)) {
    if (!specifier.startsWith(".") && !isBuiltin(specifier)) externals.add(specifier);
  }
}
for (const specifier of [...externals].sort()) {
  const name = specifier.startsWith("@") ? specifier.split("/").slice(0, 2).join("/") : specifier.split("/")[0];
  copyPackage(name, source);
  createRequire(join(destination, "build", "bw.js")).resolve(specifier);
}
console.log(JSON.stringify([...externals].sort()));
console.error(`Pruned Bitwarden: ${externals.size} bundle externals, ${copied.size} runtime packages`);
