"use client";

import { useTranslations } from "next-intl";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Archive, ArchiveRestore, Bot, Brain, Check, Copy, ExternalLink, Eye, Globe, Link2, Link2Off, Loader2, Lock, MessageSquare, Pin, Play, RotateCcw, Save, Settings2, Square, Star, Terminal, Trash2 } from "lucide-react";
import { EmojiText } from "@/components/emoji-text";
import { MemoryExtractionDrawer } from "@/components/memory-extraction-drawer";
import { SandboxGitControls } from "@/components/git-sync";
import { ModelPicker, withSelectedModelOption } from "@/components/model-picker";
import { SessionOptionTiles } from "@/components/session-option-tiles";
import { useAppLocale } from "@/components/locale-provider";
import { useAppShell } from "@/components/app-shell-context";
import { useSessionPresence } from "@/hooks/use-session-presence";
import { useWebSocket } from "@/hooks/use-websocket";
import {
  type AvailableModelInfo,
  commitSessionKnowledge,
  fetchCommands,
  fetchHistory,
  fetchSandbox,
  fetchModels,
  forkSession,
  getMemorySession,
  getWebSocketTicket,
  type SlashCommand,
  startSandbox,
  stopSandbox,
  updateSession,
  uploadSandboxFile,
  wipeSandbox,
  wsUrl,
} from "@/lib/api";
import type {
  Attachment,
  ChatMessage,
  ClientMessage,
  CompactionAnnotation,
  EscalationDecision,
  HistoryMessage,
  LlmActivity,
  SessionAttributesPatch,
  ServerMessage,
  SentFile,
  SessionInfo,
  SessionSandboxSnapshot,
  TurnUsage,
} from "@/lib/types";
import { isRecord } from "@/lib/decoding";
import { knowledgeBrowseHref } from "@/lib/knowledge-links";
import { getPresenceClientId } from "@/lib/storage";
import {
  canArchiveSession,
  cn,
  formatBytes,
  sandboxStatusIndicatorClass,
  sandboxStatusKey,
  shouldConfirmArchiveSession,
  sessionHasKnowledgeChanges,
} from "@/lib/utils";
import { Message } from "./message";
import { ToolCallGroup, groupRenderItems } from "./tool-call-group";
import { ChatInput } from "./chat-input";
import { AgentHistoryView } from "./agent-history-view";

interface ChatViewProps {
  server: string;
  token: string;
  sessionId: string;
  session: SessionInfo | null;
  initialSandbox?: SessionSandboxSnapshot | null;
  onTitleUpdate?: (title: string) => void;
  onSessionUpdate?: (session: SessionInfo) => void;
  onSandboxUpdate?: (sandbox: SessionSandboxSnapshot) => void;
  onForkSession?: (session: SessionInfo) => void;
  onOpenJobSettings?: (jobId: string) => void;
  onUpdateSessionAttributes?: (sessionId: string, attributes: SessionAttributesPatch) => Promise<SessionInfo>;
  onDeleteSession?: () => Promise<void>;
}

const SANDBOX_STARTUP_TOOL_NAMES = new Set(["use_skill", "read", "write", "str_replace", "exec", "send_file"]);

function sandboxStorageLabel(
  snapshot: SessionSandboxSnapshot | null,
  t: (key: string, values?: Record<string, string | number | Date>) => string,
): string {
  if (!snapshot) return "";
  if (snapshot.status === "missing" && !snapshot.storage_present) return "";
  const details: string[] = [];
  if (typeof snapshot.last_measured_used_bytes === "number") {
    details.push(t("sandbox.storage.used", { size: formatBytes(snapshot.last_measured_used_bytes) }));
  } else if (!snapshot.storage_present) {
    details.push(t("sandbox.storage.none"));
  }
  if (
    snapshot.runtime === "kubernetes"
    && typeof snapshot.provisioned_bytes === "number"
  ) {
    details.push(t("sandbox.storage.allocated", { size: formatBytes(snapshot.provisioned_bytes) }));
  }
  return details.join(" · ");
}

function sandboxIdentifier(snapshot: SessionSandboxSnapshot | null): string | null {
  const sandboxId = snapshot?.sandbox_id?.trim();
  return sandboxId ? sandboxId : null;
}

function thinkingUsageMeta(usage?: TurnUsage | null): {
  reasoningDurationMs?: number;
  reasoningTokens?: number;
} {
  const meta: {
    reasoningDurationMs?: number;
    reasoningTokens?: number;
  } = {};
  if (typeof usage?.reasoning_duration_ms === "number") {
    meta.reasoningDurationMs = usage.reasoning_duration_ms;
  }
  if (typeof usage?.reasoning_tokens === "number") {
    meta.reasoningTokens = usage.reasoning_tokens;
  }
  return meta;
}

function normalizedDecisionMessage(message?: string | null): string | undefined {
  if (message == null) return undefined;
  const trimmed = message.trim();
  return trimmed.length > 0 ? trimmed : undefined;
}

function errorDetail(
  error: unknown,
  t: (key: string, values?: Record<string, string | number | Date>) => string,
): string {
  if (error instanceof Error && error.message.trim().length > 0) {
    return error.message;
  }
  return t("errors.unexpected");
}

function formatArchiveTimestamp(
  iso: string | null | undefined,
  locale: string,
  t: (key: string, values?: Record<string, string | number | Date>) => string,
): string {
  if (!iso) return t("knowledge.notCommittedYet");
  const value = new Date(iso);
  if (Number.isNaN(value.getTime())) return t("knowledge.committed");
  return t("knowledge.savedAt", {
    timestamp: value.toLocaleString(locale, {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    }),
  });
}

function formatSessionTimestamp(
  iso: string | null | undefined,
  locale: string,
  t: (key: string, values?: Record<string, string | number | Date>) => string,
): string {
  if (!iso) return t("unknown");
  const value = new Date(iso);
  if (Number.isNaN(value.getTime())) return t("unknown");
  return value.toLocaleString(locale, {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatUsd(value: number, locale: string): string {
  return new Intl.NumberFormat(locale, {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: value < 0.01 ? 4 : 2,
    maximumFractionDigits: value < 0.01 ? 4 : 2,
  }).format(value);
}

function formatJobTriggerKind(
  triggerKind: "api" | "cron" | "manual",
  t: (key: string, values?: Record<string, string | number | Date>) => string,
): string {
  if (triggerKind === "api") return t("jobRun.trigger.api");
  if (triggerKind === "cron") return t("jobRun.trigger.cron");
  return t("jobRun.trigger.manual");
}

function formatSessionJobData(data?: string | null): { value: string; isJson: boolean } | null {
  if (typeof data !== "string") return null;
  if (data.trim().length === 0) return null;
  try {
    return { value: JSON.stringify(JSON.parse(data), null, 2), isJson: true };
  } catch {
    return { value: data, isJson: false };
  }
}

function knowledgeStatusBadge(
  session: SessionInfo | null,
  hasKnowledgeChanges: boolean,
  t: (key: string, values?: Record<string, string | number | Date>) => string,
): { label: string; className: string; icon: typeof Archive } {
  const isInKnowledgeRepo = Boolean(
    session?.knowledge_last_committed_at || session?.knowledge_last_archive_path,
  );

  if (session?.attributes.private && !isInKnowledgeRepo) {
    return {
      label: t("knowledge.badges.excluded"),
      className: "border-zinc-300 bg-zinc-100 text-zinc-700",
      icon: Lock,
    };
  }

  if (!isInKnowledgeRepo) {
    return {
      label: t("knowledge.badges.missing"),
      className: "border-slate-300 bg-slate-100 text-slate-700",
      icon: Archive,
    };
  }

  if (hasKnowledgeChanges) {
    return {
      label: t("knowledge.badges.outdated"),
      className: "border-amber-300 bg-amber-50 text-amber-700",
      icon: RotateCcw,
    };
  }

  return {
    label: t("knowledge.badges.upToDate"),
    className: "border-emerald-300 bg-emerald-50 text-emerald-700",
    icon: Save,
  };
}

function localizedSessionSourceInfo(
  session: SessionInfo | null,
  t: (key: string, values?: Record<string, string | number | Date>) => string,
): {
  label: string;
  icon: typeof Globe;
} {
  if (!session) {
    return { label: t("source.unknown"), icon: MessageSquare };
  }
  if (session.channel_type === "job") {
    return { label: t("source.job"), icon: Bot };
  }
  if (session.channel_type === "web") {
    return { label: t("source.web"), icon: Globe };
  }
  if (session.channel_type === "cli") {
    return { label: t("source.cli"), icon: Terminal };
  }
  return { label: session.channel_type, icon: MessageSquare };
}

function sessionSourceJobId(session: SessionInfo | null): string | null {
  if (session?.channel_type !== "job") return null;
  if (!session.channel_ref?.startsWith("job:")) return null;
  const jobId = session.channel_ref.slice("job:".length).trim();
  return jobId.length > 0 ? jobId : null;
}

function optimisticPendingSandbox(
  snapshot: SessionSandboxSnapshot | null,
): SessionSandboxSnapshot {
  return {
    exists: snapshot?.exists ?? false,
    runtime: snapshot?.runtime,
    status: "pending",
    sandbox_id: snapshot?.sandbox_id,
    resource_id: snapshot?.resource_id,
    resource_kind: snapshot?.resource_kind,
    storage_present: snapshot?.storage_present ?? false,
    provisioned_bytes: snapshot?.provisioned_bytes,
    last_measured_used_bytes: snapshot?.last_measured_used_bytes,
    last_measured_at: snapshot?.last_measured_at,
    updated_at: new Date().toISOString(),
    last_error: null,
  };
}

function shouldOptimisticallyShowPendingSandbox(
  tool: string,
  snapshot: SessionSandboxSnapshot | null,
): boolean {
  if (!SANDBOX_STARTUP_TOOL_NAMES.has(tool)) {
    return false;
  }
  return snapshot?.status !== "running" && snapshot?.status !== "pending";
}

function shouldShowStartSandbox(snapshot: SessionSandboxSnapshot | null): boolean {
  if (!snapshot) return true;
  return snapshot.status === "missing"
    || snapshot.status === "scaled_down"
    || snapshot.status === "stopped"
    || snapshot.status === "error";
}

function argsMatch(
  left: Record<string, unknown>,
  right: Record<string, unknown>,
): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

/** A run of consecutive tool/thinking messages, collapsed into one summary. */
function applyDeniedApprovalToMessages(
  messages: ChatMessage[],
  request: {
    tool: string;
    args: Record<string, unknown>;
  },
  message?: string,
): ChatMessage[] {
  const decisionMessage = normalizedDecisionMessage(message);
  const updated = [...messages];
  for (let index = updated.length - 1; index >= 0; index--) {
    const entry = updated[index];
    if (
      entry.kind === "tool_call" &&
      entry.tool === request.tool &&
      entry.approvalVerdict === "escalate" &&
      argsMatch(entry.args, request.args)
    ) {
      updated[index] = {
        ...entry,
        approvalSource: "user",
        approvalVerdict: "deny",
        approvalExplanation: decisionMessage ? entry.approvalExplanation : undefined,
        decisionMessage,
        loading: false,
      };
      break;
    }
  }
  return updated;
}

function applyApprovedApprovalToMessages(
  messages: ChatMessage[],
  request: {
    tool: string;
    args: Record<string, unknown>;
  },
  loading = false,
): ChatMessage[] {
  const updated = [...messages];
  for (let index = updated.length - 1; index >= 0; index--) {
    const entry = updated[index];
    if (
      entry.kind === "tool_call" &&
      entry.tool === request.tool &&
      entry.approvalVerdict === "escalate" &&
      argsMatch(entry.args, request.args)
    ) {
      updated[index] = {
        ...entry,
        approvalSource: "user",
        approvalVerdict: "allow",
        approvalExplanation: undefined,
        decisionMessage: undefined,
        loading,
      };
      break;
    }
  }
  return updated;
}

function isUserApprovedReplay(
  tool: string,
  detail: string | undefined,
  approvalSource: ChatMessage extends never ? never :
    | "safe-list"
    | "sentinel"
    | "user"
    | "skill"
    | "bypass"
    | "unknown"
    | undefined,
  approvalVerdict: "allow" | "deny" | "escalate" | undefined,
): boolean {
  return (
    approvalSource === "user" &&
    approvalVerdict === "allow" &&
    detail === "[user approved]" &&
    (tool === "exec" || tool === "use_skill")
  );
}

type ToolCallMessage = Extract<ChatMessage, { kind: "tool_call" }>;
type ToolCallChildMessage = NonNullable<ToolCallMessage["children"]>[number];

function isToolCallLoading(
  tool: string,
  approvalSource?:
    | "safe-list"
    | "sentinel"
    | "user"
    | "skill"
    | "bypass"
    | "unknown",
  approvalVerdict?: "allow" | "deny" | "escalate",
): boolean {
  const isGitPush = tool === "git_push";
  if (
    tool === "proxy_domain" ||
    tool === "credential_access" ||
    isGitPush
  ) {
    return false;
  }
  if (approvalSource === "sentinel" && approvalVerdict == null) {
    return true;
  }
  return approvalVerdict === "allow";
}

function updateToolCallMessageById(
  messages: ChatMessage[],
  toolId: string,
  updater: (message: ToolCallMessage | ToolCallChildMessage) =>
    | ToolCallMessage
    | ToolCallChildMessage,
): { messages: ChatMessage[]; found: boolean } {
  let found = false;
  const updated = messages.map((entry) => {
    if (entry.kind !== "tool_call") return entry;

    if (entry.toolId === toolId) {
      found = true;
      return updater(entry) as ToolCallMessage;
    }

    if (!entry.children?.length) return entry;

    let childChanged = false;
    const children = entry.children.map((child) => {
      if (child.toolId !== toolId) return child;
      found = true;
      childChanged = true;
      return updater(child) as ToolCallChildMessage;
    });

    return childChanged ? { ...entry, children } : entry;
  });

  return { messages: found ? updated : messages, found };
}

function updateToolResultById(
  messages: ChatMessage[],
  toolId: string,
  result: {
    result: string;
    exitCode?: number;
    files?: SentFile[];
    compaction?: CompactionAnnotation;
  },
): { messages: ChatMessage[]; found: boolean } {
  return updateToolCallMessageById(messages, toolId, (entry) => ({
    ...entry,
    result: result.result,
    files: result.files,
    exitCode: result.exitCode,
    loading: false,
    compaction:
      result.compaction
      ?? (entry as { compaction?: CompactionAnnotation }).compaction,
  }));
}

function normalizeOptionalString(value: unknown): string | undefined {
  return typeof value === "string" ? value : undefined;
}

function normalizeStringList(value: unknown): string[] | undefined {
  if (!Array.isArray(value)) return undefined;
  return value.filter((entry): entry is string => typeof entry === "string");
}

function normalizeToolArgs(args: unknown): Record<string, unknown> {
  return isRecord(args) ? args : {};
}

function normalizeHistoryContexts(message: HistoryMessage): string[] | undefined {
  const directContexts = normalizeStringList(message.contexts);
  if (directContexts) return directContexts;
  return normalizeStringList(normalizeToolArgs(message.args).contexts);
}

function findLaterEscalationDecision(
  history: HistoryMessage[],
  fromIndex: number,
  requestId: string,
  roleMatches: (role: string) => boolean,
): EscalationDecision | undefined {
  for (let index = fromIndex + 1; index < history.length; index++) {
    const entry = history[index];
    if (entry.request_id !== requestId || !roleMatches(entry.role)) continue;
    const decision = entry.decision;
    if (decision === "allow" || decision === "deny") return decision;
  }
  return undefined;
}

function isTurnTerminalMessage(message: ChatMessage): boolean {
  // A turn ends at its final assistant answer, never at intermediate narration (partial), so
  // reset/fork/retry stay anchored to real turn boundaries (matching the backend event log).
  return (
    (message.kind === "assistant" && !message.partial)
    || (message.kind === "error" && message.turnTerminal === true)
  );
}

/**
 * The message index of the assistant answer that terminates the turn enclosing `from` (the nearest
 * turn-terminal at or after it), or undefined while that turn is still in progress. Lets any message
 * — a user prompt, an intermediate bubble — drive fork/reset, snapping to its turn boundary.
 */
function enclosingTurnTerminalMessageIndex(
  messages: ChatMessage[],
  from: number,
): number | undefined {
  for (let index = from; index < messages.length; index++) {
    if (isTurnTerminalMessage(messages[index])) return index;
  }
  return undefined;
}

function completedTurnMessageIndices(messages: ChatMessage[]): number[] {
  return messages.flatMap((message, index) => (isTurnTerminalMessage(message) ? [index] : []));
}

function latestCompletedTurnStartMessageIndex(messages: ChatMessage[]): number {
  const latestTerminalIndex = completedTurnMessageIndices(messages).at(-1);
  if (latestTerminalIndex == null) {
    return messages.length;
  }

  for (let index = latestTerminalIndex; index >= 0; index--) {
    const message = messages[index];
    if (message.kind === "user" && !message.content.startsWith("/")) {
      return index;
    }
  }

  return messages.length;
}

function eventIndexForMessage(message: ChatMessage): number | undefined {
  if (message.kind === "assistant" || message.kind === "error" || message.kind === "user") {
    return typeof message.eventIndex === "number" ? message.eventIndex : undefined;
  }
  return undefined;
}

/** Any persisted message's event, for deep-link anchors (wider than the fork/reset targets above). */
function anchorEventIndex(message: ChatMessage): number | undefined {
  return "eventIndex" in message && typeof message.eventIndex === "number" ? message.eventIndex : undefined;
}

function groupChildToolCalls(messages: ChatMessage[]): ChatMessage[] {
  const parentIndex = new Map<string, number>();
  for (let index = 0; index < messages.length; index++) {
    const message = messages[index];
    if (message.kind === "tool_call" && message.toolId) {
      parentIndex.set(message.toolId, index);
    }
  }

  const childIndices = new Set<number>();
  for (let index = 0; index < messages.length; index++) {
    const message = messages[index];
    if (message.kind !== "tool_call" || !message.parentToolId) continue;

    const parentMessageIndex = parentIndex.get(message.parentToolId);
    if (parentMessageIndex == null) continue;

    const parent = messages[parentMessageIndex];
    if (parent.kind !== "tool_call") continue;

    if (!parent.children) parent.children = [];
    parent.children.push(message);
    childIndices.add(index);
  }

  return childIndices.size > 0
    ? messages.filter((_, index) => !childIndices.has(index))
    : messages;
}

function foldNodeOf(message: ChatMessage): string | undefined {
  if (
    message.kind === "user"
    || message.kind === "assistant"
    || message.kind === "tool_call"
  ) {
    return message.compaction?.folded_into;
  }
  return undefined;
}

function foldAnnotationOf(message: ChatMessage): CompactionAnnotation | undefined {
  if (
    message.kind === "user"
    || message.kind === "assistant"
    || message.kind === "tool_call"
  ) {
    return message.compaction;
  }
  return undefined;
}

/**
 * Wrap each run of folded messages (same node) in a rail group. Originals stay inline and
 * expanded — the rail just marks the span and exposes the model-facing summary on demand.
 */
function groupFoldedMessages(messages: ChatMessage[]): ChatMessage[] {
  const out: ChatMessage[] = [];
  let i = 0;
  while (i < messages.length) {
    const node = foldNodeOf(messages[i]);
    if (!node) {
      out.push(messages[i]);
      i++;
      continue;
    }
    const children: ChatMessage[] = [];
    let annotation: CompactionAnnotation | undefined;
    while (i < messages.length && foldNodeOf(messages[i]) === node) {
      annotation = annotation ?? foldAnnotationOf(messages[i]);
      children.push(messages[i]);
      i++;
    }
    out.push({
      kind: "compaction_summary",
      nodeId: node,
      foldedCount: children.length,
      turnCount: children.filter((c) => c.kind === "user").length || 1,
      summary: annotation?.summary,
      origTokens: annotation?.orig_tokens,
      summaryTokens: annotation?.summary_tokens,
      children,
    });
  }
  return out;
}

function projectHistoryToMessages(history: HistoryMessage[]): ChatMessage[] {
  const messages: ChatMessage[] = [];
  const pendingToolCallIndices = new Map<string, number[]>();
  // Turn = one submitted (non-slash) user prompt plus the agent work that follows it.
  let turn = 0;
  let turnStartTs: string | undefined;
  let turnToolCount = 0;

  for (let index = 0; index < history.length; index++) {
    const entry = history[index];

    if (entry.role === "user") {
      if (!entry.content.startsWith("/")) turn++;
      turnStartTs = entry.timestamp;
      turnToolCount = 0;
      messages.push({
        kind: "user",
        content: entry.content,
        attachments: entry.attachments,
        compaction: entry.compaction,
        timestamp: entry.timestamp,
        turnIndex: turn,
        eventIndex: typeof entry.event_index === "number" ? entry.event_index : undefined,
      });
      continue;
    }

    if (entry.role === "tool_call") turnToolCount++;

    if (entry.role === "tool_call") {
      const tool = entry.tool ?? "";
      const args = normalizeToolArgs(entry.args);
      const loading = isToolCallLoading(
        tool,
        entry.approval_source,
        entry.approval_verdict,
      );

      if (
        isUserApprovedReplay(
          tool,
          entry.detail,
          entry.approval_source,
          entry.approval_verdict,
        )
      ) {
        const patched = applyApprovedApprovalToMessages(
          messages,
          { tool, args },
          loading,
        );
        messages.length = 0;
        messages.push(...patched);
        continue;
      }

      messages.push({
        kind: "tool_call",
        tool,
        args,
        detail: entry.detail ?? "",
        contexts: normalizeHistoryContexts(entry),
        approvalSource: entry.approval_source,
        approvalVerdict: entry.approval_verdict,
        approvalExplanation: entry.approval_explanation,
        loading,
        toolId: normalizeOptionalString(entry.tool_id),
        parentToolId: normalizeOptionalString(entry.parent_tool_id),
        compaction: entry.compaction,
        eventIndex: typeof entry.event_index === "number" ? entry.event_index : undefined,
      });

      const queue = pendingToolCallIndices.get(tool) ?? [];
      queue.push(messages.length - 1);
      pendingToolCallIndices.set(tool, queue);
      continue;
    }

    if (entry.role === "tool_result") {
      const toolResultId = normalizeOptionalString(entry.tool_id);
      if (toolResultId) {
        const updated = updateToolResultById(messages, toolResultId, {
          result: entry.result ?? "",
          files: entry.files,
          exitCode: entry.exit_code,
          compaction: entry.compaction,
        });
        if (updated.found) {
          messages.length = 0;
          messages.push(...updated.messages);
          continue;
        }
      }

      const toolName = entry.tool ?? "";
      const queue = pendingToolCallIndices.get(toolName);
      const toolIndex = queue?.shift();
      if (toolIndex != null && messages[toolIndex]?.kind === "tool_call") {
        const toolCall = messages[toolIndex];
        messages[toolIndex] = {
          ...toolCall,
          result: entry.result,
          files: entry.files,
          exitCode: entry.exit_code,
          loading: false,
          compaction: entry.compaction ?? toolCall.compaction,
        };
      }
      if (queue && queue.length === 0) {
        pendingToolCallIndices.delete(toolName);
      }
      continue;
    }

    if (entry.role === "approval_response") {
      continue;
    }

    if (entry.role === "approval_request" && entry.tool_call_id) {
      const request = {
        type: "approval_request" as const,
        tool_call_id: entry.tool_call_id,
        tool: entry.tool ?? "",
        args: normalizeToolArgs(entry.args),
        explanation: entry.explanation ?? "",
        risk_level: entry.risk_level ?? "",
      };
      const response = history.find(
        (candidate) =>
          candidate.role === "approval_response"
          && candidate.tool_call_id === entry.tool_call_id,
      );
      if (!response) {
        messages.push({ kind: "approval", request });
      } else if (response.decision === "approved") {
        const patched = applyApprovedApprovalToMessages(messages, request);
        messages.length = 0;
        messages.push(...patched);
      } else if (response.decision === "denied") {
        const patched = applyDeniedApprovalToMessages(
          messages,
          request,
          response.message,
        );
        messages.length = 0;
        messages.push(...patched);
      }
      continue;
    }

    if (
      (entry.role === "domain_access_approval"
        || entry.role === "proxy_approval")
      && entry.request_id
    ) {
      if (!entry.decision) {
        const decision = findLaterEscalationDecision(
          history,
          index,
          entry.request_id,
          (role) =>
            role === "domain_access_approval" || role === "proxy_approval",
        );
        if (!decision) {
          messages.push({
            kind: "domain_access_approval",
            request: {
              type: "domain_access_approval_request",
              request_id: entry.request_id,
              domain: entry.domain ?? "",
              command: entry.command ?? "",
            },
            decision,
          });
        }
      }
      continue;
    }

    if (entry.role === "git_push_approval" && entry.request_id) {
      if (!entry.decision) {
        const decision = findLaterEscalationDecision(
          history,
          index,
          entry.request_id,
          (role) => role === "git_push_approval",
        );
        if (!decision) {
          messages.push({
            kind: "git_push_approval",
            request: {
              type: "git_push_approval_request",
              request_id: entry.request_id,
              ref: entry.ref ?? "",
              explanation: entry.explanation ?? "",
              changed_files: normalizeStringList(entry.changed_files) ?? [],
            },
            decision,
          });
        }
      }
      continue;
    }

    if (entry.role === "credential_approval" && entry.request_id) {
      if (!entry.decision) {
        const decision = findLaterEscalationDecision(
          history,
          index,
          entry.request_id,
          (role) => role === "credential_approval",
        );
        if (!decision) {
          messages.push({
            kind: "credential_approval",
            request: {
              type: "credential_approval_request",
              request_id: entry.request_id,
              vault_paths: normalizeStringList(entry.vault_paths) ?? [],
              names: normalizeStringList(entry.names) ?? [],
              descriptions: normalizeStringList(entry.descriptions) ?? [],
              skill_name: normalizeOptionalString(entry.skill_name),
              explanation: entry.explanation ?? "",
            },
            decision,
          });
        }
      }
      continue;
    }

    if (entry.role === "git_push") {
      messages.push({
        kind: "tool_call",
        tool: "git_push",
        args: { ref: entry.ref ?? "", decision: entry.decision ?? "" },
        detail: entry.detail ?? "",
        approvalSource: entry.approval_source,
        approvalVerdict: entry.approval_verdict,
        approvalExplanation: entry.approval_explanation,
        toolId: normalizeOptionalString(entry.tool_id),
        parentToolId: normalizeOptionalString(entry.parent_tool_id),
        eventIndex: typeof entry.event_index === "number" ? entry.event_index : undefined,
      });
      continue;
    }

    if (entry.role === "command") {
      messages.push({
        kind: "command",
        command: entry.command ?? "",
        data: entry.data,
      });
      continue;
    }

    if (entry.role === "thinking" && entry.content) {
      messages.push({
        kind: "thinking",
        content: entry.content,
        reasoningDurationMs: entry.reasoning_duration_ms,
        reasoningTokens: entry.reasoning_tokens,
      });
      continue;
    }

    const isPartial = entry.partial === true;
    const durationMs =
      turnStartTs && entry.timestamp
        ? new Date(entry.timestamp).getTime() - new Date(turnStartTs).getTime()
        : undefined;
    messages.push({
      kind: "assistant",
      content: entry.content,
      finalStatus: entry.final_status,
      eventIndex: typeof entry.event_index === "number" ? entry.event_index : undefined,
      compaction: entry.compaction,
      timestamp: entry.timestamp,
      turnIndex: turn,
      partial: isPartial || undefined,
      // Whole-turn stats belong on the final answer, not on intermediate narration.
      turnDurationMs:
        !isPartial && typeof durationMs === "number" && durationMs >= 0 ? durationMs : undefined,
      toolCount: !isPartial ? turnToolCount || undefined : undefined,
      model: !isPartial ? (entry.usage?.model ?? undefined) : undefined,
      inputTokens: !isPartial ? entry.usage?.input_tokens : undefined,
      outputTokens: !isPartial ? entry.usage?.output_tokens : undefined,
      ttftMs: !isPartial ? (entry.usage?.ttft_ms ?? undefined) : undefined,
      generationMs: !isPartial ? (entry.usage?.generation_ms ?? undefined) : undefined,
    });
  }

  // Number assistant bubbles within each turn ("message 2 of 3") for the metadata tooltip.
  const assistantIdxByTurn = new Map<number, number[]>();
  messages.forEach((m, i) => {
    if (m.kind === "assistant" && m.turnIndex != null) {
      const arr = assistantIdxByTurn.get(m.turnIndex) ?? [];
      arr.push(i);
      assistantIdxByTurn.set(m.turnIndex, arr);
    }
  });
  assistantIdxByTurn.forEach((indices) => {
    indices.forEach((i, k) => {
      const m = messages[i];
      if (m.kind === "assistant") {
        m.messageIndexInTurn = k + 1;
        m.turnMessageCount = indices.length;
      }
    });
  });

  return groupFoldedMessages(groupChildToolCalls(messages));
}

export function countSubmittedUserMessages(messages: ChatMessage[]): number {
  return messages.filter(
    (message) => message.kind === "user" && !message.content.startsWith("/"),
  ).length;
}

export function nextUnattendedInputLockBaseline({
  previousSessionId,
  sessionId,
  previousUnattended,
  sessionUnattended,
  previousBaseline,
  submittedUserMessageCount,
}: {
  previousSessionId: string;
  sessionId: string;
  previousUnattended: boolean;
  sessionUnattended: boolean;
  previousBaseline: number | null;
  submittedUserMessageCount: number;
}): number | null {
  if (!sessionUnattended) {
    return null;
  }
  if (previousSessionId !== sessionId) {
    return 0;
  }
  if (!previousUnattended) {
    return submittedUserMessageCount;
  }
  return previousBaseline ?? 0;
}

export function isUnattendedInputLocked(
  sessionUnattended: boolean,
  submittedUserMessageCount: number,
  baseline: number | null,
): boolean {
  if (!sessionUnattended) {
    return false;
  }
  return submittedUserMessageCount > (baseline ?? 0);
}

export function ChatView({
  server,
  token,
  sessionId,
  session,
  initialSandbox,
  onTitleUpdate,
  onSessionUpdate,
  onSandboxUpdate,
  onForkSession,
  onOpenJobSettings,
  onUpdateSessionAttributes,
  onDeleteSession,
}: ChatViewProps) {
  const t = useTranslations("chatView");
  const tc = useTranslations("compaction");
  const tRoot = useTranslations();
  const { locale } = useAppLocale();
  const { currentUser } = useAppShell();
  const agentName = currentUser?.agentName?.trim() || tRoot("app.name");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [waiting, setWaiting] = useState(false);
  const [queuedMessage, setQueuedMessage] = useState<string | null>(null);
  const [usage, setUsage] = useState<TurnUsage | null>(null);
  const [llmActivity, setLlmActivity] = useState<LlmActivity | null>(null);
  const [loadingHistory, setLoadingHistory] = useState(true);
  const [agentViewOpen, setAgentViewOpen] = useState(false);
  const [commands, setCommands] = useState<SlashCommand[]>([]);
  const [availableModelEntries, setAvailableModelEntries] = useState<
    AvailableModelInfo[]
  >([]);
  const [sandbox, setSandbox] = useState<SessionSandboxSnapshot | null>(
    initialSandbox ?? null,
  );
  const [sandboxLoading, setSandboxLoading] = useState(false);
  const [sandboxPowerAction, setSandboxPowerAction] = useState<"starting" | "stopping" | null>(null);
  const [wipingSandbox, setWipingSandbox] = useState(false);
  const [deletingSession, setDeletingSession] = useState(false);
  const [savingKnowledge, setSavingKnowledge] = useState(false);
  const [mobileInspectorOpen, setMobileInspectorOpen] = useState(false);
  const [sessionIdCopied, setSessionIdCopied] = useState(false);
  const [updatingSessionAttribute, setUpdatingSessionAttribute] = useState<"archived" | "private" | "pinned" | "favorite" | "mode" | null>(null);
  const [showDelayedSessionAttributeStatus, setShowDelayedSessionAttributeStatus] = useState(false);
  const [updatingSessionModel, setUpdatingSessionModel] = useState<"agent" | "sentinel" | null>(null);
  const [modelsUnlocked, setModelsUnlocked] = useState(false);
  const [modelUpdateError, setModelUpdateError] = useState<string | null>(null);
  const [turnActionBusyIndex, setTurnActionBusyIndex] = useState<number | null>(null);
  const [knowledgeNotice, setKnowledgeNotice] = useState<{
    tone: "neutral" | "success" | "error";
    message: string;
  } | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const mobileInspectorTouchStartRef = useRef<{ x: number; y: number } | null>(null);
  const isAtBottomRef = useRef(true);
  const targetEvent = useSearchParams().get("event");
  const scrolledToEventRef = useRef<string | null>(null);
  const [hasMemory, setHasMemory] = useState(false);
  const [memoryDrawerOpen, setMemoryDrawerOpen] = useState(false);
  const lastThinkingStartedAtRef = useRef<string | null>(null);
  const queueRef = useRef<string | null>(null);
  const queuedAttachmentsRef = useRef<Attachment[]>([]);
  const resetRollbackRef = useRef<ChatMessage[] | null>(null);
  // Monotonic id for the on-done history re-projection so only the newest turn's refetch applies
  // (older async responses are dropped, preventing duplicate/missing bubbles when turns overlap).
  const doneRefetchSeqRef = useRef(0);
  const sendRef = useRef<(msg: ClientMessage) => void>(() => {});
  const onSandboxUpdateRef = useRef(onSandboxUpdate);
  const sandboxRef = useRef(sandbox);
  const previousSessionIdRef = useRef(sessionId);
  const previousSessionUnattendedRef = useRef(session?.attributes.unattended ?? false);
  const unattendedInputLockBaselineRef = useRef<number | null>(
    session?.attributes.unattended ? 0 : null,
  );

  useEffect(() => {
    if (updatingSessionAttribute == null) {
      setShowDelayedSessionAttributeStatus(false);
      return;
    }

    const timeoutId = window.setTimeout(() => {
      setShowDelayedSessionAttributeStatus(true);
    }, 200);

    return () => {
      window.clearTimeout(timeoutId);
      setShowDelayedSessionAttributeStatus(false);
    };
  }, [updatingSessionAttribute]);
  const sandboxRefreshParamsRef = useRef({ server, token, sessionId });
  const sandboxRefreshPendingRef = useRef(false);
  const sandboxRefreshRunningRef = useRef(false);
  const sandboxRefreshEpochRef = useRef(0);

  useEffect(() => {
    onSandboxUpdateRef.current = onSandboxUpdate;
  }, [onSandboxUpdate]);

  const markSessionKnowledgeChanged = useCallback((hasNewMessage = false) => {
    if (!session) return;
    onSessionUpdate?.({
      ...session,
      last_active: new Date().toISOString(),
      message_count: hasNewMessage ? Math.max(session.message_count, 1) : session.message_count,
    });
  }, [onSessionUpdate, session]);

  useEffect(() => {
    sandboxRef.current = sandbox;
  }, [sandbox]);

  useEffect(() => {
    sandboxRefreshParamsRef.current = { server, token, sessionId };
    sandboxRefreshEpochRef.current += 1;
  }, [server, sessionId, token]);

  useEffect(() => {
    setMobileInspectorOpen(false);
  }, [sessionId]);

  useEffect(() => {
    setModelUpdateError(null);
  }, [sessionId]);

  useEffect(() => {
    setModelsUnlocked(false);
  }, [sessionId]);

  const handleMobileInspectorTouchStart = useCallback((event: React.TouchEvent<HTMLDivElement>) => {
    const touch = event.touches[0];
    mobileInspectorTouchStartRef.current = { x: touch.clientX, y: touch.clientY };
  }, []);

  const handleMobileInspectorTouchEnd = useCallback((event: React.TouchEvent<HTMLDivElement>) => {
    const start = mobileInspectorTouchStartRef.current;
    if (!start) return;

    mobileInspectorTouchStartRef.current = null;
    const touch = event.changedTouches[0];
    const dx = Math.abs(touch.clientX - start.x);
    const dy = touch.clientY - start.y;

    if (dy > 48 && dy > dx) {
      setMobileInspectorOpen(false);
    }
  }, []);

  // Fetch available slash commands and models on mount
  useEffect(() => {
    fetchCommands(server, token).then(setCommands);
    fetchModels(server, token).then(setAvailableModelEntries);
  }, [server, token]);

  const applySandboxSnapshot = useCallback((nextSandbox: SessionSandboxSnapshot) => {
    setSandbox(nextSandbox);
    onSandboxUpdateRef.current?.(nextSandbox);
  }, []);

  const refreshSandbox = useCallback(async () => {
    sandboxRefreshPendingRef.current = true;
    if (sandboxRefreshRunningRef.current) return;

    sandboxRefreshRunningRef.current = true;
    try {
      while (sandboxRefreshPendingRef.current) {
        sandboxRefreshPendingRef.current = false;
        const refreshEpoch = sandboxRefreshEpochRef.current;
        const {
          server: currentServer,
          token: currentToken,
          sessionId: currentSessionId,
        } = sandboxRefreshParamsRef.current;

        setSandboxLoading(true);
        try {
          const nextSandbox = await fetchSandbox(currentServer, currentToken, currentSessionId);
          if (refreshEpoch !== sandboxRefreshEpochRef.current) {
            continue;
          }
          applySandboxSnapshot(nextSandbox);
        } catch (error) {
          if (refreshEpoch === sandboxRefreshEpochRef.current) {
            console.error("Failed to refresh sandbox", error);
          }
        } finally {
          if (refreshEpoch === sandboxRefreshEpochRef.current && !sandboxRefreshPendingRef.current) {
            setSandboxLoading(false);
          }
        }
      }
    } finally {
      sandboxRefreshRunningRef.current = false;
      setSandboxLoading(false);
    }
  }, [applySandboxSnapshot]);

  useEffect(() => {
    void refreshSandbox();
  }, [refreshSandbox, sessionId, server, token]);

  // Load history on mount
  useEffect(() => {
    let cancelled = false;

    fetchHistory(server, token, sessionId)
      .then((history) => {
        if (cancelled) return;
        setMessages(projectHistoryToMessages(history));
      })
      .catch(() => {
        // history fetch can fail for new sessions - that's fine
      })
      .finally(() => {
        if (!cancelled) setLoadingHistory(false);
      });

    return () => {
      cancelled = true;
    };
    // sessionId excluded: component remounts (via key) on session change
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [server, token]);

  // Clear the loading spinner on any tool_call messages still pending
  const clearToolLoading = useCallback(() => {
    setMessages((prev) => {
      if (!prev.some((m) => m.kind === "tool_call" && m.loading)) return prev;
      return prev.map((m) =>
        m.kind === "tool_call" && m.loading ? { ...m, loading: false } : m,
      );
    });
  }, []);

  // Flush a queued message if present, otherwise mark as not-waiting
  const finishWaiting = useCallback(() => {
    clearToolLoading();
    const queued = queueRef.current;
    if (queued !== null || queuedAttachmentsRef.current.length > 0) {
      const queuedAttachments = queuedAttachmentsRef.current;
      queueRef.current = null;
      queuedAttachmentsRef.current = [];
      setQueuedMessage(null);
      sendRef.current({
        type: "message",
        content: queued ?? "",
        attachments: queuedAttachments,
      });
      markSessionKnowledgeChanged();
      // stay in waiting state
    } else {
      setWaiting(false);
    }
  }, [clearToolLoading, markSessionKnowledgeChanged]);

  const snapshotThinkingDurationMs = useCallback((): number | undefined => {
    const startedAt = lastThinkingStartedAtRef.current;
    if (!startedAt) return undefined;
    const parsed = Date.parse(startedAt);
    if (Number.isNaN(parsed)) return undefined;
    return Math.max(0, Date.now() - parsed);
  }, []);

  const finalizeThinkingMessages = useCallback((messages: ChatMessage[]): ChatMessage[] => {
    const updated = [...messages];
    const thinkIdx = updated.findIndex((m) => m.kind === "thinking_streaming");
    if (thinkIdx !== -1) {
      const thinking = updated[thinkIdx] as Extract<ChatMessage, { kind: "thinking_streaming" }>;
      updated[thinkIdx] = {
        kind: "thinking",
        content: thinking.content,
        reasoningDurationMs:
          thinking.reasoningDurationMs ?? snapshotThinkingDurationMs(),
        reasoningTokens: thinking.reasoningTokens,
      };
    }
    return updated;
  }, [snapshotThinkingDurationMs]);

  const onMessage = useCallback(
    (msg: ServerMessage) => {
      switch (msg.type) {
        case "done": {
          resetRollbackRef.current = null;
          let doneBaselineLen = 0;
          setMessages((prev) => {
            const updated = [...prev];
            const thinkingMeta = thinkingUsageMeta(msg.usage);
            const currentStreamIdx = updated.findLastIndex((m) => m.kind === "streaming");
            // Finalize thinking: update thinking_streaming or existing thinking with authoritative content
            const thinkStreamIdx = updated.findIndex((m) => m.kind === "thinking_streaming");
            if (thinkStreamIdx !== -1) {
              updated[thinkStreamIdx] = {
                kind: "thinking",
                content: msg.thinking ?? (updated[thinkStreamIdx] as { content: string }).content,
                ...thinkingMeta,
              };
            } else if (msg.thinking) {
              const thinkIdx =
                currentStreamIdx > 0 && updated[currentStreamIdx - 1].kind === "thinking"
                  ? currentStreamIdx - 1
                  : updated.length > 0 && updated[updated.length - 1].kind === "thinking"
                    ? updated.length - 1
                    : -1;
              if (thinkIdx !== -1) {
                updated[thinkIdx] = { kind: "thinking", content: msg.thinking, ...thinkingMeta };
              } else if (currentStreamIdx !== -1) {
                updated.splice(currentStreamIdx, 0, {
                  kind: "thinking",
                  content: msg.thinking,
                  ...thinkingMeta,
                });
              } else {
                updated.push({ kind: "thinking", content: msg.thinking, ...thinkingMeta });
              }
            }
            // Finalize every streaming bubble (intermediate text emitted before a tool call) into a
            // partial assistant message. The final answer was streamed only if the last streaming
            // bubble is the tail — no tool call after it. Otherwise the answer arrived only in the
            // done payload (e.g. a structured/unattended output that never streamed tokens); the
            // streamed bubbles are all narration, so append the answer as its own message. Matches
            // what reload rebuilds from events.
            const lastStreamIdx = updated.findLastIndex((m) => m.kind === "streaming");
            const finalWasStreamed =
              lastStreamIdx !== -1
              && !updated.slice(lastStreamIdx + 1).some((m) => m.kind === "tool_call");
            for (let i = 0; i < updated.length; i++) {
              if (updated[i].kind !== "streaming") continue;
              updated[i] =
                finalWasStreamed && i === lastStreamIdx
                  ? { kind: "assistant", content: msg.content, finalStatus: msg.final_status }
                  : { kind: "assistant", content: (updated[i] as { content: string }).content, partial: true };
            }
            if (!finalWasStreamed) {
              // The backend always persists a final assistant event (even empty), so append it
              // unconditionally to keep the live transcript in step with the reloaded event log.
              updated.push({ kind: "assistant", content: msg.content, finalStatus: msg.final_status });
            }
            doneBaselineLen = updated.length;
            return updated;
          });
          // The live transcript can't carry persisted-only metadata (timestamps, event indices,
          // per-turn numbering, usage / tok-s). Re-project from the now-persisted event log so the
          // finished turn shows the same data as a reload, preserving any tail that arrived since.
          // Sequence-guard so a slower earlier refetch can't clobber a newer turn's projection.
          const refetchSeq = ++doneRefetchSeqRef.current;
          fetchHistory(server, token, sessionId)
            .then((history) => {
              if (refetchSeq !== doneRefetchSeqRef.current) return;
              setMessages((prev) => [
                ...projectHistoryToMessages(history),
                ...prev.slice(doneBaselineLen),
              ]);
            })
            .catch(() => {
              // Refetch failed — keep the live transcript; metadata fills in on the next reload.
            });
          if (msg.usage) setUsage(msg.usage);
          void refreshSandbox();
          setLlmActivity(null);
          lastThinkingStartedAtRef.current = null;
          finishWaiting();
          break;
        }
        case "tool_call": {
          const isGitPush = msg.tool === "git_push";
          if (!isGitPush) setWaiting(true); // agent is active (may restore after reconnect)
          const currentSandbox = sandboxRef.current;
          if (shouldOptimisticallyShowPendingSandbox(msg.tool, currentSandbox)) {
            applySandboxSnapshot(optimisticPendingSandbox(currentSandbox));
          }
          const isLoading = isToolCallLoading(
            msg.tool,
            msg.approval_source,
            msg.approval_verdict,
          );
          const rawContexts = msg.contexts ?? msg.args?.contexts;
          const newMsg: ChatMessage = {
            kind: "tool_call",
            tool: msg.tool,
            args: msg.args,
            detail: msg.detail,
            contexts: Array.isArray(rawContexts)
              ? (rawContexts as string[])
              : undefined,
            approvalSource: msg.approval_source,
            approvalVerdict: msg.approval_verdict,
            approvalExplanation: msg.approval_explanation,
            loading: isLoading,
            toolId: msg.tool_id,
            parentToolId: msg.parent_tool_id,
          };
          if (
            isUserApprovedReplay(
              msg.tool,
              msg.detail,
              msg.approval_source,
              msg.approval_verdict,
            )
          ) {
            setMessages((prev) =>
              applyApprovedApprovalToMessages(
                finalizeThinkingMessages(prev),
                { tool: msg.tool, args: msg.args },
                isLoading,
              ),
            );
            break;
          }
          if (msg.tool_id) {
            setMessages((prev) => {
              const withThinkingFinalized = finalizeThinkingMessages(prev);
              const updated = updateToolCallMessageById(withThinkingFinalized, msg.tool_id!, (entry) => ({
                ...entry,
                ...newMsg,
              }));
              if (updated.found) return updated.messages;

              if (msg.parent_tool_id) {
                for (let i = withThinkingFinalized.length - 1; i >= 0; i--) {
                  const m = withThinkingFinalized[i];
                  if (m.kind === "tool_call" && m.toolId === msg.parent_tool_id) {
                    const next = [...withThinkingFinalized];
                    next[i] = {
                      ...m,
                      children: [...(m.children ?? []), newMsg],
                    };
                    return next;
                  }
                }
              }

              return [...withThinkingFinalized, newMsg];
            });
            if (isGitPush) finishWaiting();
            break;
          }
          if (msg.parent_tool_id) {
            // Attach to parent tool call
            setMessages((prev) => {
              const updated = finalizeThinkingMessages(prev);
              for (let i = updated.length - 1; i >= 0; i--) {
                const m = updated[i];
                if (m.kind === "tool_call" && m.toolId === msg.parent_tool_id) {
                  updated[i] = {
                    ...m,
                    children: [...(m.children ?? []), newMsg],
                  };
                  return updated;
                }
              }
              // Parent not found — render top-level
              return [...updated, newMsg];
            });
          } else {
            setMessages((prev) => [...finalizeThinkingMessages(prev), newMsg]);
          }
          if (isGitPush) finishWaiting();
          break;
        }
        case "tool_result":
          setWaiting(true);
          setMessages((prev) => {
            if (msg.tool_id) {
              const updatedById = updateToolResultById(prev, msg.tool_id, {
                result: msg.result,
                files: msg.files,
                exitCode: msg.exit_code,
              });
              if (updatedById.found) return updatedById.messages;
            }

            const updated = [...prev];
            for (let i = updated.length - 1; i >= 0; i--) {
              const m = updated[i];
              if (m.kind === "tool_call" && m.loading && m.tool === msg.tool) {
                updated[i] = {
                  ...m,
                  result: msg.result,
                  files: msg.files,
                  exitCode: msg.exit_code,
                  loading: false,
                };
                break;
              }
            }
            return updated;
          });
          if (sandboxRef.current?.status === "pending") {
            void refreshSandbox();
          }
          break;
        case "approval_request":
          setWaiting(true);
          setMessages((prev) => [...prev, { kind: "approval", request: msg }]);
          break;
        case "domain_access_approval_request":
          setWaiting(true);
          setMessages((prev) => [
            ...prev,
            { kind: "domain_access_approval", request: msg },
          ]);
          break;
        case "git_push_approval_request":
          setWaiting(true);
          setMessages((prev) => [
            ...prev,
            { kind: "git_push_approval", request: msg },
          ]);
          break;
        case "credential_approval_request":
          setWaiting(true);
          setMessages((prev) => [
            ...prev,
            { kind: "credential_approval", request: msg },
          ]);
          break;
        case "command_result":
          resetRollbackRef.current = null;
          if (msg.command === "reset_to_turn") {
            break;
          }
          let compactBaselineLen = 0;
          setMessages((prev) => {
            const next: ChatMessage[] = [
              ...prev,
              { kind: "command", command: msg.command, data: msg.data, live: true },
            ];
            compactBaselineLen = next.length;
            return next;
          });
          if (msg.command === "compact" || msg.command === "uncompact") {
            // History was rewritten server-side; re-project so folds/badges render.
            // The refetched transcript already includes this command event. Preserve any live
            // messages that arrived during the async fetch (the tail past the command result) so
            // the refetch does not clobber them with an older snapshot.
            fetchHistory(server, token, sessionId)
              .then((history) =>
                setMessages((prev) => [
                  ...projectHistoryToMessages(history),
                  ...prev.slice(compactBaselineLen),
                ]),
              )
              .catch(() => {
                // Refetch failed — the transcript is stale vs the server's compacted state.
                setMessages((prev) => [
                  ...prev,
                  { kind: "error", detail: t("errors.compactRefresh") },
                ]);
              });
          }
          setLlmActivity(null);
          lastThinkingStartedAtRef.current = null;
          finishWaiting();
          break;
        case "error":
          setMessages((prev) => {
            const rollback = resetRollbackRef.current;
            resetRollbackRef.current = null;
            if (rollback !== null) {
              return [
                ...rollback,
                { kind: "error", detail: msg.detail, turnTerminal: msg.turn_terminal === true },
              ];
            }
            return [
              ...prev,
              { kind: "error", detail: msg.detail, turnTerminal: msg.turn_terminal === true },
            ];
          });
          setLlmActivity(null);
          lastThinkingStartedAtRef.current = null;
          finishWaiting();
          break;
        case "cancelled":
          resetRollbackRef.current = null;
          setMessages((prev) => [
            ...prev,
            { kind: "error", detail: msg.detail, turnTerminal: true },
          ]);
          setLlmActivity(null);
          lastThinkingStartedAtRef.current = null;
          finishWaiting();
          break;
        case "llm_activity":
          setLlmActivity(msg.activity ?? null);
          if (typeof msg.activity?.first_thinking_at === "string") {
            lastThinkingStartedAtRef.current = msg.activity.first_thinking_at;
          } else if (msg.activity?.phase === "processing_prompt") {
            lastThinkingStartedAtRef.current = null;
          }
          break;
        case "session_title":
          onTitleUpdate?.(msg.title);
          if (msg.usage) setUsage(msg.usage);
          break;
        case "status":
          if (msg.agent_running) setWaiting(true);
          if (msg.usage) setUsage(msg.usage);
          setLlmActivity(msg.llm_activity ?? null);
          if (typeof msg.llm_activity?.first_thinking_at === "string") {
            lastThinkingStartedAtRef.current = msg.llm_activity.first_thinking_at;
          } else if (msg.llm_activity?.phase === "processing_prompt") {
            lastThinkingStartedAtRef.current = null;
          }
          break;
        case "user_message":
          resetRollbackRef.current = null;
          // Slash commands end with command_result (no agent); echo must not re-arm waiting
          // after command_result cleared it (message order / batching).
          if (!msg.content.startsWith("/")) {
            setWaiting(true);
          }
          setMessages((prev) => [
            ...prev,
            { kind: "user", content: msg.content, attachments: msg.attachments },
          ]);
          break;
        case "token":
          setWaiting(true);
          setMessages((prev) => {
            const updated = finalizeThinkingMessages(prev);
            const lastIdx = updated.length - 1;
            if (lastIdx >= 0 && updated[lastIdx].kind === "streaming") {
              updated[lastIdx] = {
                kind: "streaming",
                content: (updated[lastIdx] as { content: string }).content + msg.content,
              };
            } else {
              updated.push({ kind: "streaming", content: msg.content });
            }
            return updated;
          });
          break;
        case "thinking":
          setWaiting(true);
          setMessages((prev) => {
            if (prev.length > 0 && prev[prev.length - 1].kind === "thinking_streaming") {
              const last = prev[prev.length - 1] as {
                kind: "thinking_streaming";
                content: string;
                reasoningDurationMs?: number;
                reasoningTokens?: number;
              };
              return [
                ...prev.slice(0, -1),
                {
                  kind: "thinking_streaming",
                  content: last.content + msg.content,
                  reasoningDurationMs: last.reasoningDurationMs,
                  reasoningTokens: last.reasoningTokens,
                },
              ];
            }
            return [...prev, { kind: "thinking_streaming", content: msg.content }];
          });
          break;
      }
    },
    [applySandboxSnapshot, finalizeThinkingMessages, finishWaiting, onTitleUpdate, refreshSandbox, server, token, sessionId, t],
  );

  const onWsDisconnect = useCallback(() => {
    resetRollbackRef.current = null;
    queueRef.current = null;
    queuedAttachmentsRef.current = [];
    lastThinkingStartedAtRef.current = null;
    setQueuedMessage(null);
    clearToolLoading();
    setWaiting(false);
  }, [clearToolLoading]);
  const presenceClientId = useRef(getPresenceClientId()).current;
  const [webSocketTicket, setWebSocketTicket] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    setWebSocketTicket(null);
    getWebSocketTicket(server, token)
      .then((ticket) => {
        if (!cancelled) setWebSocketTicket(ticket);
      })
      .catch(() => {
        if (!cancelled) setWebSocketTicket(null);
      });
    return () => {
      cancelled = true;
    };
  }, [server, token]);
  const url = webSocketTicket ? wsUrl(server, sessionId, token, presenceClientId, webSocketTicket) : null;
  const { status, send } = useWebSocket(url, onMessage, onWsDisconnect);
  useSessionPresence(server, token, sessionId, status, presenceClientId);
  useEffect(() => {
    sendRef.current = send;
  }, [send]);

  const terminalIndices = completedTurnMessageIndices(messages);
  const latestTerminalIndex = terminalIndices.length > 0 ? terminalIndices[terminalIndices.length - 1] : -1;
  const turnActionsDisabled = waiting || loadingHistory || status !== "connected" || turnActionBusyIndex !== null;

  useEffect(() => {
    let cancelled = false;
    getMemorySession(server, sessionId)
      .then((detail) => {
        if (!cancelled) setHasMemory(detail?.current != null);
      })
      // The chip is optional chrome: a failing memory API must not disturb the chat.
      .catch((memoryError: unknown) => {
        console.warn("Memory chip unavailable", memoryError);
        if (!cancelled) setHasMemory(false);
      });
    return () => {
      cancelled = true;
    };
  }, [server, sessionId]);

  // Deep link from memory fact sources (?event=<seq>). Not every event renders (approvals,
  // collapsed tool groups), so land on the nearest rendered anchor at or before the seq.
  useEffect(() => {
    if (targetEvent === null || loadingHistory || targetEvent === scrolledToEventRef.current) return;
    const target = Number(targetEvent);
    const anchors = Array.from(scrollRef.current?.querySelectorAll<HTMLElement>("[data-event-index]") ?? []);
    // DOM order is event order, so the last anchor at or before the target is the closest.
    const anchor = anchors.filter((element) => Number(element.dataset.eventIndex) <= target).at(-1);
    if (!anchor) return;
    scrolledToEventRef.current = targetEvent;
    isAtBottomRef.current = false;
    anchor.scrollIntoView({ block: "center" });
    anchor.animate?.([{ backgroundColor: "color-mix(in oklch, var(--accent) 80%, transparent)" }, { backgroundColor: "transparent" }], { duration: 2000 });
  }, [targetEvent, loadingHistory, messages]);

  // Auto-scroll only when already at bottom
  useEffect(() => {
    if (isAtBottomRef.current) {
      const element = scrollRef.current;
      if (!element) return;
      element.scrollTop = element.scrollHeight;
    }
  }, [messages]);

  const handleScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const threshold = 64;
    isAtBottomRef.current =
      el.scrollHeight - el.scrollTop - el.clientHeight < threshold;
  }, []);

  const uploadFile = useCallback(
    (
      file: File,
      opts?: { onProgress?: (fraction: number) => void; signal?: AbortSignal },
    ) => uploadSandboxFile(server, sessionId, file, opts ?? {}),
    [server, sessionId],
  );

  function handleSend(content: string, attachments: Attachment[] = []) {
    resetRollbackRef.current = null;
    if (waiting) {
      queueRef.current = content;
      queuedAttachmentsRef.current = attachments;
      // Surface the queued state even for attachment-only sends so the banner shows and
      // the composer's submit guard blocks a second send from silently overwriting it.
      setQueuedMessage(
        content || attachments.map((a) => a.name).join(", "),
      );
    } else {
      lastThinkingStartedAtRef.current = null;
      send({ type: "message", content, attachments });
      markSessionKnowledgeChanged(true);
      setWaiting(true);
    }
  }

  function handleInterrupt(content: string) {
    resetRollbackRef.current = null;
    queueRef.current = content;
    queuedAttachmentsRef.current = [];
    setQueuedMessage(content);
    send({ type: "cancel" });
  }

  function handleRetry() {
    if (waiting || status !== "connected") return;
    const currentMessages = messages;
    const startIndex = latestCompletedTurnStartMessageIndex(messages);
    if (startIndex >= messages.length) return;

    resetRollbackRef.current = currentMessages;
    queueRef.current = null;
    queuedAttachmentsRef.current = [];
    setQueuedMessage(null);
    lastThinkingStartedAtRef.current = null;
    setLlmActivity(null);
    setMessages((prev) => prev.slice(0, startIndex));
    setWaiting(true);
    send({ type: "retry_latest_turn" });
  }

  async function resolveTurnTargetEventIndex(messageIndex: number): Promise<number | undefined> {
    const currentMessages = messages;
    // Event-granular: each message carries its own event index, so reset/fork cut exactly here
    // (the backend keeps the older turns compacted and rebuilds the cut turn verbatim).
    const own = eventIndexForMessage(currentMessages[messageIndex]);
    if (own != null) return own;

    // Live message not yet persisted (no event index): refetch and align by position — once the
    // turn is on disk the reprojection has the same shape, so the same index resolves.
    const history = await fetchHistory(server, token, sessionId);
    const canonicalMessages = projectHistoryToMessages(history);
    const candidate = canonicalMessages[messageIndex];
    if (candidate != null && candidate.kind === currentMessages[messageIndex].kind) {
      return eventIndexForMessage(candidate);
    }
    return undefined;
  }

  async function handleReset(messageIndex: number) {
    if (waiting || status !== "connected") return;

    const currentMessages = messages;
    setTurnActionBusyIndex(messageIndex);
    try {
      const targetEventIndex = await resolveTurnTargetEventIndex(messageIndex);

      if (targetEventIndex == null) {
        setMessages((prev) => [
          ...prev,
          { kind: "error", detail: t("errors.resetTarget") },
        ]);
        return;
      }

      resetRollbackRef.current = currentMessages;
      send({ type: "reset_to_turn", event_index: targetEventIndex });
      // Cut exactly at the clicked message — mid-turn resets keep the bubbles up to here.
      setMessages((prev) => prev.slice(0, messageIndex + 1));
    } finally {
      setTurnActionBusyIndex(null);
    }
  }

  async function handleFork(messageIndex: number) {
    if (waiting || status !== "connected" || !onForkSession) return;

    setTurnActionBusyIndex(messageIndex);
    try {
      const targetEventIndex = await resolveTurnTargetEventIndex(messageIndex);
      if (targetEventIndex == null) {
        setMessages((prev) => [
          ...prev,
          { kind: "error", detail: t("errors.forkTarget") },
        ]);
        return;
      }

      const forked = await forkSession(server, token, sessionId, {
        eventIndex: targetEventIndex,
        channelType: "web",
        unattended: session?.attributes.unattended ? false : undefined,
      });
      onForkSession(forked);
    } catch (error) {
      setMessages((prev) => [...prev, { kind: "error", detail: errorDetail(error, t) }]);
    } finally {
      setTurnActionBusyIndex(null);
    }
  }

  async function handleWipeSandbox() {
    if (waiting || sandboxPowerAction || wipingSandbox || deletingSession) return;
    if (!window.confirm(t("confirm.wipeSandbox"))) {
      return;
    }
    setWipingSandbox(true);
    try {
      const nextSandbox = await wipeSandbox(server, token, sessionId);
      applySandboxSnapshot(nextSandbox);
    } catch (error) {
      console.error("Failed to wipe sandbox", error);
      setMessages((prev) => [...prev, { kind: "error", detail: errorDetail(error, t) }]);
    } finally {
      setWipingSandbox(false);
    }
  }

  async function handleSandboxPowerAction() {
    if (waiting || sandboxPowerAction || wipingSandbox || deletingSession) return;

    const currentSandbox = sandboxRef.current;
    const shouldStart = shouldShowStartSandbox(currentSandbox);
    if (!shouldStart && !window.confirm(t("confirm.scaleDownSandbox"))) {
      return;
    }

    setSandboxPowerAction(shouldStart ? "starting" : "stopping");
    try {
      if (shouldStart) {
        applySandboxSnapshot(optimisticPendingSandbox(currentSandbox));
        const nextSandbox = await startSandbox(server, token, sessionId);
        applySandboxSnapshot(nextSandbox);
      } else {
        const nextSandbox = await stopSandbox(server, token, sessionId);
        applySandboxSnapshot(nextSandbox);
      }
    } catch (error) {
      console.error(`Failed to ${shouldStart ? "start" : "scale down"} sandbox`, error);
      setMessages((prev) => [...prev, { kind: "error", detail: errorDetail(error, t) }]);
      void refreshSandbox();
    } finally {
      setSandboxPowerAction(null);
    }
  }

  async function handleDeleteSession() {
    if (waiting || sandboxPowerAction || wipingSandbox || deletingSession || !onDeleteSession) return;
    if (
      (session?.message_count ?? 0) > 0
      && !window.confirm(t("confirm.deleteSession"))
    ) {
      return;
    }
    setDeletingSession(true);
    try {
      await onDeleteSession();
    } finally {
      setDeletingSession(false);
    }
  }

  async function handleToggleArchived() {
    if (!session || updatingSessionAttribute || deletingSession || !onUpdateSessionAttributes) return;

    const nextArchived = !session.attributes.archived;
    if (nextArchived && !canArchiveSession(session)) {
      return;
    }
    if (nextArchived) {
      if (shouldConfirmArchiveSession(session) && !window.confirm(t("confirm.archiveSession"))) {
        return;
      }
    } else if (!window.confirm(t("confirm.unarchiveSession"))) {
      return;
    }

    setUpdatingSessionAttribute("archived");
    try {
      const updated = await onUpdateSessionAttributes(sessionId, { archived: nextArchived });
      onSessionUpdate?.(updated);
    } finally {
      setUpdatingSessionAttribute(null);
    }
  }

  async function handleCommitKnowledge() {
    if (!session || session.attributes.private || session.attributes.archived || waiting || savingKnowledge || deletingSession) return;

    setSavingKnowledge(true);
    setKnowledgeNotice(null);
    try {
      const result = await commitSessionKnowledge(server, token, sessionId);
      onSessionUpdate?.(result.session);
      setKnowledgeNotice({
        tone: result.committed ? "success" : "neutral",
        message:
          result.reason
          ?? (result.committed_at ? formatArchiveTimestamp(result.committed_at, locale, t) : t("knowledge.committedToRepo")),
      });
    } catch (error) {
      setKnowledgeNotice({ tone: "error", message: errorDetail(error, t) });
    } finally {
      setSavingKnowledge(false);
    }
  }

  async function handleTogglePrivacy() {
    if (!session || updatingSessionAttribute || deletingSession) return;

    const nextPrivate = !session.attributes.private;
    if (
      nextPrivate
      && session.knowledge_last_committed_at
      && !window.confirm(t("confirm.makePrivate"))
    ) {
      return;
    }

    setUpdatingSessionAttribute("private");
    setKnowledgeNotice(null);
    try {
      const updated = onUpdateSessionAttributes
        ? await onUpdateSessionAttributes(sessionId, { private: nextPrivate })
        : await updateSession(server, token, sessionId, { attributes: { private: nextPrivate } });
      onSessionUpdate?.(updated);
      setKnowledgeNotice({
        tone: "neutral",
        message: nextPrivate
          ? updated.knowledge_last_committed_at
            ? t("knowledge.privateExistingCommits")
            : t("knowledge.privateExcluded")
          : t("knowledge.includedInRepo"),
      });
    } catch (error) {
      setKnowledgeNotice({ tone: "error", message: errorDetail(error, t) });
    } finally {
      setUpdatingSessionAttribute(null);
    }
  }

  async function handleTogglePinned() {
    if (!session || updatingSessionAttribute || deletingSession || !onUpdateSessionAttributes) return;

    setUpdatingSessionAttribute("pinned");
    try {
      const updated = await onUpdateSessionAttributes(sessionId, { pinned: !session.attributes.pinned });
      onSessionUpdate?.(updated);
    } finally {
      setUpdatingSessionAttribute(null);
    }
  }

  async function handleToggleFavorite() {
    if (!session || updatingSessionAttribute || deletingSession || !onUpdateSessionAttributes) return;

    setUpdatingSessionAttribute("favorite");
    try {
      const updated = await onUpdateSessionAttributes(sessionId, { favorite: !session.attributes.favorite });
      onSessionUpdate?.(updated);
    } finally {
      setUpdatingSessionAttribute(null);
    }
  }

  async function handleToggleSessionMode(mode: "ask" | "yolo" | "unattended") {
    if (!session || updatingSessionAttribute || deletingSession || !onUpdateSessionAttributes) return;

    const nextAttributes: SessionAttributesPatch = mode === "ask"
      ? session.attributes.ask_mode
        ? { ask_mode: false }
        : { ask_mode: true, yolo_mode: false }
      : mode === "yolo"
        ? session.attributes.yolo_mode
          ? { yolo_mode: false }
          : { yolo_mode: true, ask_mode: false }
        : { unattended: !session.attributes.unattended };

    if (Object.entries(nextAttributes).every(([key, value]) => session.attributes[key as keyof SessionAttributesPatch] === value)) {
      return;
    }

    setUpdatingSessionAttribute("mode");
    try {
      const updated = await onUpdateSessionAttributes(sessionId, nextAttributes);
      onSessionUpdate?.(updated);
    } finally {
      setUpdatingSessionAttribute(null);
    }
  }

  async function handleUpdateSessionModel(modelType: "agent" | "sentinel", value: string | null) {
    if (!session || updatingSessionModel || waiting || deletingSession || sessionArchived) {
      return;
    }

    const currentAgentValue = session.agent_model_name ?? null;
    const currentSentinelValue = session.sentinel_model_name ?? null;
    const nextAgentValue = !modelsUnlocked || modelType === "agent" ? value : currentAgentValue;
    const nextSentinelValue = !modelsUnlocked || modelType === "sentinel" ? value : currentSentinelValue;
    const patch: { agent_model_name?: string | null; sentinel_model_name?: string | null } = {};

    if (nextAgentValue !== currentAgentValue) {
      patch.agent_model_name = nextAgentValue;
    }
    if (nextSentinelValue !== currentSentinelValue) {
      patch.sentinel_model_name = nextSentinelValue;
    }
    if (Object.keys(patch).length === 0) {
      return;
    }

    setUpdatingSessionModel(modelType);
    setModelUpdateError(null);
    try {
      const updated = await updateSession(server, token, sessionId, patch);
      onSessionUpdate?.(updated);
    } catch (error) {
      setModelUpdateError(errorDetail(error, t));
    } finally {
      setUpdatingSessionModel(null);
    }
  }

  function handleApproval(
    toolCallId: string,
    approved: boolean,
    responseMessage?: string,
  ) {
    const normalizedMessage = normalizedDecisionMessage(responseMessage);
    send({
      type: "approval_response",
      tool_call_id: toolCallId,
      approved,
      message: normalizedMessage,
    });
    markSessionKnowledgeChanged();
    setMessages((prev) => {
        let request: { tool: string; args: Record<string, unknown> } | null = null;
        const withoutApproval = prev.filter((entry) => {
          if (entry.kind === "approval" && entry.request.tool_call_id === toolCallId) {
            request = { tool: entry.request.tool, args: entry.request.args };
            return false;
          }
          return true;
        });
        if (!approved && request) {
          return applyDeniedApprovalToMessages(
            withoutApproval,
            request,
            normalizedMessage,
          );
        }
        if (approved && request) {
          return applyApprovedApprovalToMessages(withoutApproval, request);
        }
        return withoutApproval;
      });
  }

  function handleEscalation(
    requestId: string,
    decision: EscalationDecision,
    responseMessage?: string,
  ) {
    send({
      type: "escalation_response",
      request_id: requestId,
      decision,
      message: normalizedDecisionMessage(responseMessage),
    });
    markSessionKnowledgeChanged();
    setMessages((prev) =>
      prev.filter(
        (m) =>
          !(
            (m.kind === "domain_access_approval" ||
              m.kind === "git_push_approval") &&
            m.request.request_id === requestId
          ),
      ),
    );
  }

  function handleCredentialEscalation(
    requestId: string,
    decision: EscalationDecision,
    responseMessage?: string,
  ) {
    send({
      type: "escalation_response",
      request_id: requestId,
      decision,
      message: normalizedDecisionMessage(responseMessage),
    });
    markSessionKnowledgeChanged();
    setMessages((prev) =>
      prev.filter(
        (m) =>
          !(
            m.kind === "credential_approval" &&
            m.request.request_id === requestId
          ),
      ),
    );
  }

  function handleCancel() {
    send({ type: "cancel" });
  }

  async function handleCopySessionId(): Promise<void> {
    try {
      await navigator.clipboard.writeText(sessionId);
      setSessionIdCopied(true);
      window.setTimeout(() => setSessionIdCopied(false), 1200);
    } catch {
      /* clipboard may be denied; avoid throwing in UI */
    }
  }

  const connected = status === "connected";
  const hasKnowledgeContent = messages.length > 0;
  const hasKnowledgeChanges = sessionHasKnowledgeChanges(session);
  const sessionArchived = session?.attributes.archived ?? false;
  const sessionUnattended = session?.attributes.unattended ?? false;
  const sessionAskMode = session?.attributes.ask_mode ?? false;
  const sessionYoloMode = session?.attributes.yolo_mode ?? false;
  const submittedUserMessageCount = countSubmittedUserMessages(messages);
  const unattendedInputLockBaseline = nextUnattendedInputLockBaseline({
    previousSessionId: previousSessionIdRef.current,
    sessionId,
    previousUnattended: previousSessionUnattendedRef.current,
    sessionUnattended,
    previousBaseline: unattendedInputLockBaselineRef.current,
    submittedUserMessageCount,
  });
  const unattendedInputLocked = isUnattendedInputLocked(
    sessionUnattended,
    submittedUserMessageCount,
    unattendedInputLockBaseline,
  );
  const sessionPrivate = session?.attributes.private ?? false;
  const sessionPinned = session?.attributes.pinned ?? false;
  const sessionFavorite = session?.attributes.favorite ?? false;
  const sessionCanArchive = canArchiveSession(session);
  const inputDisabled = sessionArchived || unattendedInputLocked;
  const inputDisabledPlaceholder = sessionArchived
    ? t("inputDisabled.archived")
    : t("inputDisabled.unattended");
  const canCommitKnowledge = !!session && !sessionPrivate && !sessionArchived && hasKnowledgeContent && hasKnowledgeChanges;
  const waitingLabel = !waiting
    ? null
    : llmActivity?.source === "agent"
      ? llmActivity.phase === "processing_prompt"
        ? t("waiting.processingPrompt")
        : llmActivity.phase === "thinking"
          ? t("waiting.thinking")
        : llmActivity.phase === "generating"
          ? t("waiting.generating")
          : t("waiting.working")
      : t("waiting.working");
    const showsStartSandbox = shouldShowStartSandbox(sandbox);
    const sandboxActionDisabled = waiting
      || sandboxLoading
      || !!sandboxPowerAction
      || wipingSandbox
      || deletingSession
      || sandbox?.status === "pending";
    const sandboxPowerButtonLabel = sandboxPowerAction === "starting"
      ? t("sandbox.actions.starting")
      : sandboxPowerAction === "stopping"
        ? t("sandbox.actions.scalingDown")
        : sandbox?.status === "pending"
          ? t("sandbox.actions.starting")
        : showsStartSandbox
          ? t("sandbox.actions.start")
          : t("sandbox.actions.scaleDown");
    const archiveStatusLabel = formatArchiveTimestamp(session?.knowledge_last_committed_at, locale, t);
    const knowledgeBadge = knowledgeStatusBadge(session, hasKnowledgeChanges, t);
    const archiveButtonDisabled = !canCommitKnowledge || waiting || savingKnowledge || deletingSession;
    const commitButtonTitle = !hasKnowledgeContent
      ? t("knowledge.commitDisabledNoHistory")
      : session?.knowledge_last_committed_at
        ? hasKnowledgeChanges
          ? archiveStatusLabel
          : t("knowledge.noNewChanges", { status: archiveStatusLabel })
        : undefined;
  const sessionDisplayTitle = session?.title?.trim() || sessionId;
  const source = localizedSessionSourceInfo(session, t);
    const defaultModelLabel = tRoot("commandResult.models.default");
    const agentModelOptions = useMemo(
      () => withSelectedModelOption(availableModelEntries, session?.agent_model_name),
      [availableModelEntries, session?.agent_model_name],
    );
    const sentinelModelOptions = useMemo(
      () => withSelectedModelOption(availableModelEntries, session?.sentinel_model_name),
      [availableModelEntries, session?.sentinel_model_name],
    );
  const sourceJobId = sessionSourceJobId(session);
  const latestJobRun = session?.latest_job_run ?? null;
  const latestJobData = formatSessionJobData(latestJobRun?.data);
  const fallbackSourceJobId = latestJobRun ? null : sourceJobId;
  const totalCostUsd = session?.total_cost_usd ?? 0;
  const jobLinkClass = "-mx-1 inline-flex items-center gap-1 rounded px-1 font-mono text-xs leading-5 text-foreground transition-colors hover:bg-muted";
  useEffect(() => {
    previousSessionIdRef.current = sessionId;
    previousSessionUnattendedRef.current = sessionUnattended;
    unattendedInputLockBaselineRef.current = unattendedInputLockBaseline;
  }, [sessionId, sessionUnattended, unattendedInputLockBaseline]);

  const renderJobSettingsLink = (jobId: string) => {
    if (!onOpenJobSettings) {
      return jobId;
    }

    return (
      <button
        type="button"
        onClick={() => onOpenJobSettings(jobId)}
        className={jobLinkClass}
      >
        <span>{jobId}</span>
        <ExternalLink className="h-3 w-3 shrink-0 self-center text-muted-foreground" />
      </button>
    );
  };
  const sessionDetailBadges = [
    sessionArchived
      ? { label: t("badges.archived"), icon: Archive, className: "border-violet-200 bg-violet-50 text-violet-800" }
      : null,
    sessionPinned
      ? { label: t("badges.pinned"), icon: Pin, className: "border-sky-200 bg-sky-50 text-sky-800" }
      : null,
    sessionFavorite
      ? { label: t("badges.favorite"), icon: Star, className: "border-amber-200 bg-amber-50 text-amber-800" }
      : null,
  ].filter((value): value is { label: string; icon: typeof Archive; className: string } => value !== null);
  const inspectorBadgeClass = "inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium";
  const inspectorContent = (
    <div className="space-y-3">
      <section className="rounded-2xl border border-border/70 bg-muted/25 px-3 py-2 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="text-[11px] font-medium uppercase tracking-[0.12em] text-muted-foreground">
            {t("inspector.actions")}
          </div>
          <div className="flex flex-wrap items-center justify-end gap-1">
          <button
            onClick={() => setAgentViewOpen(true)}
            disabled={!session}
            title={tc("agentViewHint")}
            className="rounded-md p-1.5 text-foreground/70 transition-colors hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Eye className="h-3.5 w-3.5" />
          </button>
          <button
            onClick={() => void handleTogglePinned()}
            disabled={!session || !!updatingSessionAttribute || deletingSession || !onUpdateSessionAttributes}
            title={sessionPinned ? t("actions.unpin") : t("actions.pin")}
            className="rounded-md p-1.5 text-sky-900 transition-colors hover:bg-sky-100 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {updatingSessionAttribute === "pinned" ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Pin className="h-3.5 w-3.5" />
            )}
          </button>
          <button
            onClick={() => void handleToggleFavorite()}
            disabled={!session || !!updatingSessionAttribute || deletingSession || !onUpdateSessionAttributes}
            title={sessionFavorite ? t("actions.unfavorite") : t("actions.favorite")}
            className="rounded-md p-1.5 text-amber-900 transition-colors hover:bg-amber-100 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {updatingSessionAttribute === "favorite" ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Star className="h-3.5 w-3.5" />
            )}
          </button>
          {sessionArchived || sessionCanArchive ? (
            <button
              onClick={() => void handleToggleArchived()}
              disabled={!session || !!updatingSessionAttribute || deletingSession || !onUpdateSessionAttributes}
              title={sessionArchived ? t("actions.unarchive") : t("actions.archive")}
              className="rounded-md p-1.5 text-violet-900 transition-colors hover:bg-violet-100 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {updatingSessionAttribute === "archived" ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : sessionArchived ? (
                <ArchiveRestore className="h-3.5 w-3.5" />
              ) : (
                <Archive className="h-3.5 w-3.5" />
              )}
            </button>
          ) : null}
          <button
            onClick={() => void handleDeleteSession()}
            disabled={waiting || !!sandboxPowerAction || wipingSandbox || deletingSession || !onDeleteSession}
            title={t("actions.delete")}
            className="rounded-md p-1.5 text-destructive transition-colors hover:bg-destructive/10 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {deletingSession ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Trash2 className="h-3.5 w-3.5" />
            )}
          </button>
          </div>
        </div>
      </section>

      <section className="rounded-2xl border border-border/70 bg-background/90 p-3 shadow-sm">
        <div className="text-[11px] font-medium uppercase tracking-[0.12em] text-muted-foreground">
          {t("inspector.session")}
        </div>

        <dl className="mt-3 grid grid-cols-[4.5rem_minmax(0,1fr)] items-start gap-x-3 gap-y-2 text-sm">
          <dt className="text-muted-foreground">{t("session.title")}</dt>
          <dd className="break-words font-semibold text-foreground">
            {session?.title?.trim() ? <EmojiText text={sessionDisplayTitle} /> : sessionDisplayTitle}
          </dd>

          <dt className="text-muted-foreground">{t("session.id")}</dt>
          <dd className="flex items-center gap-2">
            <span className="min-w-0 break-all font-mono text-xs text-muted-foreground">{sessionId}</span>
            <button
              type="button"
              onClick={() => void handleCopySessionId()}
              className="shrink-0 rounded-md border border-border/70 p-1 text-muted-foreground transition-colors hover:bg-muted"
              aria-label={sessionIdCopied ? t("session.idCopied") : t("session.copyId")}
              title={sessionIdCopied ? t("session.idCopiedShort") : t("session.copyId")}
            >
              {sessionIdCopied ? (
                <Check className="h-3 w-3" strokeWidth={2} />
              ) : (
                <Copy className="h-3 w-3" strokeWidth={2} />
              )}
            </button>
          </dd>

          <dt className="text-muted-foreground">{t("session.source")}</dt>
          <dd className="inline-flex items-center gap-2 font-medium text-foreground">
            <source.icon className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
            <span>{source.label}</span>
          </dd>

          <dt className="text-muted-foreground">{t("session.created")}</dt>
          <dd className="text-foreground">{formatSessionTimestamp(session?.created_at, locale, t)}</dd>

          <dt className="text-muted-foreground">{t("session.lastActive")}</dt>
          <dd className="text-foreground">{formatSessionTimestamp(session?.last_active, locale, t)}</dd>

          <dt className="text-muted-foreground">{t("session.messages")}</dt>
          <dd className="text-foreground">{session?.message_count ?? 0}</dd>

          {totalCostUsd > 0 ? (
            <>
              <dt className="text-muted-foreground">{t("session.totalCost")}</dt>
              <dd className="text-foreground">{formatUsd(totalCostUsd, locale)}</dd>
            </>
          ) : null}

          {fallbackSourceJobId ? (
            <>
              <dt className="text-muted-foreground">{t("session.job")}</dt>
              <dd className="break-all">{renderJobSettingsLink(fallbackSourceJobId)}</dd>
            </>
          ) : null}

          {session?.channel_ref && !fallbackSourceJobId ? (
            <>
              <dt className="text-muted-foreground">{t("session.reference")}</dt>
              <dd className="break-all">
                {sourceJobId ? renderJobSettingsLink(sourceJobId) : session.channel_ref}
              </dd>
            </>
          ) : null}

        </dl>

        <div className="mt-4 border-t border-border/60 pt-4">
          <SessionOptionTiles
            items={[
              {
                key: "private",
                active: sessionPrivate,
                disabled: !session || deletingSession || updatingSessionAttribute !== null,
                onClick: () => void handleTogglePrivacy(),
              },
              {
                key: "ask_mode",
                active: sessionAskMode,
                disabled: !session || deletingSession || !onUpdateSessionAttributes || updatingSessionAttribute !== null,
                onClick: () => void handleToggleSessionMode("ask"),
              },
              {
                key: "yolo_mode",
                active: sessionYoloMode,
                disabled: !session || deletingSession || !onUpdateSessionAttributes || updatingSessionAttribute !== null,
                onClick: () => void handleToggleSessionMode("yolo"),
              },
              {
                key: "unattended",
                active: sessionUnattended,
                disabled: !session || deletingSession || !onUpdateSessionAttributes || updatingSessionAttribute !== null,
                onClick: () => void handleToggleSessionMode("unattended"),
              },
            ]}
          />

          {showDelayedSessionAttributeStatus && updatingSessionAttribute === "private" ? (
            <div className="inline-flex items-center gap-2 pt-2 text-xs text-muted-foreground">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              <span>{t("session.savingPrivate")}</span>
            </div>
          ) : null}

          {showDelayedSessionAttributeStatus && updatingSessionAttribute === "mode" ? (
            <div className="inline-flex items-center gap-2 pt-2 text-xs text-muted-foreground">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              <span>{t("session.updatingMode")}</span>
            </div>
          ) : null}
        </div>

        <div className="mt-3 flex flex-wrap gap-2">
          {sessionDetailBadges.map((badge) => (
            <span
              key={badge.label}
              className={cn(inspectorBadgeClass, "gap-1", badge.className)}
            >
              <badge.icon className="h-3 w-3 shrink-0" />
              {badge.label}
            </span>
          ))}
        </div>
      </section>

      <section className="rounded-2xl border border-border/70 bg-background/90 p-3 shadow-sm">
        <div className="flex items-center justify-between gap-2">
          <div className="text-[11px] font-medium uppercase tracking-[0.12em] text-muted-foreground">
            {tRoot("jobs.fields.models")}
          </div>
          <button
            type="button"
            onClick={() => setModelsUnlocked((current) => !current)}
            aria-pressed={modelsUnlocked}
            aria-label={modelsUnlocked ? tRoot("jobs.fields.modelsUnlinked") : tRoot("jobs.fields.modelsLinked")}
            title={modelsUnlocked ? tRoot("jobs.fields.modelsUnlinkedHelp") : tRoot("jobs.fields.modelsLinkedHelp")}
            className={cn(
              "inline-flex h-7 w-7 items-center justify-center rounded-md border border-border/70 text-muted-foreground transition-colors",
              modelsUnlocked ? "hover:bg-muted" : "bg-accent/60 text-accent-foreground hover:bg-accent",
            )}
          >
            {modelsUnlocked ? <Link2Off className="h-3.5 w-3.5" /> : <Link2 className="h-3.5 w-3.5" />}
          </button>
        </div>

        <div className="mt-3 space-y-3">
          <label className="space-y-1.5">
            <span className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">{tRoot("jobs.fields.agentModel")}</span>
            <ModelPicker
              value={session?.agent_model_name}
              entries={agentModelOptions}
              onChange={(value) => void handleUpdateSessionModel("agent", value)}
              disabled={!session || waiting || deletingSession || sessionArchived || updatingSessionModel !== null}
              defaultLabel={defaultModelLabel}
            />
          </label>

          <label className="space-y-1.5">
            <span className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">{tRoot("jobs.fields.sentinelModel")}</span>
            <ModelPicker
              value={session?.sentinel_model_name}
              entries={sentinelModelOptions}
              onChange={(value) => void handleUpdateSessionModel("sentinel", value)}
              disabled={!session || waiting || deletingSession || sessionArchived || updatingSessionModel !== null}
              defaultLabel={defaultModelLabel}
            />
          </label>
        </div>

        {modelUpdateError ? (
          <div className="mt-3 text-xs text-destructive">{modelUpdateError}</div>
        ) : null}
      </section>

      {latestJobRun ? (
        <section className="rounded-2xl border border-border/70 bg-background/90 p-3 shadow-sm">
          <div className="text-[11px] font-medium uppercase tracking-[0.12em] text-muted-foreground">
            {t("jobRun.title")}
          </div>

          <dl className="mt-3 grid grid-cols-[4.5rem_minmax(0,1fr)] items-start gap-x-3 gap-y-2 text-sm">
            <dt className="text-muted-foreground">{t("jobRun.job")}</dt>
            <dd className="break-all">{renderJobSettingsLink(latestJobRun.job_id)}</dd>

            <dt className="text-muted-foreground">{t("jobRun.trigger.label")}</dt>
            <dd className="text-foreground">{formatJobTriggerKind(latestJobRun.trigger_kind, t)}</dd>

            <dt className="text-muted-foreground">{t("jobRun.ranAt")}</dt>
            <dd className="text-foreground">{formatSessionTimestamp(latestJobRun.triggered_at, locale, t)}</dd>

            {latestJobRun.cron_expression ? (
              <>
                <dt className="text-muted-foreground">{t("jobRun.schedule")}</dt>
                <dd className="break-all font-mono text-xs text-foreground">{latestJobRun.cron_expression}</dd>
              </>
            ) : null}
          </dl>

          {latestJobData ? (
            <div className="mt-3 space-y-1.5">
              <div className="text-[11px] font-medium uppercase tracking-[0.12em] text-muted-foreground">
                {t("jobRun.data")}
              </div>
              <pre className="overflow-x-auto rounded-xl border border-border/70 bg-muted/35 px-3 py-2 font-mono text-xs leading-5 text-foreground whitespace-pre-wrap break-words">
                {latestJobData.value}
              </pre>
            </div>
          ) : null}
        </section>
      ) : null}

      <section className="rounded-2xl border border-border/70 bg-background/90 p-3 shadow-sm">
        <div className="flex items-start justify-between gap-2">
          <div className="text-[11px] font-medium uppercase tracking-[0.12em] text-muted-foreground">
            {t("sandbox.title")}
          </div>
          <div className="flex shrink-0 items-center gap-1">
            <button
              onClick={() => void handleSandboxPowerAction()}
              disabled={sandboxActionDisabled || sessionArchived}
              title={sandboxPowerButtonLabel}
              className="rounded-md p-1.5 text-sky-900 transition-colors hover:bg-sky-100 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {sandboxPowerAction ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : showsStartSandbox ? (
                <Play className="h-3.5 w-3.5" />
              ) : (
                <Square className="h-3.5 w-3.5" />
              )}
            </button>
            <button
              onClick={() => void handleWipeSandbox()}
              disabled={waiting || !!sandboxPowerAction || wipingSandbox || deletingSession || sessionArchived}
              title={t("sandbox.actions.reset")}
              className="rounded-md p-1.5 text-amber-900 transition-colors hover:bg-amber-100 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {wipingSandbox ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <RotateCcw className="h-3.5 w-3.5" />
              )}
            </button>
          </div>
        </div>
        <div className="mt-2 space-y-1">
          <div className="flex min-w-0 items-center gap-2 text-sm font-medium text-foreground">
            <span
              className={cn(
                "h-2 w-2 shrink-0 rounded-full",
                sandboxLoading
                  ? "animate-pulse bg-amber-500"
                  : sandbox
                    ? sandboxStatusIndicatorClass(sandbox.status)
                    : "bg-slate-300",
              )}
            />
            <span className="truncate">
              {sandboxLoading
                ? t("sandbox.refreshing")
                : sandbox
                  ? t(`sandbox.status.${sandboxStatusKey(sandbox.status)}`)
                  : t("sandbox.checking")}
            </span>
          </div>
          <div className="text-xs text-muted-foreground">{sandboxStorageLabel(sandbox, t)}</div>
          {sandboxIdentifier(sandbox) ? (
            <div className="flex min-w-0 items-center gap-2 text-xs text-muted-foreground">
              <span>{t("sandbox.fields.id")}</span>
              <span className="break-all font-mono text-foreground">{sandboxIdentifier(sandbox)}</span>
            </div>
          ) : null}
        </div>
        <div className="mt-3 border-t border-border/60 pt-3">
          <SandboxGitControls
            server={server}
            token={token}
            sessionId={sessionId}
            disabled={waiting || !!sandboxPowerAction || wipingSandbox || deletingSession}
            refreshKey={sandbox?.status}
          />
        </div>
      </section>

      <section className="rounded-2xl border border-border/70 bg-background/90 p-3 shadow-sm">
        <div className="flex items-start justify-between gap-2">
          <div className="text-[11px] font-medium uppercase tracking-[0.12em] text-muted-foreground">
            {t("knowledge.title")}
          </div>
          <button
            onClick={() => void handleCommitKnowledge()}
            disabled={archiveButtonDisabled}
            title={commitButtonTitle ?? t("knowledge.commit")}
            className="rounded-md p-1.5 text-emerald-900 transition-colors hover:bg-emerald-100 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {savingKnowledge ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Save className="h-3.5 w-3.5" />
            )}
          </button>
        </div>
        <div className="mt-2 flex min-w-0 flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <span
            className={cn(
              inspectorBadgeClass,
              "gap-1",
              knowledgeBadge.className,
            )}
          >
            <knowledgeBadge.icon className="h-3 w-3 shrink-0" />
            {knowledgeBadge.label}
          </span>
          <span className="truncate">{archiveStatusLabel}</span>
        </div>
        {session?.knowledge_last_archive_path ? (
          <Link
            href={knowledgeBrowseHref(session.knowledge_last_archive_path)}
            title={t("knowledge.openInBrowser")}
            className="mt-2 block break-all rounded-sm font-mono text-xs text-muted-foreground underline-offset-2 transition-colors hover:text-foreground hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {session.knowledge_last_archive_path}
          </Link>
        ) : null}
      </section>

      {knowledgeNotice ? (
        <div
          className={cn(
            "rounded-2xl border border-border/70 bg-background/90 px-3 py-2 text-xs shadow-sm",
            knowledgeNotice.tone === "error"
              ? "text-destructive"
              : knowledgeNotice.tone === "success"
                ? "text-emerald-700"
                : "text-muted-foreground",
          )}
        >
          {knowledgeNotice.message}
        </div>
      ) : null}
    </div>
  );

  return (
    <div className="flex h-full min-h-0 flex-1 flex-col overflow-hidden">
      {/* Status bar */}
      {status !== "connected" && (
        <div className="flex items-center gap-2 border-b border-border px-4 py-2 text-xs text-muted-foreground">
          <span
            className={`h-1.5 w-1.5 rounded-full ${status === "connecting" ? "bg-warning animate-pulse" : "bg-destructive"}`}
          />
          {status === "connecting" ? t("status.connecting") : t("status.disconnected")}
        </div>
      )}

      <div className="min-h-0 flex flex-1 flex-col lg:grid lg:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="min-h-0 flex flex-1 flex-col">
          <div className="border-b border-border px-3 py-2.5 sm:px-4 sm:py-3">
            <div className="flex items-center justify-between gap-3 sm:items-start">
              <div className="min-w-0">
                <div className="flex min-w-0 items-center gap-2">
                  <div className="truncate text-sm font-semibold text-foreground">
                    {session?.title?.trim() ? <EmojiText text={sessionDisplayTitle} /> : sessionDisplayTitle}
                  </div>
                  {hasMemory ? (
                    <button
                      type="button"
                      onClick={() => setMemoryDrawerOpen(true)}
                      className="inline-flex shrink-0 items-center gap-1 rounded-full bg-accent px-2 py-0.5 text-[11px] font-medium text-accent-foreground transition-colors hover:bg-accent/70"
                    >
                      <Brain className="h-3 w-3" />
                      {t("memoryChip")}
                    </button>
                  ) : null}
                </div>
                <div className="mt-1 hidden truncate font-mono text-xs text-muted-foreground sm:block">
                  {sessionId}
                </div>
              </div>
              <button
                type="button"
                onClick={() => setMobileInspectorOpen(true)}
                className="inline-flex items-center gap-2 rounded-lg border border-border bg-background px-3 py-2 text-sm font-medium hover:bg-muted lg:hidden"
              >
                <Settings2 className="h-4 w-4" />
                {t("mobile.details")}
              </button>
            </div>
          </div>

          <div
            ref={scrollRef}
            onScroll={handleScroll}
            className="min-h-0 flex-1 overflow-y-auto px-4 py-4"
          >
            <div className="session-chat-content mx-auto max-w-3xl space-y-3">
              {loadingHistory && (
                <div className="flex justify-center py-8">
                  <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                </div>
              )}
              {!loadingHistory && messages.length === 0 && (
                <div className="flex flex-col items-center justify-center py-16 text-center">
                  <p className="text-lg font-medium text-foreground/80">{agentName}</p>
                  <p className="mt-1 text-sm text-muted-foreground">
                    {connected
                      ? t("empty.start")
                      : t("empty.connectingSession")}
                  </p>
                </div>
              )}
              {(() => {
                const renderMessage = (i: number) => {
                  const msg = messages[i];
                  // Event-granular: fork/reset cut exactly at this message (mid-turn included).
                  // Retry still re-runs the latest turn.
                  const actionable = msg.kind === "user" || msg.kind === "assistant";
                  const enclosingTerminal = enclosingTurnTerminalMessageIndex(messages, i);
                  // A persisted/completed message can be a cut target; its event index is resolved
                  // (refetched if a freshly-finished turn hasn't been reprojected) when acted on.
                  const inHistory =
                    typeof eventIndexForMessage(msg) === "number" || enclosingTerminal != null;
                  const canFork = actionable && inHistory;
                  // Resetting the very last bubble removes nothing — offer it only with a tail to drop.
                  const canReset = canFork && i < messages.length - 1;
                  const canRetry = actionable && enclosingTerminal === latestTerminalIndex;
                  return (
                    <div key={i} data-event-index={anchorEventIndex(msg)} className="rounded-lg">
                      <Message
                        message={msg}
                        server={server}
                        sessionId={sessionId}
                        activeLlmActivity={llmActivity}
                        canFork={canFork}
                        canRetry={canRetry}
                        canReset={canReset}
                        actionDisabled={turnActionsDisabled}
                        onApproval={handleApproval}
                        onEscalation={handleEscalation}
                        onCredentialApproval={handleCredentialEscalation}
                        onFork={canFork ? () => void handleFork(i) : undefined}
                        onRetry={canRetry ? handleRetry : undefined}
                        onReset={canReset ? () => void handleReset(i) : undefined}
                      />
                    </div>
                  );
                };
                return groupRenderItems(messages).map((item) =>
                  item.type === "message" ? (
                    renderMessage(item.index)
                  ) : (
                    <div key={`g-${item.start}`} data-event-index={anchorEventIndex(messages[item.start])} className="rounded-lg">
                      <ToolCallGroup
                        items={item.indices.map((j) => messages[j])}
                        inProgress={item.inProgress}
                      >
                        {item.indices.map((j) => renderMessage(j))}
                      </ToolCallGroup>
                    </div>
                  ),
                );
              })()}
              {waitingLabel && (
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  <span>{waitingLabel}</span>
                </div>
              )}
              <div ref={bottomRef} />
            </div>
          </div>

          <ChatInput
            sessionId={sessionId}
            onSend={handleSend}
            onCancel={handleCancel}
            onInterrupt={handleInterrupt}
            connected={connected}
            disabled={inputDisabled}
            disabledPlaceholder={inputDisabledPlaceholder}
            agentName={agentName}
            waiting={waiting}
            queuedMessage={queuedMessage}
            commands={commands}
            availableModelEntries={availableModelEntries}
            usage={usage}
            sandboxRunning={sandbox?.status === "running"}
            uploadFile={uploadFile}
          />
        </div>

        <aside className="hidden min-h-0 border-l border-border bg-muted/20 lg:block">
          <div className="h-full overflow-y-auto p-3">{inspectorContent}</div>
        </aside>
      </div>

      {agentViewOpen ? (
        <AgentHistoryView
          server={server}
          token={token}
          sessionId={sessionId}
          onClose={() => setAgentViewOpen(false)}
        />
      ) : null}

      {mobileInspectorOpen ? (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div
            className="absolute inset-0 bg-black/30 backdrop-blur-[1px]"
            onClick={() => setMobileInspectorOpen(false)}
          />
          <div className="absolute inset-x-0 bottom-0 flex max-h-[85vh] min-h-0 flex-col overflow-hidden rounded-t-3xl border border-border bg-background shadow-2xl">
            <div
              className="border-b border-border"
              onTouchStart={handleMobileInspectorTouchStart}
              onTouchEnd={handleMobileInspectorTouchEnd}
            >
              <div className="flex justify-center px-4 pt-2 pb-1.5">
                <span className="h-1.5 w-12 rounded-full bg-border/80" />
              </div>
              <div className="flex items-start justify-between gap-3 px-4 py-2.5">
                <div className="min-w-0">
                  <div className="text-sm font-semibold text-foreground">{t("mobile.details")}</div>
                  <div className="truncate text-xs text-muted-foreground">
                    {session?.title?.trim() ? <EmojiText text={sessionDisplayTitle} /> : sessionDisplayTitle}
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => setMobileInspectorOpen(false)}
                  className="rounded-lg border border-border bg-background px-2.5 py-1.5 text-sm font-medium hover:bg-muted"
                >
                  {t("mobile.done")}
                </button>
              </div>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto p-3 pb-[max(1.5rem,calc(env(safe-area-inset-bottom)+0.75rem))]">
              {inspectorContent}
            </div>
          </div>
        </div>
      ) : null}

      {memoryDrawerOpen ? (
        <MemoryExtractionDrawer
          server={server}
          sessionId={sessionId}
          onClose={() => setMemoryDrawerOpen(false)}
          onSourceNavigate={() => setMemoryDrawerOpen(false)}
        />
      ) : null}
    </div>
  );
}
