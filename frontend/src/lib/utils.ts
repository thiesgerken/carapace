import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

import type { SandboxStatus } from "./types";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
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

export function sandboxStatusLabel(status: SandboxStatus): string {
  switch (status) {
    case "missing":
      return "Not Started";
    case "running":
      return "Running";
    case "scaled_down":
      return "Spun Down";
    case "pending":
      return "Starting Up";
    case "stopped":
      return "Stopped";
    case "error":
      return "Error";
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
