/** Must match ``SANDBOX_READ_BODY_SEPARATOR`` in ``carapace.sandbox.manager``. */
export const SANDBOX_READ_BODY_SEPARATOR = "-".repeat(24);

export type SplitReadResult =
  | { hasSplit: true; header: string; body: string }
  | { hasSplit: false; body: string };

/** Split read-tool output into metadata (above the dash line) and file body (below). */
export function splitReadToolResult(result: string): SplitReadResult {
  const sep = SANDBOX_READ_BODY_SEPARATOR;
  const needle = `\n${sep}\n`;
  const i = result.indexOf(needle);
  if (i === -1) {
    return { hasSplit: false, body: result };
  }
  return {
    hasSplit: true,
    header: result.slice(0, i),
    body: result.slice(i + needle.length),
  };
}

const EXT_TO_LANG: Record<string, string> = {
  py: "python",
  pyw: "python",
  pyi: "python",
  rs: "rust",
  go: "go",
  ts: "typescript",
  tsx: "tsx",
  mts: "typescript",
  cts: "typescript",
  js: "javascript",
  jsx: "jsx",
  mjs: "javascript",
  cjs: "javascript",
  json: "json",
  jsonc: "jsonc",
  md: "markdown",
  mdx: "mdx",
  yaml: "yaml",
  yml: "yaml",
  toml: "toml",
  sh: "bash",
  bash: "bash",
  zsh: "bash",
  fish: "fish",
  html: "html",
  htm: "html",
  css: "css",
  scss: "scss",
  sass: "sass",
  less: "less",
  sql: "sql",
  xml: "xml",
  svg: "xml",
  vue: "vue",
  svelte: "svelte",
  rb: "ruby",
  php: "php",
  java: "java",
  kt: "kotlin",
  kts: "kotlin",
  swift: "swift",
  c: "c",
  h: "c",
  cpp: "cpp",
  cc: "cpp",
  cxx: "cpp",
  hpp: "cpp",
  cs: "csharp",
  fs: "fsharp",
  ex: "elixir",
  exs: "elixir",
  erl: "erlang",
  hs: "haskell",
  ml: "ocaml",
  nim: "nim",
  zig: "zig",
  v: "v",
  dockerfile: "dockerfile",
  tf: "hcl",
  hcl: "hcl",
  rego: "rego",
  graphql: "graphql",
  gql: "graphql",
};

/** Shiki / rehype-pretty-code language id from a sandbox path (e.g. ``/workspace/a/b.py``). */
export function languageFromFilePath(path: string): string {
  const trimmed = path.trim();
  if (!trimmed) return "text";
  const seg = trimmed.split(/[/\\]/).pop() ?? trimmed;
  const lower = seg.toLowerCase();
  if (lower === "dockerfile" || lower.endsWith("dockerfile"))
    return "dockerfile";
  const dot = lower.lastIndexOf(".");
  if (dot < 0 || dot === lower.length - 1) return "text";
  const ext = lower.slice(dot + 1);
  return EXT_TO_LANG[ext] ?? "text";
}

/** Wrap code for ``MarkdownContent`` with a fence that avoids breaking on embedded fences. */
export function fencedCodeBlock(lang: string, code: string): string {
  const trimmed = code.replace(/\n+$/, "");
  const fence = trimmed.includes("```") ? "````" : "```";
  return `${fence}${lang}\n${trimmed}\n${fence}`;
}
