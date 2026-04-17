import { cn } from "@/lib/utils";
import { AlertCircle } from "lucide-react";
import type { ApprovalRequest } from "@/lib/types";
import { DenialNoteActions } from "./denial-note-actions";

interface ApprovalCardProps {
  request: ApprovalRequest;
  onRespond: (approved: boolean, message?: string) => void;
}

export function ApprovalCard({
  request,
  onRespond,
}: ApprovalCardProps) {
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

      <DenialNoteActions
        allowLabel="Approve"
        denyButtonClassName="border border-border text-foreground hover:bg-muted"
        notePlaceholder="Why should this be blocked?"
        onAllow={() => onRespond(true)}
        onDeny={(message) => onRespond(false, message)}
      />
    </div>
  );
}
