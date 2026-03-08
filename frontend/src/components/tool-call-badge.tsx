"use client";

import { useState } from "react";
import { ChevronRight, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

interface ToolCallBadgeProps {
  tool: string;
  args: Record<string, unknown>;
  detail: string;
  result?: string;
  loading?: boolean;
}

export function ToolCallBadge({
  tool,
  args,
  detail,
  result,
  loading,
}: ToolCallBadgeProps) {
  const [open, setOpen] = useState(false);

  return (
    <div className="my-1">
      <button
        onClick={() => setOpen(!open)}
        className={cn(
          "inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs",
          "bg-muted text-muted-foreground",
          "hover:bg-accent transition-colors",
        )}
      >
        <ChevronRight
          className={cn("h-3 w-3 transition-transform", open && "rotate-90")}
        />
        <span className="font-mono">{tool}</span>
        {detail && <span className="opacity-60">{detail}</span>}
        {loading && (
          <Loader2 className="ml-1 h-3 w-3 animate-spin text-muted-foreground" />
        )}
      </button>
      {open && (
        <div className="ml-4 mt-1 space-y-1">
          <pre className="rounded-md bg-muted p-2 text-xs font-mono overflow-x-auto">
            {JSON.stringify(args, null, 2)}
          </pre>
          {result != null && (
            <pre className="rounded-md bg-muted p-2 text-xs font-mono overflow-x-auto max-h-48 overflow-y-auto whitespace-pre-wrap">
              {result}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}
