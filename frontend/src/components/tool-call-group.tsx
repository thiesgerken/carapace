"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";
import { ChevronRight, Layers, Loader2 } from "lucide-react";
import type { ReactNode } from "react";
import type { ChatMessage } from "@/lib/types";
import { cn } from "@/lib/utils";

interface ToolCallGroupProps {
  /** The grouped tool_call / thinking messages, for summary counting. */
  items: ChatMessage[];
  /** Pre-rendered child rows, shown when expanded. */
  children: ReactNode;
  /** Run still active (last message in the conversation) → start expanded. */
  inProgress: boolean;
}

export type RenderItem =
  | { type: "message"; index: number }
  | { type: "group"; start: number; indices: number[]; inProgress: boolean };

function isToolish(m: ChatMessage): boolean {
  // Deliveries must stay visible when the surrounding activity collapses.
  return (m.kind === "tool_call" && m.tool !== "send_file") || m.kind === "thinking" || m.kind === "thinking_streaming";
}

/**
 * Group maximal runs of tool/thinking messages. A run becomes a collapsible group only when it has
 * ≥2 items and contains ≥1 tool_call; otherwise its items render individually. A group that reaches
 * the end of the list is still in progress (rendered expanded).
 */
export function groupRenderItems(messages: ChatMessage[]): RenderItem[] {
  const items: RenderItem[] = [];
  let i = 0;
  while (i < messages.length) {
    if (!isToolish(messages[i])) {
      items.push({ type: "message", index: i });
      i++;
      continue;
    }
    const start = i;
    const indices: number[] = [];
    while (i < messages.length && isToolish(messages[i])) {
      indices.push(i);
      i++;
    }
    const hasToolCall = indices.some((j) => messages[j].kind === "tool_call");
    if (indices.length >= 2 && hasToolCall) {
      items.push({ type: "group", start, indices, inProgress: i >= messages.length });
    } else {
      for (const j of indices) items.push({ type: "message", index: j });
    }
  }
  return items;
}

interface ToolCallLike {
  tool: string;
  args: Record<string, unknown>;
}

/** All tool calls in the run, including ones nested as children rows. */
function flattenToolCalls(items: ChatMessage[]): ToolCallLike[] {
  const out: ToolCallLike[] = [];
  for (const m of items) {
    if (m.kind !== "tool_call") continue;
    out.push({ tool: m.tool, args: m.args });
    for (const c of m.children ?? []) out.push({ tool: c.tool, args: c.args });
  }
  return out;
}

function distinctPathCount(
  calls: ToolCallLike[],
  tool: string,
): { calls: number; files: number } {
  let count = 0;
  const paths = new Set<string>();
  for (const c of calls) {
    if (c.tool !== tool) continue;
    count++;
    const p = c.args.path;
    if (typeof p === "string" && p.length > 0) paths.add(p);
  }
  return { calls: count, files: paths.size || count };
}

function buildSummary(
  items: ChatMessage[],
  inProgress: boolean,
  t: (key: string, values?: Record<string, number>) => string,
): string {
  const tense = inProgress ? "present" : "past";
  const calls = flattenToolCalls(items);
  const exec = calls.filter((c) => c.tool === "exec").length;
  const read = distinctPathCount(calls, "read");
  const write = distinctPathCount(calls, "write");
  const edit = distinctPathCount(calls, "str_replace");
  const skill = calls.filter((c) => c.tool === "use_skill").length;
  const counted = new Set([
    "exec",
    "read",
    "write",
    "str_replace",
    "use_skill",
  ]);
  const other = calls.filter((c) => !counted.has(c.tool)).length;

  const parts: string[] = [];
  if (exec > 0) parts.push(t(`${tense}.exec`, { count: exec }));
  if (read.calls > 0) parts.push(t(`${tense}.read`, { count: read.files }));
  if (write.calls > 0) parts.push(t(`${tense}.write`, { count: write.files }));
  if (edit.calls > 0) parts.push(t(`${tense}.edit`, { count: edit.files }));
  if (skill > 0) parts.push(t(`${tense}.skill`, { count: skill }));
  if (other > 0) parts.push(t(`${tense}.other`, { count: other }));

  const joined = parts.join(", ");
  if (joined.length === 0) return t("empty");
  return joined.charAt(0).toUpperCase() + joined.slice(1);
}

export function ToolCallGroup({
  items,
  children,
  inProgress,
}: ToolCallGroupProps) {
  const t = useTranslations("toolCallGroup");
  // Until the user toggles, follow inProgress (collapse when the run finishes).
  const [override, setOverride] = useState<boolean | null>(null);
  const open = override ?? inProgress;

  const summary = buildSummary(items, inProgress, t);

  return (
    <div className="my-1 w-full min-w-0">
      <button
        type="button"
        onClick={() => setOverride(!open)}
        className={cn(
          "flex w-full min-w-0 items-center gap-1.5 rounded-md px-2 py-1 text-xs text-left",
          "text-muted-foreground hover:bg-accent transition-colors",
          open && "bg-accent",
        )}
      >
        <ChevronRight
          className={cn(
            "h-3 w-3 shrink-0 transition-transform",
            open && "rotate-90",
          )}
        />
        <Layers className="h-3 w-3 shrink-0 text-foreground/65 dark:text-foreground/70" />
        <span className="min-w-0 flex-1 overflow-hidden text-ellipsis whitespace-nowrap font-medium text-foreground/75 dark:text-foreground/80">
          {summary}
        </span>
        {inProgress && (
          <Loader2 className="ml-auto h-3 w-3 shrink-0 animate-spin text-muted-foreground" />
        )}
      </button>

      {open && (
        <div className="ml-3 mt-0.5 border-l border-border/80 pl-3">
          {children}
        </div>
      )}
    </div>
  );
}
