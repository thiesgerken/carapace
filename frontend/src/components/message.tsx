"use client";

import { Check, Copy } from "lucide-react";
import { useCallback, useState } from "react";

import type { ChatMessage, EscalationDecision } from "@/lib/types";
import { MarkdownContent } from "./markdown-content";
import { ToolCallBadge } from "./tool-call-badge";
import { ApprovalCard } from "./approval-card";
import { CredentialApprovalCard } from "./credential-approval-card";
import { DomainAccessApprovalCard } from "./domain-access-approval-card";
import { GitPushApprovalCard } from "./git-push-approval-card";
import { CommandResultView } from "./command-result";
import { cn } from "@/lib/utils";

function MessageCopyButton({
  text,
  className,
}: {
  text: string;
  className?: string;
}) {
  const [copied, setCopied] = useState(false);
  const copy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      /* clipboard may be denied; avoid throwing in UI */
    }
  }, [text]);

  if (!text) return null;

  return (
    <button
      type="button"
      className={cn(
        "rounded-md p-1 text-muted-foreground transition-[opacity,colors] hover:bg-muted hover:text-foreground focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
        "opacity-100 md:opacity-0 md:group-hover:opacity-100",
        className,
      )}
      aria-label={copied ? "Copied" : "Copy original Markdown"}
      title="Copy original Markdown"
      onClick={() => void copy()}
    >
      {copied ? (
        <Check className="size-3.5" strokeWidth={2} />
      ) : (
        <Copy className="size-3.5" strokeWidth={2} />
      )}
    </button>
  );
}

interface MessageProps {
  message: ChatMessage;
  onApproval?: (toolCallId: string, approved: boolean) => void;
  approvalResolved?: boolean;
  onEscalation?: (requestId: string, decision: EscalationDecision) => void;
  onCredentialApproval?: (
    requestId: string,
    decision: EscalationDecision,
  ) => void;
}

export function Message({
  message,
  onApproval,
  approvalResolved,
  onEscalation,
  onCredentialApproval,
}: MessageProps) {
  switch (message.kind) {
    case "user":
      return (
        <div className="flex justify-end">
          <div
            className={cn(
              "max-w-[85%] rounded-2xl rounded-br-md px-3.5 py-2 text-sm",
              "bg-user-bubble text-user-bubble-fg",
            )}
          >
            <p className="whitespace-pre-wrap">{message.content}</p>
          </div>
        </div>
      );

    case "assistant":
      return (
        <div className="group flex max-w-[85%] items-start gap-1.5 text-sm">
          <div className="min-w-0 flex-1">
            <MarkdownContent content={message.content} />
          </div>
          <MessageCopyButton text={message.content} className="shrink-0" />
        </div>
      );

    case "streaming":
      return (
        <div className="group flex max-w-[85%] items-start gap-1.5 text-sm">
          <div className="min-w-0 flex-1">
            <MarkdownContent content={message.content} />
          </div>
          <MessageCopyButton text={message.content} className="shrink-0" />
        </div>
      );

    case "tool_call":
      return (
        <ToolCallBadge
          tool={message.tool}
          args={message.args}
          detail={message.detail}
          result={message.result}
          exitCode={message.exitCode}
          loading={message.loading}
        />
      );

    case "approval":
      return (
        <ApprovalCard
          request={message.request}
          resolved={approvalResolved}
          onRespond={(approved) =>
            onApproval?.(message.request.tool_call_id, approved)
          }
        />
      );

    case "domain_access_approval":
      return (
        <DomainAccessApprovalCard
          request={message.request}
          decision={message.decision}
          onRespond={(decision) =>
            onEscalation?.(message.request.request_id, decision)
          }
        />
      );

    case "git_push_approval":
      return (
        <GitPushApprovalCard
          request={message.request}
          decision={message.decision}
          onRespond={(decision) =>
            onEscalation?.(message.request.request_id, decision)
          }
        />
      );

    case "credential_approval":
      return (
        <CredentialApprovalCard
          request={message.request}
          decision={message.decision}
          onRespond={(decision) =>
            onCredentialApproval?.(message.request.request_id, decision)
          }
        />
      );

    case "command":
      return (
        <CommandResultView command={message.command} data={message.data} />
      );

    case "error":
      return (
        <div className="my-1 rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
          <pre className="whitespace-pre-wrap font-mono text-xs">
            {message.detail}
          </pre>
        </div>
      );
  }
}
