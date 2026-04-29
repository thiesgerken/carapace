"use client";

import { Brain, Check, ChevronRight, Copy, Loader2, RotateCcw, Undo2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import type { ChatMessage, EscalationDecision, LlmActivity } from "@/lib/types";
import { MarkdownContent } from "./markdown-content";
import { ToolCallBadge } from "./tool-call-badge";
import { ApprovalCard } from "./approval-card";
import { CredentialApprovalCard } from "./credential-approval-card";
import { DomainAccessApprovalCard } from "./domain-access-approval-card";
import { GitPushApprovalCard } from "./git-push-approval-card";
import { CommandResultView } from "./command-result";
import { cn } from "@/lib/utils";

function formatDuration(ms: number): string {
  if (ms < 1_000) return `${ms}ms`;
  if (ms < 10_000) return `${(ms / 1_000).toFixed(1)}s`;
  return `${Math.round(ms / 1_000)}s`;
}

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
        "rounded-md p-1 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
        className,
      )}
      aria-label={copied ? "Copied" : "Copy message"}
      title={copied ? "Copied" : "Copy message"}
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
  reasoningDurationMs,
  reasoningTokens,
  activeLlmActivity,
}: {
  content: string;
  streaming: boolean;
  reasoningDurationMs?: number;
  reasoningTokens?: number;
  activeLlmActivity?: LlmActivity | null;
}) {
  const [manualOpen, setManualOpen] = useState(false);
  const [liveReasoningDuration, setLiveReasoningDuration] = useState<{
    startedAt: string;
    durationMs: number;
  } | null>(null);
  const open = streaming || manualOpen;
  const liveThinkingStartedAt =
    streaming &&
    activeLlmActivity?.phase === "thinking" &&
    typeof activeLlmActivity.first_thinking_at === "string"
      ? activeLlmActivity.first_thinking_at
      : null;

  useEffect(() => {
    if (!liveThinkingStartedAt) {
      return;
    }

    const startedAt = Date.parse(liveThinkingStartedAt);
    if (Number.isNaN(startedAt)) {
      return;
    }

    const updateDuration = () => {
      setLiveReasoningDuration({
        startedAt: liveThinkingStartedAt,
        durationMs: Math.max(0, Date.now() - startedAt),
      });
    };

    const timeoutId = window.setTimeout(updateDuration, 0);
    const intervalId = window.setInterval(updateDuration, 100);
    return () => {
      window.clearTimeout(timeoutId);
      window.clearInterval(intervalId);
    };
  }, [liveThinkingStartedAt]);

  const shownDurationMs =
    liveThinkingStartedAt && liveReasoningDuration?.startedAt === liveThinkingStartedAt
      ? liveReasoningDuration.durationMs
      : reasoningDurationMs;
  const meta: string[] = [];
  if (typeof shownDurationMs === "number") {
    meta.push(`for ${formatDuration(shownDurationMs)}`);
  }
  if (typeof reasoningTokens === "number" && reasoningTokens > 0) {
    meta.push(`${reasoningTokens.toLocaleString()} reasoning`);
  }

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
          {streaming ? "thinking" : "thought"}
        </span>
        {meta.length > 0 && (
          <span className="min-w-0 truncate font-mono text-[11px] text-foreground/65 dark:text-foreground/70">
            {meta.join(", ")}
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

function MessageActionButton({
  label,
  icon,
  disabled,
  onClick,
}: {
  label: string;
  icon: React.ReactNode;
  disabled?: boolean;
  onClick?: () => void;
}) {
  if (!onClick) return null;

  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      aria-label={label}
      title={label}
      className={cn(
        "inline-flex items-center rounded-md border border-border/70 p-1.5 text-muted-foreground transition-colors",
        "hover:bg-accent hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50",
      )}
    >
      {icon}
    </button>
  );
}

function MessageActions({
  copyText,
  canRetry,
  canReset,
  disabled,
  onRetry,
  onReset,
}: {
  copyText?: string;
  canRetry?: boolean;
  canReset?: boolean;
  disabled?: boolean;
  onRetry?: () => void;
  onReset?: () => void;
}) {
  const hasCopy = typeof copyText === "string" && copyText.length > 0;
  if (!hasCopy && !canRetry && !canReset) return null;

  return (
    <div className="mt-2 flex items-center gap-2">
      <MessageCopyButton text={copyText ?? ""} className="border border-border/70 p-1.5" />
      <MessageActionButton
        label="Retry turn"
        icon={<RotateCcw className="size-3.5" />}
        disabled={disabled}
        onClick={canRetry ? onRetry : undefined}
      />
      <MessageActionButton
        label="Reset conversation to after this turn"
        icon={<Undo2 className="size-3.5" />}
        disabled={disabled}
        onClick={canReset ? onReset : undefined}
      />
    </div>
  );
}

interface MessageProps {
  message: ChatMessage;
  activeLlmActivity?: LlmActivity | null;
  canRetry?: boolean;
  canReset?: boolean;
  actionDisabled?: boolean;
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
  onRetry?: () => void;
  onReset?: () => void;
}

export function Message({
  message,
  activeLlmActivity,
  canRetry,
  canReset,
  actionDisabled,
  onApproval,
  onEscalation,
  onCredentialApproval,
  onRetry,
  onReset,
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
        <div className="group max-w-[85%] text-sm">
          <div className="min-w-0 flex-1">
            <MarkdownContent content={message.content} />
          </div>
          <MessageActions
            copyText={message.content}
            canRetry={canRetry}
            canReset={canReset}
            disabled={actionDisabled}
            onRetry={onRetry}
            onReset={onReset}
          />
        </div>
      );

    case "streaming":
      return (
        <div className="group flex max-w-[85%] items-start gap-1.5 text-sm">
          <div className="min-w-0 flex-1">
            <MarkdownContent content={message.content} />
          </div>
        </div>
      );

    case "thinking":
      return (
        <ThinkingBadge
          content={message.content}
          streaming={false}
          reasoningDurationMs={message.reasoningDurationMs}
          reasoningTokens={message.reasoningTokens}
        />
      );

    case "thinking_streaming":
      return (
        <ThinkingBadge
          content={message.content}
          streaming
          reasoningDurationMs={message.reasoningDurationMs}
          reasoningTokens={message.reasoningTokens}
          activeLlmActivity={activeLlmActivity}
        />
      );

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
        <div className="my-1 max-w-[85%] rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
          <pre className="whitespace-pre-wrap font-mono text-xs">{message.detail}</pre>
          <MessageActions
            copyText={message.detail}
            canRetry={canRetry}
            canReset={canReset}
            disabled={actionDisabled}
            onRetry={onRetry}
            onReset={onReset}
          />
        </div>
      );
  }
}
