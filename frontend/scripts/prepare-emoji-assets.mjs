import {
  cpSync,
  existsSync,
  mkdirSync,
  readdirSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const frontendRoot = path.resolve(__dirname, "..");
const publicEmojiDir = path.join(frontendRoot, "public", "emoji");
const JDECKED_TWEMOJI_PACKAGE_DIR = path.join(
  frontendRoot,
  "node_modules",
  "jdecked-twemoji-assets",
  "assets",
  "svg",
);
const generatedFilePath = path.join(
  frontendRoot,
  "src",
  "lib",
  "emoji.generated.ts",
);

const sourceDir = resolveSourceDir();

rmSync(publicEmojiDir, { force: true, recursive: true });

mkdirSync(publicEmojiDir, { recursive: true });

const svgFiles = collectSvgFiles(sourceDir);
const copied = new Set();

for (const filePath of svgFiles) {
  const fileName = path.basename(filePath).toLowerCase();
  const targetPath = path.join(publicEmojiDir, fileName);
  if (copied.has(fileName)) {
    continue;
  }
  cpSync(filePath, targetPath);
  copied.add(fileName);
}

writeGeneratedModule({
  codepoints: Array.from(copied, (fileName) => fileName.slice(0, -4)).sort(),
});

process.stdout.write(
  `Prepared bundled Twemoji assets with ${copied.size} SVG files.\n`,
);

function resolveSourceDir() {
  if (!existsSync(JDECKED_TWEMOJI_PACKAGE_DIR)) {
    throw new Error(
      "Twemoji assets were not found under node_modules/jdecked-twemoji-assets/assets/svg. This frontend sources Twemoji from the jdecked/twemoji repository tarball, so run pnpm install first.",
    );
  }

  return JDECKED_TWEMOJI_PACKAGE_DIR;
}

function collectSvgFiles(dirPath) {
  const entries = readdirSync(dirPath, { withFileTypes: true });
  const files = [];

  for (const entry of entries) {
    const entryPath = path.join(dirPath, entry.name);
    if (entry.isDirectory()) {
      files.push(...collectSvgFiles(entryPath));
      continue;
    }

    if (entry.isFile() && entry.name.endsWith(".svg")) {
      files.push(entryPath);
    }
  }

  return files;
}

function writeGeneratedModule({ codepoints }) {
  const contents = `export const emojiSet = "twemoji" as const;\n\nexport const bundledEmojiCodepoints = ${JSON.stringify(codepoints, null, 2)} as const;\n`;
  writeFileSync(generatedFilePath, contents);
}
