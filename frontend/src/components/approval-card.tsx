"use client";

import { useState } from "react";

import { cn } from "@/lib/utils";
import { AlertCircle } from "lucide-react";
import type { ApprovalRequest } from "@/lib/types";

interface ApprovalCardProps {
  request: ApprovalRequest;
  onRespond: (approved: boolean, message?: string) => void;
}

export function ApprovalCard({
  request,
  onRespond,
}: ApprovalCardProps) {
  const [message, setMessage] = useState("");
  const [showNote, setShowNote] = useState(false);

  function toggleNote(): void {
    if (showNote) {
      setMessage("");
    }
    setShowNote(!showNote);
  }

  return (
    <div
      className={cn(
        "my-2 rounded-lg border-2 border-warning/60 bg-warning/5 p-3 text-sm",
      )}
    >
      <div className="mb-2 flex items-center gap-2 text-xs font-medium uppercase tracking-wider text-warning-foreground/70">
        <AlertCircle className="h-3.5 w-3.5" />
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

      <div className="mt-3 flex flex-wrap items-center gap-2">
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
          onClick={() => onRespond(false, showNote ? message.trim() || undefined : undefined)}
          className={cn(
            "rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
            "border border-border hover:bg-muted",
          )}
        >
          Deny
        </button>
        <button
          type="button"
          onClick={toggleNote}
          className="text-xs text-muted-foreground transition-colors hover:text-foreground"
        >
          {showNote ? "Hide note" : "Add note"}
        </button>
      </div>

      {showNote && (
        <label className="mt-3 block space-y-1">
          <span className="text-xs text-muted-foreground">
            Optional note for the agent
          </span>
          <textarea
            value={message}
            onChange={(event) => setMessage(event.target.value)}
            rows={2}
            className={cn(
              "w-full rounded-md border border-border bg-background px-3 py-2 text-xs",
              "text-foreground outline-none transition-colors",
              "focus:border-warning/60 focus:ring-2 focus:ring-warning/20",
            )}
            placeholder="Why should this be blocked?"
          />
        </label>
      )}
    </div>
  );
}
