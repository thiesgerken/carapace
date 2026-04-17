"use client";

import { Brain, Check, ChevronRight, Copy, Loader2 } from "lucide-react";
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

function ThinkingBadge({
  content,
  streaming,
}: {
  content: string;
  streaming: boolean;
}) {
  const [manualOpen, setManualOpen] = useState(false);
  const open = streaming || manualOpen;

  return (
    <div className="my-1 w-full min-w-0">
      <button
        type="button"
        onClick={() => setManualOpen((prev) => !prev)}
        className={cn(
          "flex w-full min-w-0 items-center gap-1.5 rounded-md px-2 py-1 text-xs text-left",
          "bg-muted/60 text-muted-foreground",
          "hover:bg-accent transition-colors",
        )}
      >
        <ChevronRight
          className={cn(
            "h-3 w-3 shrink-0 transition-transform",
            open && "rotate-90",
          )}
        />
        {streaming ? (
          <Loader2 className="h-3 w-3 shrink-0 animate-spin text-muted-foreground" />
        ) : (
          <Brain className="h-3 w-3 shrink-0 text-muted-foreground" />
        )}
        <span className="shrink-0 font-mono font-medium text-foreground/80">
          {streaming ? "thinking…" : "thought"}
        </span>
        {!streaming && content.length > 0 && (
          <span className="min-w-0 truncate font-mono text-[11px] text-foreground/65 dark:text-foreground/70">
            {content.length.toLocaleString()} chars
          </span>
        )}
      </button>

      {open && (
        <div className="ml-5 mt-1.5 rounded-lg border border-border/60 bg-muted/30 p-3 text-xs text-muted-foreground">
          <MarkdownContent content={content} />
        </div>
      )}
    </div>
  );
}

interface MessageProps {
  message: ChatMessage;
  onApproval?: (toolCallId: string, approved: boolean, message?: string) => void;
  onEscalation?: (
    requestId: string,
    decision: EscalationDecision,
    message?: string,
  ) => void;
  onCredentialApproval?: (
    requestId: string,
    decision: EscalationDecision,
    message?: string,
  ) => void;
}

export function Message({
  message,
  onApproval,
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

    case "thinking":
      return <ThinkingBadge content={message.content} streaming={false} />;

    case "thinking_streaming":
      return <ThinkingBadge content={message.content} streaming />;

    case "tool_call":
      return (
        <ToolCallBadge
          tool={message.tool}
          args={message.args}
          detail={message.detail}
          contexts={message.contexts}
          approvalSource={message.approvalSource}
          approvalVerdict={message.approvalVerdict}
          approvalExplanation={message.approvalExplanation}
          decisionMessage={message.decisionMessage}
          result={message.result}
          exitCode={message.exitCode}
          loading={message.loading}
          childCalls={message.children?.map((c) => ({
            tool: c.tool,
            args: c.args,
            detail: c.detail,
            contexts: c.contexts,
            approvalSource: c.approvalSource,
            approvalVerdict: c.approvalVerdict,
            approvalExplanation: c.approvalExplanation,
            decisionMessage: c.decisionMessage,
            result: c.result,
            exitCode: c.exitCode,
            loading: c.loading,
          }))}
        />
      );

    case "approval":
      return (
        <ApprovalCard
          request={message.request}
          onRespond={(approved, responseMessage) =>
            onApproval?.(message.request.tool_call_id, approved, responseMessage)
          }
        />
      );

    case "domain_access_approval":
      return (
        <DomainAccessApprovalCard
          request={message.request}
          decision={message.decision}
          onRespond={(decision, responseMessage) =>
            onEscalation?.(message.request.request_id, decision, responseMessage)
          }
        />
      );

    case "git_push_approval":
      return (
        <GitPushApprovalCard
          request={message.request}
          decision={message.decision}
          onRespond={(decision, responseMessage) =>
            onEscalation?.(message.request.request_id, decision, responseMessage)
          }
        />
      );

    case "credential_approval":
      return (
        <CredentialApprovalCard
          request={message.request}
          decision={message.decision}
          onRespond={(decision, responseMessage) =>
            onCredentialApproval?.(
              message.request.request_id,
              decision,
              responseMessage,
            )
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
