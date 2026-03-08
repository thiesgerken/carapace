"use client";

import { useState } from "react";
import { ChevronRight, Loader2, ShieldCheck, ShieldAlert, UserCheck } from "lucide-react";
import { cn } from "@/lib/utils";

interface ToolCallBadgeProps {
  tool: string;
  args: Record<string, unknown>;
  detail: string;
  result?: string;
  loading?: boolean;
}

type ApprovalSource = "safe-list" | "sentinel" | "user" | "unknown";
type ApprovalVerdict = "allow" | "deny" | "escalate";

function parseDetail(detail: string): {
  source: ApprovalSource;
  verdict: ApprovalVerdict;
  explanation: string;
  summary: string;
} {
  if (detail.startsWith("[safe-list]")) {
    return { source: "safe-list", verdict: "allow", explanation: "", summary: "auto-allowed" };
  }

  const match = detail.match(/^\[sentinel:\s*(allow|deny|escalate)]\s*([\s\S]*)/);
  if (match) {
    const verdict = match[1] as ApprovalVerdict;
    const explanation = match[2] ?? "";
    return { source: "sentinel", verdict, explanation, summary: explanation };
  }

  if (detail.includes("user approved") || detail.includes("escalate → allowed")) {
    return { source: "user", verdict: "allow", explanation: detail, summary: detail };
  }

  return { source: "unknown", verdict: "allow", explanation: detail, summary: detail };
}

function formatArgsSummary(args: Record<string, unknown>): string {
  const parts: string[] = [];
  for (const [k, v] of Object.entries(args)) {
    let vStr = typeof v === "string" ? v : JSON.stringify(v);
    if (vStr.length > 50) vStr = vStr.slice(0, 47) + "…";
    parts.push(`${k}=${vStr}`);
  }
  const joined = parts.join(", ");
  return joined.length > 120 ? joined.slice(0, 117) + "…" : joined;
}

function ApprovalBadge({ source, verdict }: { source: ApprovalSource; verdict: ApprovalVerdict }) {
  if (source === "safe-list") {
    return (
      <span className="inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[10px] font-medium bg-green-500/10 text-green-600 dark:text-green-400">
        <ShieldCheck className="h-2.5 w-2.5" />
        safe-list
      </span>
    );
  }

  if (source === "sentinel") {
    const colorClass = verdict === "allow"
      ? "bg-blue-500/10 text-blue-600 dark:text-blue-400"
      : verdict === "deny"
        ? "bg-red-500/10 text-red-600 dark:text-red-400"
        : "bg-yellow-500/10 text-yellow-600 dark:text-yellow-400";
    return (
      <span className={cn("inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[10px] font-medium", colorClass)}>
        <ShieldAlert className="h-2.5 w-2.5" />
        sentinel
      </span>
    );
  }

  if (source === "user") {
    return (
      <span className="inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[10px] font-medium bg-purple-500/10 text-purple-600 dark:text-purple-400">
        <UserCheck className="h-2.5 w-2.5" />
        user
      </span>
    );
  }

  return null;
}

export function ToolCallBadge({
  tool,
  args,
  detail,
  result,
  loading,
}: ToolCallBadgeProps) {
  const [open, setOpen] = useState(false);
  const { source, verdict, explanation } = parseDetail(detail);
  const argsSummary = formatArgsSummary(args);

  return (
    <div className="my-1">
      <button
        onClick={() => setOpen(!open)}
        className={cn(
          "inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs",
          "bg-muted/60 text-muted-foreground",
          "hover:bg-accent transition-colors",
          "max-w-full",
        )}
      >
        <ChevronRight
          className={cn("h-3 w-3 shrink-0 transition-transform", open && "rotate-90")}
        />
        <span className="font-mono font-medium text-foreground/80">{tool}</span>
        {argsSummary && (
          <span className="truncate opacity-50 font-mono max-w-[300px]">{argsSummary}</span>
        )}
        <ApprovalBadge source={source} verdict={verdict} />
        {loading && (
          <Loader2 className="ml-0.5 h-3 w-3 shrink-0 animate-spin text-muted-foreground" />
        )}
      </button>

      {open && (
        <div className="ml-5 mt-1.5 rounded-lg border border-border/60 bg-muted/30 p-3 space-y-2 text-xs">
          {explanation && (
            <div className="text-muted-foreground leading-relaxed">
              <span className="font-medium text-foreground/70">Sentinel: </span>
              {explanation}
            </div>
          )}

          <details open>
            <summary className="cursor-pointer text-muted-foreground hover:text-foreground transition-colors font-medium select-none">
              Arguments
            </summary>
            <pre className="mt-1.5 rounded-md bg-muted p-2.5 font-mono overflow-x-auto border border-border/40">
              {JSON.stringify(args, null, 2)}
            </pre>
          </details>

          {result != null && (
            <details open>
              <summary className="cursor-pointer text-muted-foreground hover:text-foreground transition-colors font-medium select-none">
                Result
              </summary>
              <pre className="mt-1.5 rounded-md bg-muted p-2.5 font-mono overflow-x-auto max-h-48 overflow-y-auto whitespace-pre-wrap border border-border/40">
                {result}
              </pre>
            </details>
          )}
        </div>
      )}
    </div>
  );
}
