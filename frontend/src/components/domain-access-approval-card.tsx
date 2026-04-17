"use client";

import { useState } from "react";

import { cn } from "@/lib/utils";
import { Globe } from "lucide-react";
import type { EscalationDecision, DomainAccessApprovalRequest } from "@/lib/types";

interface DomainAccessApprovalCardProps {
  request: DomainAccessApprovalRequest;
  onRespond: (decision: EscalationDecision, message?: string) => void;
  decision?: EscalationDecision;
}

const DECISION_LABELS: Record<EscalationDecision, string> = {
  allow: "Allowed",
  deny: "Denied",
};

export function DomainAccessApprovalCard({
  request,
  onRespond,
  decision,
}: DomainAccessApprovalCardProps) {
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
        <Globe className="h-3.5 w-3.5" />
        Domain Access Request
      </div>

      <div className="space-y-1.5">
        <div>
          <span className="text-muted-foreground">Domain: </span>
          <span className="font-mono font-medium">{request.domain}</span>
        </div>
        {request.command && (
          <div>
            <span className="text-muted-foreground">Triggered by: </span>
            <span className="font-mono text-xs text-foreground/80">
              {request.command}
            </span>
          </div>
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
              Allow {request.domain}
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
                placeholder="Why should this be blocked?"
              />
            </label>
          )}
        </div>
      )}
    </div>
  );
}
