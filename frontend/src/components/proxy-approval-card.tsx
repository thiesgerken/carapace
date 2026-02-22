"use client";

import { cn } from "@/lib/utils";
import type { DomainDecision, ProxyApprovalRequest } from "@/lib/types";

interface ProxyApprovalCardProps {
  request: ProxyApprovalRequest;
  onRespond: (decision: DomainDecision) => void;
  decision?: DomainDecision;
}

const DECISION_LABELS: Record<DomainDecision, string> = {
  allow_once: "Allowed once",
  allow_all_once: "Allowed all (once)",
  allow_15min: "Allowed for 15 min",
  allow_all_15min: "Allowed all for 15 min",
  deny: "Denied",
};

export function ProxyApprovalCard({
  request,
  onRespond,
  decision,
}: ProxyApprovalCardProps) {
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
            d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z M9 10l2 2 4-4"
          />
        </svg>
        Proxy Access Request
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
        <div className="mt-3 space-y-2">
          <div className="flex flex-wrap gap-2">
            <button
              onClick={() => onRespond("allow_once")}
              className={cn(
                "rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
                "bg-foreground text-background hover:bg-foreground/90",
              )}
            >
              Allow {request.domain} once
            </button>
            <button
              onClick={() => onRespond("allow_all_once")}
              className={cn(
                "rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
                "border border-border hover:bg-muted",
              )}
            >
              Allow all internet once
            </button>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              onClick={() => onRespond("allow_15min")}
              className={cn(
                "rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
                "bg-foreground text-background hover:bg-foreground/90",
              )}
            >
              Allow {request.domain} for 15 min
            </button>
            <button
              onClick={() => onRespond("allow_all_15min")}
              className={cn(
                "rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
                "border border-border hover:bg-muted",
              )}
            >
              Allow all internet for 15 min
            </button>
          </div>
          <div>
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
        </div>
      )}
    </div>
  );
}
