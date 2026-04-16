"use client";

import { useState } from "react";

import { cn } from "@/lib/utils";
import { KeyRound } from "lucide-react";
import type {
  CredentialApprovalRequest,
  EscalationDecision,
} from "@/lib/types";

interface CredentialApprovalCardProps {
  request: CredentialApprovalRequest;
  onRespond: (decision: EscalationDecision, message?: string) => void;
  decision?: EscalationDecision;
}

const DECISION_LABELS: Record<EscalationDecision, string> = {
  allow: "Allowed",
  deny: "Denied",
};

export function CredentialApprovalCard({
  request,
  onRespond,
  decision,
}: CredentialApprovalCardProps) {
  const [message, setMessage] = useState("");
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
        <KeyRound className="h-3.5 w-3.5" />
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
              <span className="font-mono font-medium text-foreground">
                {name}
              </span>
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
        <div className="mt-3 space-y-3">
          <label className="block space-y-1">
            <span className="text-xs text-muted-foreground">
              Optional message when denying
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
              placeholder="Why should this credential access be blocked?"
            />
          </label>

          <div className="flex flex-wrap gap-2">
          <button
            onClick={() => onRespond("allow")}
            className={cn(
              "rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
              "bg-foreground text-background hover:bg-foreground/90",
            )}
          >
            Allow
          </button>
          <button
            onClick={() => onRespond("deny", message.trim() || undefined)}
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
