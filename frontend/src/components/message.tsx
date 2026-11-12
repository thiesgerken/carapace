"use client";

import { AlertTriangle, Archive, Brain, Check, ChevronRight, Copy, GitBranch, Info, Loader2, Paperclip, Play, RotateCcw, Undo2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";

import type { ChatMessage, EscalationDecision, LlmActivity } from "@/lib/types";
import { ToolCallGroup, groupRenderItems } from "./tool-call-group";
import { useAppLocale } from "@/components/locale-provider";
import { MarkdownContent } from "./markdown-content";
import { FilePreview } from "./file-preview";
import { ToolCallBadge } from "./tool-call-badge";
import { ApprovalCard } from "./approval-card";
import { CredentialApprovalCard } from "./credential-approval-card";
import { DomainAccessApprovalCard } from "./domain-access-approval-card";
import { GitPushApprovalCard } from "./git-push-approval-card";
import { CommandResultView } from "./command-result";
import { cn } from "@/lib/utils";

function formatDuration(ms: number, locale: string, precise = true): string {
  // Decimals/ms only matter while the timer is live (responsive feel);
  // a finished block reads cleaner as whole seconds.
  if (!precise) return `${Math.max(1, Math.round(ms / 1_000))}s`;
  if (ms < 1_000) return `${ms}ms`;
  if (ms < 10_000) {
    const seconds = new Intl.NumberFormat(locale, {
      minimumFractionDigits: 1,
      maximumFractionDigits: 1,
    }).format(ms / 1_000);
    return `${seconds}s`;
  }
  return `${Math.round(ms / 1_000)}s`;
}

function formatRelativeTime(iso: string, locale: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const sec = Math.round((Date.now() - then) / 1_000);
  const rtf = new Intl.RelativeTimeFormat(locale, { numeric: "auto" });
  if (sec < 60) return rtf.format(-sec, "second");
  const min = Math.round(sec / 60);
  if (min < 60) return rtf.format(-min, "minute");
  const hr = Math.round(min / 60);
  if (hr < 24) return rtf.format(-hr, "hour");
  return rtf.format(-Math.round(hr / 24), "day");
}

function formatTokens(n: number, locale: string): string {
  if (n < 1_000) return new Intl.NumberFormat(locale).format(n);
  const k = n / 1_000;
  return `${new Intl.NumberFormat(locale, { maximumFractionDigits: k < 10 ? 1 : 0 }).format(k)}k`;
}

function shortModel(model: string): string {
  return model.includes(":") ? model.slice(model.indexOf(":") + 1) : model;
}

/**
 * Turn/timestamp metadata. A muted relative time is always shown (small, low-contrast); the
 * absolute time, turn number, duration, tool count and model/token usage sit behind its tooltip
 * so the resting line stays unintrusive.
 */
function TurnMeta({
  timestamp,
  turnIndex,
  messageIndexInTurn,
  turnMessageCount,
  turnDurationMs,
  toolCount,
  model,
  inputTokens,
  outputTokens,
  ttftMs,
  generationMs,
  className,
}: {
  timestamp?: string;
  turnIndex?: number;
  messageIndexInTurn?: number;
  turnMessageCount?: number;
  turnDurationMs?: number;
  toolCount?: number;
  model?: string;
  inputTokens?: number;
  outputTokens?: number;
  ttftMs?: number;
  generationMs?: number;
  className?: string;
}) {
  const { locale } = useAppLocale();
  const t = useTranslations("turnMeta");
  if (!timestamp && turnIndex == null) return null;
  const rel = timestamp ? formatRelativeTime(timestamp, locale) : "";
  // Date and time formatted separately and joined with a space, so there's no comma between them.
  const abs = timestamp
    ? `${new Date(timestamp).toLocaleDateString(locale, { dateStyle: "medium" })} ${new Date(
        timestamp,
      ).toLocaleTimeString(locale, { timeStyle: "short" })}`
    : "";
  const turnLabel = turnIndex != null ? t("turn", { n: turnIndex }) : "";
  const posLabel =
    messageIndexInTurn != null && turnMessageCount != null && turnMessageCount > 1
      ? t("messageInTurn", { i: messageIndexInTurn, n: turnMessageCount })
      : "";
  // tok/s = provider output tokens / generation seconds (tool waits excluded) — shown inline.
  const tps =
    typeof outputTokens === "number" && typeof generationMs === "number" && generationMs > 0
      ? Math.round((outputTokens / generationMs) * 1000)
      : undefined;

  const tipParts = [posLabel, turnLabel, abs];
  if (typeof turnDurationMs === "number") tipParts.push(formatDuration(turnDurationMs, locale, false));
  if (typeof toolCount === "number" && toolCount > 0) tipParts.push(t("tools", { count: toolCount }));
  if (model) tipParts.push(shortModel(model));
  if (typeof inputTokens === "number" && typeof outputTokens === "number") {
    tipParts.push(
      t("tokens", {
        in: formatTokens(inputTokens, locale),
        out: formatTokens(outputTokens, locale),
      }),
    );
  }
  if (typeof ttftMs === "number") tipParts.push(t("ttft", { value: formatDuration(ttftMs, locale, true) }));
  const tip = tipParts.filter(Boolean).join(" · ");

  const visible = [rel || turnLabel, tps != null ? t("tps", { n: tps }) : ""].filter(Boolean).join(" · ");
  return (
    <span
      title={tip}
      className={cn(
        "select-none whitespace-nowrap text-[10px] tabular-nums text-muted-foreground/50",
        className,
      )}
    >
      {visible}
    </span>
  );
}

function MessageCopyButton({
  text,
  className,
}: {
  text: string;
  className?: string;
}) {
  const t = useTranslations("message");
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
      aria-label={copied ? t("copied") : t("copy")}
      title={copied ? t("copied") : t("copy")}
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
  const t = useTranslations("message");
  const { locale } = useAppLocale();
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
    meta.push(
      t(
        streaming
          ? "thinkingMeta.durationStreaming"
          : "thinkingMeta.durationComplete",
        { duration: formatDuration(shownDurationMs, locale, streaming) },
      ),
    );
  }
  if (typeof reasoningTokens === "number" && reasoningTokens > 0) {
    meta.push(t("thinkingMeta.reasoning", { count: reasoningTokens.toLocaleString() }));
  }

  return (
    <div className="my-1 w-full min-w-0">
      <button
        type="button"
        onClick={() => setManualOpen((prev) => !prev)}
        className={cn(
          "flex w-full min-w-0 items-center gap-1.5 rounded-md px-2 py-1 text-xs text-left",
          "text-muted-foreground hover:bg-accent transition-colors",
          open && "bg-accent",
        )}
      >
        <ChevronRight
          className={cn(
            "h-3 w-3 shrink-0 transition-transform",
            open && "rotate-90",
          )}
        />
        {streaming ? (
          <Loader2 className="h-3 w-3 shrink-0 animate-spin text-foreground/65 dark:text-foreground/70" />
        ) : (
          <Brain className="h-3 w-3 shrink-0 text-foreground/65 dark:text-foreground/70" />
        )}
        <span className="shrink-0 font-medium text-foreground/85 dark:text-foreground/90">
          {streaming ? t("thinking.streaming") : t("thinking.complete")}
        </span>
        {meta.length > 0 && (
          <span className="min-w-0 flex-1 truncate font-mono text-[11px] text-foreground/60 dark:text-foreground/65">
            {meta.join(", ")}
          </span>
        )}
      </button>

      {open && (
        <div className="thinking-details tool-row-details ml-5 mt-1.5 rounded-lg border border-border/60 bg-muted/30 p-3 text-xs text-muted-foreground">
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
  canFork,
  canRetry,
  canReset,
  continueInsteadOfRetry,
  canContinue,
  disabled,
  onFork,
  onRetry,
  onReset,
  onContinue,
  timestamp,
  turnIndex,
  messageIndexInTurn,
  turnMessageCount,
  turnDurationMs,
  toolCount,
  model,
  inputTokens,
  outputTokens,
  ttftMs,
  generationMs,
  className,
}: {
  copyText?: string;
  canFork?: boolean;
  canRetry?: boolean;
  canReset?: boolean;
  /** On a turn's error row, which resumes on the kept history rather than rerunning the turn. */
  continueInsteadOfRetry?: boolean;
  canContinue?: boolean;
  disabled?: boolean;
  onFork?: () => void;
  onRetry?: () => void;
  onReset?: () => void;
  onContinue?: () => void;
  timestamp?: string;
  turnIndex?: number;
  messageIndexInTurn?: number;
  turnMessageCount?: number;
  turnDurationMs?: number;
  toolCount?: number;
  model?: string;
  inputTokens?: number;
  outputTokens?: number;
  ttftMs?: number;
  generationMs?: number;
  className?: string;
}) {
  const t = useTranslations("message");
  const hasCopy = typeof copyText === "string" && copyText.length > 0;
  const hasMeta = Boolean(timestamp) || turnIndex != null;
  if (!hasCopy && !canFork && !canRetry && !canContinue && !canReset && !hasMeta) return null;

  // Controls first, then the meta pushed to the far end of the row (spacer between spans the width).
  return (
    <div className={cn("mt-2 flex items-center gap-2", className)}>
      <MessageCopyButton text={copyText ?? ""} className="border border-border/70 p-1.5" />
      <MessageActionButton
        label={t("actions.fork")}
        icon={<GitBranch className="size-3.5" />}
        disabled={disabled}
        onClick={canFork ? onFork : undefined}
      />
      {continueInsteadOfRetry ? (
        <MessageActionButton
          label={t("actions.continue")}
          icon={<Play className="size-3.5" />}
          disabled={disabled}
          onClick={canContinue ? onContinue : undefined}
        />
      ) : (
        <MessageActionButton
          label={t("actions.retry")}
          icon={<RotateCcw className="size-3.5" />}
          disabled={disabled}
          onClick={canRetry ? onRetry : undefined}
        />
      )}
      <MessageActionButton
        label={t("actions.reset")}
        icon={<Undo2 className="size-3.5" />}
        disabled={disabled}
        onClick={canReset ? onReset : undefined}
      />
      <TurnMeta
        timestamp={timestamp}
        turnIndex={turnIndex}
        messageIndexInTurn={messageIndexInTurn}
        turnMessageCount={turnMessageCount}
        turnDurationMs={turnDurationMs}
        toolCount={toolCount}
        model={model}
        inputTokens={inputTokens}
        outputTokens={outputTokens}
        ttftMs={ttftMs}
        generationMs={generationMs}
        className="ml-auto"
      />
    </div>
  );
}

function FinalStatusNotice({ status }: { status: "success" | "warning" }) {
  const t = useTranslations("message");
  const isWarning = status === "warning";
  const statusLabel = isWarning
    ? t("finalStatus.status.warning")
    : t("finalStatus.status.success");

  return (
    <div
      className={cn(
        "mt-3 rounded-xl border px-3 py-2.5 text-sm",
        isWarning
          ? "border-amber-200 bg-amber-50 text-amber-900"
          : "border-sky-200 bg-sky-50 text-sky-900",
      )}
    >
      <div className="flex items-start gap-2">
        {isWarning ? (
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
        ) : (
          <Info className="mt-0.5 h-4 w-4 shrink-0" />
        )}
        <p>
          {t("finalStatus.notice", { status: statusLabel })}
        </p>
      </div>
    </div>
  );
}

/** Where the model's provider compacted the context server-side; earlier messages stay shown as they were. */
function ProviderCompactionMarker({
  message,
}: {
  message: Extract<ChatMessage, { kind: "provider_compaction" }>;
}) {
  const t = useTranslations("compaction");
  const [open, setOpen] = useState(false);
  return (
    <div className="my-1 w-full min-w-0">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className={cn(
          "flex w-full min-w-0 items-center gap-1.5 rounded-md px-1.5 py-0.5 text-[11px] text-left",
          "text-muted-foreground/80 hover:bg-accent transition-colors",
        )}
        title={t("providerTitle")}
        aria-expanded={open}
      >
        <Archive className="h-3 w-3 shrink-0 text-amber-600/70" />
        <span className="font-medium">{t("providerMarker", { provider: message.provider ?? "?" })}</span>
        <ChevronRight className={cn("ml-auto h-3 w-3 shrink-0 transition-transform", open && "rotate-90")} />
      </button>
      {open ? (
        <div className="mb-1.5 ml-5 mt-1 rounded-md border border-amber-500/30 bg-amber-500/5 p-2 text-[11px] text-muted-foreground">
          {message.summary ? (
            <>
              <p className="mb-1 text-[10px] font-medium uppercase tracking-wide opacity-70">{t("modelSummaryLabel")}</p>
              <div className="whitespace-pre-wrap break-words">{message.summary}</div>
            </>
          ) : (
            <p>{t("providerOpaque")}</p>
          )}
        </div>
      ) : null}
    </div>
  );
}

function CompactionSummaryBlock({
  message,
  server,
  sessionId,
  activeLlmActivity,
}: {
  message: Extract<ChatMessage, { kind: "compaction_summary" }>;
  server?: string;
  sessionId?: string;
  activeLlmActivity?: LlmActivity | null;
}) {
  const t = useTranslations("compaction");
  const [open, setOpen] = useState(false);
  const savings =
    message.origTokens != null && message.summaryTokens != null
      ? t("tokenDelta", { from: message.origTokens, to: message.summaryTokens })
      : null;
  return (
    <div className="relative my-1 w-full min-w-0">
      {/* Rail lives in the gutter (negative offset) so the originals are not shifted. */}
      <div
        aria-hidden
        className="pointer-events-none absolute -left-3 bottom-1 top-1 w-0.5 rounded bg-amber-500/40"
      />
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className={cn(
          "flex w-full min-w-0 items-center gap-1.5 rounded-md px-1.5 py-0.5 text-[11px] text-left",
          "text-muted-foreground/80 hover:bg-accent transition-colors",
        )}
        title={t("foldTitle")}
        aria-expanded={open}
      >
        <Archive className="h-3 w-3 shrink-0 text-amber-600/70" />
        <span className="font-medium">
          {t("railHeader", { count: message.turnCount })}
        </span>
        {savings ? <span className="opacity-70">· {savings}</span> : null}
        <span className="ml-auto flex shrink-0 items-center gap-0.5 opacity-80">
          {t("modelSees")}
          <ChevronRight
            className={cn("h-3 w-3 transition-transform", open && "rotate-90")}
          />
        </span>
      </button>
      {open && message.summary ? (
        <div className="mb-1.5 ml-5 mt-1 rounded-md border border-amber-500/30 bg-amber-500/5 p-2 text-[11px] text-muted-foreground">
          <p className="mb-1 text-[10px] font-medium uppercase tracking-wide opacity-70">
            {t("modelSummaryLabel")}
          </p>
          <div className="whitespace-pre-wrap break-words">{message.summary}</div>
        </div>
      ) : null}
      <div className="space-y-1">
        {(() => {
          const children = message.children;
          const renderChild = (idx: number) => (
            <Message
              key={idx}
              message={children[idx]}
              server={server}
              sessionId={sessionId}
              activeLlmActivity={activeLlmActivity}
            />
          );
          // Collapse runs of tool rows into a group, exactly like the live transcript.
          return groupRenderItems(children).map((item) =>
            item.type === "message" ? (
              renderChild(item.index)
            ) : (
              <ToolCallGroup
                key={`g-${item.start}`}
                items={item.indices.map((j) => children[j])}
                inProgress={false}
              >
                {item.indices.map((j) => renderChild(j))}
              </ToolCallGroup>
            ),
          );
        })()}
      </div>
    </div>
  );
}

interface MessageProps {
  message: ChatMessage;
  server?: string;
  sessionId?: string;
  activeLlmActivity?: LlmActivity | null;
  canFork?: boolean;
  canRetry?: boolean;
  canContinue?: boolean;
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
  onFork?: () => void;
  onRetry?: () => void;
  onContinue?: () => void;
  onReset?: () => void;
}

export function Message({
  message,
  server,
  sessionId,
  activeLlmActivity,
  canFork,
  canRetry,
  canContinue,
  canReset,
  actionDisabled,
  onApproval,
  onEscalation,
  onCredentialApproval,
  onFork,
  onRetry,
  onContinue,
  onReset,
}: MessageProps) {
  switch (message.kind) {
    case "user":
      return (
        <div className="group flex flex-col items-end">
          <div className="flex w-fit max-w-full flex-col items-end md:max-w-[85%]">
          <div
            className={cn(
              "chat-copy-serif max-w-full rounded-2xl rounded-br-md border border-border/60 bg-muted/30 px-3.5 py-2 text-sm text-foreground",
            )}
          >
            {message.content ? <MarkdownContent content={message.content} /> : null}
            {message.attachments && message.attachments.length > 0 ? (
              <div
                className={cn(
                  "flex flex-col items-end gap-1.5",
                  message.content ? "mt-2" : "",
                )}
              >
                {message.attachments.map((att) =>
                  att.file_id ? (
                    <FilePreview
                      key={att.file_id}
                      fileId={att.file_id}
                      name={att.name}
                      path={att.path}
                      mime={att.mime}
                      size={att.size}
                      server={server}
                      sessionId={sessionId}
                      className="w-full max-w-sm text-left"
                    />
                  ) : (
                    <span
                      key={att.path}
                      title={att.path}
                      className="flex items-center gap-1.5 rounded-lg border border-border bg-background/50 px-2 py-1 text-xs"
                    >
                      <Paperclip className="h-3 w-3 shrink-0" />
                      <span className="max-w-40 truncate">{att.name}</span>
                    </span>
                  ),
                )}
              </div>
            ) : null}
          </div>
          <MessageActions
            copyText={message.content}
            canFork={canFork}
            canRetry={canRetry}
            canReset={canReset}
            disabled={actionDisabled}
            onFork={onFork}
            onRetry={onRetry}
            onReset={onReset}
            timestamp={message.timestamp}
            turnIndex={message.turnIndex}
            className="w-full"
          />
          </div>
        </div>
      );

    case "assistant":
      return (
        <div className="group max-w-full text-sm md:max-w-[85%]">
          <div className="chat-copy-serif min-w-0 flex-1">
            <MarkdownContent content={message.content} />
            {message.finalStatus ? <FinalStatusNotice status={message.finalStatus} /> : null}
          </div>
          <MessageActions
            copyText={message.content}
            canFork={canFork}
            canRetry={canRetry}
            canReset={canReset}
            disabled={actionDisabled}
            onFork={onFork}
            onRetry={onRetry}
            onReset={onReset}
            timestamp={message.timestamp}
            turnIndex={message.turnIndex}
            messageIndexInTurn={message.messageIndexInTurn}
            turnMessageCount={message.turnMessageCount}
            turnDurationMs={message.turnDurationMs}
            toolCount={message.toolCount}
            model={message.model}
            inputTokens={message.inputTokens}
            outputTokens={message.outputTokens}
            ttftMs={message.ttftMs}
            generationMs={message.generationMs}
          />
        </div>
      );

    case "streaming":
      return (
        <div className="group flex max-w-full items-start gap-1.5 text-sm md:max-w-[85%]">
          <div className="chat-copy-serif min-w-0 flex-1">
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
          files={message.files}
          exitCode={message.exitCode}
          loading={message.loading}
          compaction={message.compaction}
          server={server}
          sessionId={sessionId}
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
            files: c.files,
            exitCode: c.exitCode,
            loading: c.loading,
            compaction: c.compaction,
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

    case "provider_compaction":
      return <ProviderCompactionMarker message={message} />;

    case "compaction_summary":
      return (
        <CompactionSummaryBlock
          message={message}
          server={server}
          sessionId={sessionId}
          activeLlmActivity={activeLlmActivity}
        />
      );

    case "command":
      return (
        <CommandResultView
          command={message.command}
          data={message.data}
          defaultExpanded={message.live}
        />
      );

    case "error":
      return (
        <div className="my-1 max-w-full rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive md:max-w-[85%]">
          <pre className="whitespace-pre-wrap font-mono text-xs">{message.detail}</pre>
          <MessageActions
            copyText={message.detail}
            canFork={canFork}
            canRetry={canRetry}
            canReset={canReset}
            continueInsteadOfRetry
            canContinue={canContinue}
            disabled={actionDisabled}
            onFork={onFork}
            onRetry={onRetry}
            onReset={onReset}
            onContinue={onContinue}
          />
        </div>
      );
  }
}
