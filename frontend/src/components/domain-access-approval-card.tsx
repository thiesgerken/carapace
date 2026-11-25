import { useTranslations } from "next-intl";
import { cn } from "@/lib/utils";
import { Globe } from "lucide-react";
import type { EscalationDecision, DomainAccessApprovalRequest } from "@/lib/types";
import { DenialNoteActions } from "./denial-note-actions";

interface DomainAccessApprovalCardProps {
  request: DomainAccessApprovalRequest;
  onRespond: (decision: EscalationDecision, message?: string) => void;
  decision?: EscalationDecision;
}

export function DomainAccessApprovalCard({
  request,
  onRespond,
  decision,
}: DomainAccessApprovalCardProps) {
  const t = useTranslations("approval.domainAccess");
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
        <Globe className="h-3.5 w-3.5" />
        {t("title")}
      </div>

      <div className="space-y-1.5">
        <div>
          <span className="text-muted-foreground">{t("domainLabel")} </span>
          <span className="font-mono font-medium break-words">{request.domain}</span>
        </div>
        {request.command && (
          <div>
            <span className="text-muted-foreground">{t("triggeredByLabel")} </span>
            <span className="font-mono text-xs text-foreground/80 break-words">
              {request.command}
            </span>
          </div>
        )}
        {resolved && decision && (
          <div className="text-xs text-muted-foreground italic">
            {decisionLabels[decision]}
          </div>
        )}
      </div>

      {!resolved && (
        <DenialNoteActions
          allowLabel={t("allow", { domain: request.domain })}
          notePlaceholder={t("denyPlaceholder")}
          onAllow={() => onRespond("allow")}
          onDeny={(message) => onRespond("deny", message)}
        />
      )}
    </div>
  );
}
