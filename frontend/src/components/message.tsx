"use client";

import type { ChatMessage, EscalationDecision } from "@/lib/types";
import { MarkdownContent } from "./markdown-content";
import { ToolCallBadge } from "./tool-call-badge";
import { ApprovalCard } from "./approval-card";
import { DomainAccessApprovalCard } from "./domain-access-approval-card";
import { GitPushApprovalCard } from "./git-push-approval-card";
import { CommandResultView } from "./command-result";
import { cn } from "@/lib/utils";

interface MessageProps {
  message: ChatMessage;
  onApproval?: (toolCallId: string, approved: boolean) => void;
  approvalResolved?: boolean;
  onEscalation?: (requestId: string, decision: EscalationDecision) => void;
}

export function Message({
  message,
  onApproval,
  approvalResolved,
  onEscalation,
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
        <div className="max-w-[85%] text-sm">
          <MarkdownContent content={message.content} />
        </div>
      );

    case "streaming":
      return (
        <div className="max-w-[85%] text-sm">
          <MarkdownContent content={message.content} />
        </div>
      );

    case "tool_call":
      return (
        <ToolCallBadge
          tool={message.tool}
          args={message.args}
          detail={message.detail}
          result={message.result}
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
