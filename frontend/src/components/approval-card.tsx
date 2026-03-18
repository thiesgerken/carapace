"use client";

import { cn } from "@/lib/utils";
import type { ApprovalRequest } from "@/lib/types";

interface ApprovalCardProps {
  request: ApprovalRequest;
  onRespond: (approved: boolean) => void;
  resolved?: boolean;
}

export function ApprovalCard({
  request,
  onRespond,
  resolved,
}: ApprovalCardProps) {
  return (
    <div
      className={cn(
        "my-2 rounded-lg border-2 p-3 text-sm",
        resolved === undefined
          ? "border-warning/60 bg-warning/5"
          : "border-border bg-muted/30 opacity-60",
      )}
    >
      <div className="mb-2 flex items-center gap-2 text-xs font-medium uppercase tracking-wider text-warning-foreground/70">
        <svg
          className="h-3.5 w-3.5"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M12 9v2m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
          />
        </svg>
        Approval Required
      </div>

      <div className="space-y-1.5">
        <div>
          <span className="text-muted-foreground">Tool: </span>
          <span className="font-mono font-medium">{request.tool}</span>
        </div>
        {request.explanation && (
          <div>
            <span className="text-muted-foreground">Reason: </span>
            <span>{request.explanation}</span>
          </div>
        )}
        {request.risk_level && (
          <div>
            <span className="text-muted-foreground">Risk: </span>
            <span
              className={cn(
                "font-medium",
                request.risk_level === "high" && "text-destructive",
                request.risk_level === "medium" && "text-warning-foreground",
                request.risk_level === "low" && "text-green-600 dark:text-green-400",
              )}
            >
              {request.risk_level}
            </span>
          </div>
        )}
        <details className="text-xs">
          <summary className="cursor-pointer text-muted-foreground hover:text-foreground transition-colors">
            Arguments
          </summary>
          <pre className="mt-1 rounded-md bg-muted p-2 font-mono overflow-x-auto whitespace-pre-wrap break-words">
            {JSON.stringify(request.args, null, 2)}
          </pre>
        </details>
      </div>

      {resolved === undefined && (
        <div className="mt-3 flex gap-2">
          <button
            onClick={() => onRespond(true)}
            className={cn(
              "rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
              "bg-foreground text-background hover:bg-foreground/90",
            )}
          >
            Approve
          </button>
          <button
            onClick={() => onRespond(false)}
            className={cn(
              "rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
              "border border-border hover:bg-muted",
            )}
          >
            Deny
          </button>
        </div>
      )}
    </div>
  );
}
