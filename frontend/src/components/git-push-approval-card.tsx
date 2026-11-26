import { useTranslations } from "next-intl";
import { cn } from "@/lib/utils";
import { GitBranch } from "lucide-react";
import type { EscalationDecision, GitPushApprovalRequest } from "@/lib/types";
import { DenialNoteActions } from "./denial-note-actions";

interface GitPushApprovalCardProps {
  request: GitPushApprovalRequest;
  onRespond: (decision: EscalationDecision, message?: string) => void;
  decision?: EscalationDecision;
}

export function GitPushApprovalCard({
  request,
  onRespond,
  decision,
}: GitPushApprovalCardProps) {
  const t = useTranslations("approval.gitPush");
  const resolved = decision !== undefined;
  const decisionLabels: Record<EscalationDecision, string> = {
    allow: t("decision.allow"),
    deny: t("decision.deny"),
  };

  return (
    <div
      className={cn(
        "my-2 rounded-lg border-2 p-3 text-sm",
        resolved
          ? "border-border bg-inset opacity-60"
          : "border-warning/60 bg-warning/5",
      )}
    >
      <div className="mb-2 flex items-center gap-2 text-xs font-medium text-warning">
        <GitBranch className="h-3.5 w-3.5" />
        {t("title")}
      </div>

      <div className="space-y-1.5">
        <div>
          <span className="text-muted-foreground">{t("refLabel")} </span>
          <span className="font-mono font-medium">{request.ref}</span>
        </div>
        {request.explanation && (
          <div>
            <span className="text-muted-foreground">{t("reasonLabel")} </span>
            <span className="text-foreground/80">{request.explanation}</span>
          </div>
        )}
        {request.changed_files.length > 0 && (
          <details className="mt-1">
            <summary className="cursor-pointer text-xs text-muted-foreground hover:text-foreground">
              {t("changedFiles", { count: request.changed_files.length })}
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
            {decisionLabels[decision]}
          </div>
        )}
      </div>

      {!resolved && (
        <DenialNoteActions
          allowLabel={t("allow")}
          notePlaceholder={t("denyPlaceholder")}
          onAllow={() => onRespond("allow")}
          onDeny={(message) => onRespond("deny", message)}
        />
      )}
    </div>
  );
}
