import { cn } from "@/lib/utils";
import { GitBranch } from "lucide-react";
import type { EscalationDecision, GitPushApprovalRequest } from "@/lib/types";
import { DenialNoteActions } from "./denial-note-actions";

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
        <DenialNoteActions
          allowLabel="Allow Push"
          notePlaceholder="Why should this push be blocked?"
          onAllow={() => onRespond("allow")}
          onDeny={(message) => onRespond("deny", message)}
        />
      )}
    </div>
  );
}
