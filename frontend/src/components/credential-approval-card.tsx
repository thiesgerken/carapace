import { useTranslations } from "next-intl";
import { cn } from "@/lib/utils";
import { KeyRound } from "lucide-react";
import type {
  CredentialApprovalRequest,
  EscalationDecision,
} from "@/lib/types";
import { DenialNoteActions } from "./denial-note-actions";

interface CredentialApprovalCardProps {
  request: CredentialApprovalRequest;
  onRespond: (decision: EscalationDecision, message?: string) => void;
  decision?: EscalationDecision;
}

export function CredentialApprovalCard({
  request,
  onRespond,
  decision,
}: CredentialApprovalCardProps) {
  const t = useTranslations("approval.credential");
  const resolved = decision !== undefined;
  // An up-front request (`cgate request`) can ask for domains next to credentials, or for domains only.
  const hasDomains = request.domains.length > 0;
  const hasCredentials = request.names.length > 0;
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
        <KeyRound className="h-3.5 w-3.5" />
        {hasDomains ? t("accessTitle") : t("title")}
      </div>

      <div className="space-y-1.5">
        {hasDomains && (
          <div className="space-y-1">
            <div className="text-xs text-muted-foreground">{t("domainsLabel")}</div>
            {request.domains.map((domain) => (
              <div key={domain} className="font-mono font-medium text-foreground">
                {domain}
              </div>
            ))}
          </div>
        )}
        {hasDomains && hasCredentials && (
          <div className="text-xs text-muted-foreground">{t("credentialsLabel")}</div>
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
