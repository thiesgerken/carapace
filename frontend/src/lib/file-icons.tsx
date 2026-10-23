import {
  Bot,
  Braces,
  Container,
  File,
  FileArchive,
  FileAudio,
  FileCode,
  FileSpreadsheet,
  FileText,
  FileType,
  FileVideo,
  Folder,
  FolderClock,
  FolderCog,
  FolderCode,
  GitBranch,
  Hammer,
  Image,
  Key,
  Lock,
  type LucideIcon,
  Package,
  Palette,
  ScrollText,
  Scale,
  Settings2,
  ShieldCheck,
  Sparkles,
  SquareTerminal,
  User,
} from "lucide-react";
import type { ReactNode } from "react";

/** Files whose meaning comes from their exact name, not their extension. */
const NAME_ICONS: Record<string, LucideIcon> = {
  "agents.md": Bot,
  "conversation.json": ScrollText,
  dockerfile: Container,
  "skill.md": Package,
  "soul.md": Sparkles,
  "security.md": ShieldCheck,
  "user.md": User,
  license: Scale,
  makefile: Hammer,
  readme: FileText,
  "readme.md": FileText,
  ".gitignore": GitBranch,
  ".gitattributes": GitBranch,
  ".gitmodules": GitBranch,
  ".env": Key,
  "package.json": Package,
  "pyproject.toml": Package,
  "requirements.txt": Package,
  "setup.sh": Hammer,
};

/** Lockfiles share an icon regardless of ecosystem. */
const LOCK_NAMES = new Set(["uv.lock", "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "cargo.lock"]);

const EXTENSION_ICONS: Record<string, LucideIcon> = {
  md: FileText,
  markdown: FileText,
  txt: FileText,
  rst: FileText,
  log: ScrollText,

  json: Braces,
  jsonl: Braces,
  yaml: Settings2,
  yml: Settings2,
  toml: Settings2,
  ini: Settings2,
  cfg: Settings2,
  conf: Settings2,
  env: Key,

  py: FileCode,
  ts: FileCode,
  tsx: FileCode,
  js: FileCode,
  jsx: FileCode,
  go: FileCode,
  rs: FileCode,
  rb: FileCode,
  java: FileCode,
  php: FileCode,
  c: FileCode,
  h: FileCode,
  cpp: FileCode,
  sql: FileCode,
  html: FileCode,
  css: Palette,
  scss: Palette,
  sh: SquareTerminal,
  bash: SquareTerminal,
  zsh: SquareTerminal,
  fish: SquareTerminal,

  png: Image,
  jpg: Image,
  jpeg: Image,
  gif: Image,
  svg: Image,
  webp: Image,
  avif: Image,
  ico: Image,
  bmp: Image,

  pdf: FileType,
  csv: FileSpreadsheet,
  tsv: FileSpreadsheet,
  xlsx: FileSpreadsheet,
  ods: FileSpreadsheet,

  zip: FileArchive,
  gz: FileArchive,
  tgz: FileArchive,
  bz2: FileArchive,
  xz: FileArchive,
  tar: FileArchive,
  "7z": FileArchive,
  rar: FileArchive,

  mp3: FileAudio,
  wav: FileAudio,
  flac: FileAudio,
  ogg: FileAudio,
  m4a: FileAudio,

  mp4: FileVideo,
  mov: FileVideo,
  mkv: FileVideo,
  webm: FileVideo,

  lock: Lock,
  pem: Key,
  key: Key,
};

export type EntryIconKind = "session" | "skill" | "artifact" | null;

export interface EntryIconTarget {
  name: string;
  type: "file" | "dir";
  kind: EntryIconKind;
}

function lookup({ name, type, kind }: EntryIconTarget): LucideIcon {
  // Recognized directories keep a folder silhouette so they still read as directories.
  if (type === "dir") {
    if (kind === "session") return FolderClock;
    if (kind === "skill") return FolderCog;
    if (kind === "artifact") return FolderCode;
    return Folder;
  }
  const lower = name.toLowerCase();
  const byName = NAME_ICONS[lower];
  if (byName) return byName;
  if (LOCK_NAMES.has(lower)) return Lock;

  const dot = lower.lastIndexOf(".");
  // A leading dot means a hidden file (.gitignore), not an extension.
  if (dot <= 0 || dot === lower.length - 1) return File;
  return EXTENSION_ICONS[lower.slice(dot + 1)] ?? File;
}

/**
 * Icon for a directory entry, by kind for directories and name/extension for files.
 * Returns an element rather than a component so callers do not assign a component
 * to a local during render.
 */
export function entryIcon(target: EntryIconTarget, className: string): ReactNode {
  const Icon = lookup(target);
  return <Icon className={className} />;
}
