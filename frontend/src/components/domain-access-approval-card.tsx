"use client";

import { cn } from "@/lib/utils";
import { Globe } from "lucide-react";
import type { EscalationDecision, DomainAccessApprovalRequest } from "@/lib/types";

interface DomainAccessApprovalCardProps {
  request: DomainAccessApprovalRequest;
  onRespond: (decision: EscalationDecision) => void;
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
  const resolved = decision !== undefined;

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
        <div className="mt-3 flex flex-wrap gap-2">
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
            onClick={() => onRespond("deny")}
            className={cn(
              "rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
              "border border-destructive/50 text-destructive hover:bg-destructive/10",
            )}
          >
            Deny
          </button>
        </div>
      )}
    </div>
  );
}
