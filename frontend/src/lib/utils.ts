import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

import type { SandboxStatus, SessionInfo } from "./types";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

function parseTimestamp(iso?: string | null): number | null {
  if (!iso) return null;
  const value = Date.parse(iso);
  return Number.isNaN(value) ? null : value;
}

export function sessionHasKnowledgeChanges(
  session:
    | Pick<SessionInfo, "last_active" | "knowledge_last_committed_at">
    | null
    | undefined,
): boolean {
  if (!session) return false;
  const committedAt = parseTimestamp(session.knowledge_last_committed_at);
  if (committedAt == null) return true;
  const lastActive = parseTimestamp(session.last_active);
  if (lastActive == null) return false;
  return lastActive > committedAt;
}

export function canArchiveSession(
  session: Pick<SessionInfo, "message_count"> | null | undefined,
): boolean {
  return (session?.message_count ?? 0) > 0;
}

export function shouldConfirmArchiveSession(
  session: Pick<SessionInfo, "sandbox"> | null | undefined,
): boolean {
  const sandbox = session?.sandbox;
  if (!sandbox) return false;
  return sandbox.status !== "missing" || sandbox.storage_present;
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let value = bytes / 1024;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  return `${value.toFixed(value >= 10 ? 0 : 1)} ${units[unitIndex]}`;
}

export function sandboxStatusKey(status: SandboxStatus): SandboxStatus {
  switch (status) {
    case "missing":
    case "running":
    case "scaled_down":
    case "pending":
    case "stopped":
    case "error":
      return status;
  }
}

export function sandboxStatusIndicatorClass(status: SandboxStatus): string {
  switch (status) {
    case "running":
      return "bg-emerald-500";
    case "pending":
      return "bg-amber-500 animate-pulse";
    case "scaled_down":
      return "bg-sky-500";
    case "stopped":
      return "bg-slate-400";
    case "error":
      return "bg-destructive";
    case "missing":
      return "bg-slate-300";
  }
}

/** Splits `text` into alternating plain and matching parts around every case-insensitive occurrence of `query`. */
export function splitOnMatches(text: string, query: string): { text: string; match: boolean }[] {
  const needle = query.trim();
  if (!needle) return [{ text, match: false }];
  const pattern = new RegExp(`(${needle.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})`, "gi");
  // With a capturing group, split puts the matches at the odd indexes.
  return text
    .split(pattern)
    .map((part, index) => ({ text: part, match: index % 2 === 1 }))
    .filter((part) => part.text !== "");
}
