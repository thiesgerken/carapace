"use client";

import { cn } from "@/lib/utils";
import type { CredentialApprovalRequest, CredentialDecision } from "@/lib/types";

interface CredentialApprovalCardProps {
  request: CredentialApprovalRequest;
  onRespond: (decision: CredentialDecision) => void;
  decision?: CredentialDecision;
}

const DECISION_LABELS: Record<CredentialDecision, string> = {
  approved: "Approved",
  denied: "Denied",
};

export function CredentialApprovalCard({
  request,
  onRespond,
  decision,
}: CredentialApprovalCardProps) {
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
            d="M15.75 5.25a3 3 0 013 3m3 0a6 6 0 01-7.029 5.912c-.563-.097-1.159.026-1.563.43L10.5 17.25H8.25v2.25H6v2.25H2.25v-2.818c0-.597.237-1.17.659-1.591l6.499-6.499c.404-.404.527-1 .43-1.563A6 6 0 1121.75 8.25z"
          />
        </svg>
        Credential Request
      </div>

      <div className="space-y-1.5">
        {request.skill_name && (
          <div>
            <span className="text-muted-foreground">Skill: </span>
            <span className="font-medium">{request.skill_name}</span>
          </div>
        )}
        <div className="space-y-1">
          {request.names.map((name, i) => (
            <div key={request.vault_paths[i]} className="flex flex-col">
              <span className="font-mono font-medium text-foreground">{name}</span>
              {request.descriptions[i] && (
                <span className="text-xs text-muted-foreground">
                  {request.descriptions[i]}
                </span>
              )}
            </div>
          ))}
        </div>
        {request.explanation && (
          <div className="text-xs text-muted-foreground italic">
            {request.explanation}
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
            onClick={() => onRespond("approved")}
            className={cn(
              "rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
              "bg-foreground text-background hover:bg-foreground/90",
            )}
          >
            Approve
          </button>
          <button
            onClick={() => onRespond("denied")}
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
