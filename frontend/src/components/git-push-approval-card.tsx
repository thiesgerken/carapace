"use client";

import { useState } from "react";

import { cn } from "@/lib/utils";
import { GitBranch } from "lucide-react";
import type { EscalationDecision, GitPushApprovalRequest } from "@/lib/types";

interface GitPushApprovalCardProps {
  request: GitPushApprovalRequest;
  onRespond: (decision: EscalationDecision, message?: string) => void;
  decision?: EscalationDecision;
}

const DECISION_LABELS: Record<EscalationDecision, string> = {
  allow: "Allowed",
  deny: "Denied",
};

export function GitPushApprovalCard({
  request,
  onRespond,
  decision,
}: GitPushApprovalCardProps) {
  const [message, setMessage] = useState("");
  const [showNote, setShowNote] = useState(false);
  const resolved = decision !== undefined;

  function toggleNote(): void {
    if (showNote) {
      setMessage("");
    }
    setShowNote(!showNote);
  }

  return (
    <div
      className={cn(
        "my-2 rounded-lg border-2 p-3 text-sm",
        resolved
          ? "border-border bg-muted/30 opacity-60"
          : "border-warning/60 bg-warning/5",
      )}
    >
      <div className="mb-2 flex items-center gap-2 text-xs font-medium uppercase tracking-wider text-warning-foreground/70">
        <GitBranch className="h-3.5 w-3.5" />
        Git Push Request
      </div>

      <div className="space-y-1.5">
        <div>
          <span className="text-muted-foreground">Ref: </span>
          <span className="font-mono font-medium">{request.ref}</span>
        </div>
        {request.explanation && (
          <div>
            <span className="text-muted-foreground">Reason: </span>
            <span className="text-foreground/80">{request.explanation}</span>
          </div>
        )}
        {request.changed_files.length > 0 && (
          <details className="mt-1">
            <summary className="cursor-pointer text-xs text-muted-foreground hover:text-foreground">
              {request.changed_files.length} changed file
              {request.changed_files.length !== 1 && "s"}
            </summary>
            <ul className="mt-1 space-y-0.5 pl-3 font-mono text-xs text-foreground/80">
              {request.changed_files.map((f) => (
                <li key={f}>{f}</li>
              ))}
            </ul>
          </details>
        )}
        {resolved && decision && (
          <div className="text-xs text-muted-foreground italic">
            {DECISION_LABELS[decision]}
          </div>
        )}
      </div>

      {!resolved && (
        <div className="mt-3 space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={() => onRespond("allow")}
              className={cn(
                "rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
                "bg-foreground text-background hover:bg-foreground/90",
              )}
            >
              Allow Push
            </button>
            <button
              onClick={() =>
                onRespond("deny", showNote ? message.trim() || undefined : undefined)
              }
              className={cn(
                "rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
                "border border-destructive/50 text-destructive hover:bg-destructive/10",
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
            <label className="block space-y-1">
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
                placeholder="Why should this push be blocked?"
              />
            </label>
          )}
        </div>
      )}
    </div>
  );
}
