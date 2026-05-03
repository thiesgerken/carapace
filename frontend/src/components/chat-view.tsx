"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Archive, ArchiveRestore, Loader2, Lock, Pin, Play, RotateCcw, Save, Square, Star, Trash2, Unlock } from "lucide-react";
import { useWebSocket } from "@/hooks/use-websocket";
import {
  type AvailableModelInfo,
  commitSessionKnowledge,
  fetchCommands,
  fetchHistory,
  fetchSandbox,
  fetchModels,
  forkSession,
  type SlashCommand,
  startSandbox,
  stopSandbox,
  updateSession,
  wipeSandbox,
  wsUrl,
} from "@/lib/api";
import type {
  ChatMessage,
  ClientMessage,
  EscalationDecision,
  HistoryMessage,
  LlmActivity,
  ServerMessage,
  SessionInfo,
  SessionSandboxSnapshot,
  TurnUsage,
} from "@/lib/types";
import { isRecord } from "@/lib/decoding";
import {
  cn,
  formatBytes,
  sandboxStatusIndicatorClass,
  sandboxStatusLabel,
  sessionHasKnowledgeChanges,
} from "@/lib/utils";
import { Message } from "./message";
import { ChatInput } from "./chat-input";

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
  onUpdateSessionAttributes?: (sessionId: string, attributes: { private?: boolean; archived?: boolean; pinned?: boolean; favorite?: boolean }) => Promise<SessionInfo>;
  onDeleteSession?: () => Promise<void>;
}

const SANDBOX_STARTUP_TOOL_NAMES = new Set(["use_skill", "read", "write", "str_replace", "exec"]);

function sandboxStorageLabel(snapshot: SessionSandboxSnapshot | null): string {
  if (!snapshot) return "";
  if (snapshot.status === "missing" && !snapshot.storage_present) return "";
  const details: string[] = [];
  if (typeof snapshot.last_measured_used_bytes === "number") {
    details.push(`${formatBytes(snapshot.last_measured_used_bytes)} used`);
  } else if (!snapshot.storage_present) {
    details.push("no sandbox storage");
  }
  if (
    snapshot.runtime === "kubernetes"
    && typeof snapshot.provisioned_bytes === "number"
  ) {
    details.push(`${formatBytes(snapshot.provisioned_bytes)} allocated`);
  }
  return details.join(" · ");
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

function errorDetail(error: unknown): string {
  if (error instanceof Error && error.message.trim().length > 0) {
    return error.message;
  }
  return "Unexpected error";
}

function formatArchiveTimestamp(iso?: string | null): string {
  if (!iso) return "Not committed yet";
  const value = new Date(iso);
  if (Number.isNaN(value.getTime())) return "Committed";
  return `Saved ${value.toLocaleString(undefined, {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  })}`;
}

function knowledgeStatusBadge(
  session: SessionInfo | null,
  hasKnowledgeChanges: boolean,
): { label: string; className: string } {
  const isInKnowledgeRepo = Boolean(
    session?.knowledge_last_committed_at || session?.knowledge_last_archive_path,
  );

  if (session?.attributes.private && !isInKnowledgeRepo) {
    return {
      label: "excluded",
      className: "border-zinc-300 bg-zinc-100 text-zinc-700",
    };
  }

  if (!isInKnowledgeRepo) {
    return {
      label: "missing",
      className: "border-slate-300 bg-slate-100 text-slate-700",
    };
  }

  if (hasKnowledgeChanges) {
    return {
      label: "outdated",
      className: "border-amber-300 bg-amber-50 text-amber-700",
    };
  }

  return {
    label: "up-to-date",
    className: "border-emerald-300 bg-emerald-50 text-emerald-700",
  };
}

function optimisticPendingSandbox(
  snapshot: SessionSandboxSnapshot | null,
): SessionSandboxSnapshot {
  return {
    exists: snapshot?.exists ?? false,
    runtime: snapshot?.runtime,
    status: "pending",
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
  result: { result: string; exitCode?: number },
): { messages: ChatMessage[]; found: boolean } {
  return updateToolCallMessageById(messages, toolId, (entry) => ({
    ...entry,
    result: result.result,
    exitCode: result.exitCode,
    loading: false,
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
  return message.kind === "assistant" || (message.kind === "error" && message.turnTerminal === true);
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
  if (message.kind === "assistant" || message.kind === "error") {
    return typeof message.eventIndex === "number" ? message.eventIndex : undefined;
  }
  return undefined;
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

function projectHistoryToMessages(history: HistoryMessage[]): ChatMessage[] {
  const messages: ChatMessage[] = [];
  const pendingToolCallIndices = new Map<string, number[]>();

  for (let index = 0; index < history.length; index++) {
    const entry = history[index];

    if (entry.role === "user") {
      messages.push({ kind: "user", content: entry.content });
      continue;
    }

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
          exitCode: entry.exit_code,
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
          exitCode: entry.exit_code,
          loading: false,
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

    messages.push({
      kind: "assistant",
      content: entry.content,
      eventIndex: typeof entry.event_index === "number" ? entry.event_index : undefined,
    });
  }

  return groupChildToolCalls(messages);
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
  onUpdateSessionAttributes,
  onDeleteSession,
}: ChatViewProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [waiting, setWaiting] = useState(false);
  const [queuedMessage, setQueuedMessage] = useState<string | null>(null);
  const [usage, setUsage] = useState<TurnUsage | null>(null);
  const [llmActivity, setLlmActivity] = useState<LlmActivity | null>(null);
  const [loadingHistory, setLoadingHistory] = useState(true);
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
  const [updatingSessionAttribute, setUpdatingSessionAttribute] = useState<"archived" | "private" | "pinned" | "favorite" | null>(null);
  const [turnActionBusyIndex, setTurnActionBusyIndex] = useState<number | null>(null);
  const [knowledgeNotice, setKnowledgeNotice] = useState<{
    tone: "neutral" | "success" | "error";
    message: string;
  } | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const isAtBottomRef = useRef(true);
  const lastThinkingStartedAtRef = useRef<string | null>(null);
  const queueRef = useRef<string | null>(null);
  const resetRollbackRef = useRef<ChatMessage[] | null>(null);
  const sendRef = useRef<(msg: ClientMessage) => void>(() => {});
  const onSandboxUpdateRef = useRef(onSandboxUpdate);
  const sandboxRef = useRef(sandbox);
  const sandboxRefreshParamsRef = useRef({ server, token, sessionId });
  const sandboxRefreshPendingRef = useRef(false);
  const sandboxRefreshRunningRef = useRef(false);
  const sandboxRefreshEpochRef = useRef(0);

  useEffect(() => {
    onSandboxUpdateRef.current = onSandboxUpdate;
  }, [onSandboxUpdate]);

  const markSessionKnowledgeChanged = useCallback(() => {
    if (!session) return;
    onSessionUpdate?.({
      ...session,
      last_active: new Date().toISOString(),
    });
  }, [onSessionUpdate, session]);

  useEffect(() => {
    sandboxRef.current = sandbox;
  }, [sandbox]);

  useEffect(() => {
    sandboxRefreshParamsRef.current = { server, token, sessionId };
    sandboxRefreshEpochRef.current += 1;
  }, [server, sessionId, token]);

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
    if (queued) {
      queueRef.current = null;
      setQueuedMessage(null);
      sendRef.current({ type: "message", content: queued });
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
        case "done":
          resetRollbackRef.current = null;
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
            // Replace streaming message with the final content
            const streamIdx = updated.findLastIndex((m) => m.kind === "streaming");
            if (streamIdx !== -1) {
              updated[streamIdx] = { kind: "assistant", content: msg.content };
            } else {
              updated.push({ kind: "assistant", content: msg.content });
            }
            return updated;
          });
          if (msg.usage) setUsage(msg.usage);
          void refreshSandbox();
          setLlmActivity(null);
          lastThinkingStartedAtRef.current = null;
          finishWaiting();
          break;
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
          setMessages((prev) => [
            ...prev,
            { kind: "command", command: msg.command, data: msg.data },
          ]);
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
            { kind: "user", content: msg.content },
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
    [applySandboxSnapshot, finalizeThinkingMessages, finishWaiting, onTitleUpdate, refreshSandbox],
  );

  const onWsDisconnect = useCallback(() => {
    resetRollbackRef.current = null;
    queueRef.current = null;
    lastThinkingStartedAtRef.current = null;
    setQueuedMessage(null);
    clearToolLoading();
    setWaiting(false);
  }, [clearToolLoading]);
  const url = wsUrl(server, sessionId, token);
  const { status, send } = useWebSocket(url, onMessage, onWsDisconnect);
  useEffect(() => {
    sendRef.current = send;
  }, [send]);

  const terminalIndices = completedTurnMessageIndices(messages);
  const latestTerminalIndex = terminalIndices.length > 0 ? terminalIndices[terminalIndices.length - 1] : -1;
  const turnActionsDisabled = waiting || loadingHistory || status !== "connected" || turnActionBusyIndex !== null;

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

  function handleSend(content: string) {
    resetRollbackRef.current = null;
    if (waiting) {
      queueRef.current = content;
      setQueuedMessage(content);
    } else {
      lastThinkingStartedAtRef.current = null;
      send({ type: "message", content });
      markSessionKnowledgeChanged();
      setWaiting(true);
    }
  }

  function handleInterrupt(content: string) {
    resetRollbackRef.current = null;
    queueRef.current = content;
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
    setQueuedMessage(null);
    lastThinkingStartedAtRef.current = null;
    setLlmActivity(null);
    setMessages((prev) => prev.slice(0, startIndex));
    setWaiting(true);
    send({ type: "retry_latest_turn" });
  }

  async function resolveTurnTargetEventIndex(messageIndex: number): Promise<number | undefined> {
    const currentMessages = messages;
    const localTerminalIndices = completedTurnMessageIndices(currentMessages);
    const localTurnOrdinal = localTerminalIndices.indexOf(messageIndex);
    if (localTurnOrdinal === -1) return undefined;

    let targetEventIndex = eventIndexForMessage(currentMessages[messageIndex]);

    if (targetEventIndex == null) {
      const history = await fetchHistory(server, token, sessionId);
      const canonicalMessages = projectHistoryToMessages(history);
      const canonicalTerminalIndices = completedTurnMessageIndices(canonicalMessages);
      const canonicalMessageIndex = canonicalTerminalIndices[localTurnOrdinal];
      if (canonicalMessageIndex != null) {
        targetEventIndex = eventIndexForMessage(canonicalMessages[canonicalMessageIndex]);
      }
    }

    return targetEventIndex;
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
          { kind: "error", detail: "Could not resolve reset target." },
        ]);
        return;
      }

      resetRollbackRef.current = currentMessages;
      send({ type: "reset_to_turn", event_index: targetEventIndex });
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
          { kind: "error", detail: "Could not resolve fork target." },
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
      setMessages((prev) => [...prev, { kind: "error", detail: errorDetail(error) }]);
    } finally {
      setTurnActionBusyIndex(null);
    }
  }

  async function handleWipeSandbox() {
    if (waiting || sandboxPowerAction || wipingSandbox || deletingSession) return;
    if (!window.confirm("Wipe the sandbox and its storage for this session? Chat history will stay.")) {
      return;
    }
    setWipingSandbox(true);
    try {
      const nextSandbox = await wipeSandbox(server, token, sessionId);
      applySandboxSnapshot(nextSandbox);
    } catch (error) {
      console.error("Failed to wipe sandbox", error);
      setMessages((prev) => [...prev, { kind: "error", detail: errorDetail(error) }]);
    } finally {
      setWipingSandbox(false);
    }
  }

  async function handleSandboxPowerAction() {
    if (waiting || sandboxPowerAction || wipingSandbox || deletingSession) return;

    const currentSandbox = sandboxRef.current;
    const shouldStart = shouldShowStartSandbox(currentSandbox);
    if (!shouldStart && !window.confirm("Scale down the sandbox for this session? Storage will be kept.")) {
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
      setMessages((prev) => [...prev, { kind: "error", detail: errorDetail(error) }]);
      void refreshSandbox();
    } finally {
      setSandboxPowerAction(null);
    }
  }

  async function handleDeleteSession() {
    if (waiting || sandboxPowerAction || wipingSandbox || deletingSession || !onDeleteSession) return;
    if (!window.confirm("Delete this session? Chat history and sandbox state will be removed.")) {
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
    const confirmation = nextArchived
      ? "Archive this session? It will leave the default list, reset its sandbox, and stay in the knowledge repo."
      : "Unarchive this session? It will return to the active session list.";
    if (!window.confirm(confirmation)) {
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
          ?? (result.committed_at ? formatArchiveTimestamp(result.committed_at) : "Committed to knowledge"),
      });
    } catch (error) {
      setKnowledgeNotice({ tone: "error", message: errorDetail(error) });
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
      && !window.confirm("Mark this session private? Existing knowledge commits will remain in git history.")
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
            ? "Session is private. Existing knowledge commits remain unchanged."
            : "Session is private and will not be committed to knowledge."
          : "Session is included in knowledge commits to your repo.",
      });
    } catch (error) {
      setKnowledgeNotice({ tone: "error", message: errorDetail(error) });
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

  const connected = status === "connected";
  const hasKnowledgeContent = messages.length > 0;
  const hasKnowledgeChanges = sessionHasKnowledgeChanges(session);
  const sessionArchived = session?.attributes.archived ?? false;
  const sessionUnattended = session?.attributes.unattended ?? false;
  const sessionPrivate = session?.attributes.private ?? false;
  const sessionPinned = session?.attributes.pinned ?? false;
  const sessionFavorite = session?.attributes.favorite ?? false;
  const inputDisabled = sessionArchived || sessionUnattended;
  const inputDisabledPlaceholder = sessionArchived
    ? "Unarchive first"
    : "This session is unattended. Fork it first to continue here.";
  const canCommitKnowledge = !!session && !sessionPrivate && !sessionArchived && hasKnowledgeContent && hasKnowledgeChanges;
  const waitingLabel = !waiting
    ? null
    : llmActivity?.source === "agent"
      ? llmActivity.phase === "processing_prompt"
        ? "Processing Prompt..."
        : llmActivity.phase === "thinking"
          ? "Thinking..."
        : llmActivity.phase === "generating"
          ? "Generating..."
          : "Working..."
      : "Working...";
    const showsStartSandbox = shouldShowStartSandbox(sandbox);
    const sandboxActionDisabled = waiting
      || sandboxLoading
      || !!sandboxPowerAction
      || wipingSandbox
      || deletingSession
      || sandbox?.status === "pending";
    const sandboxPowerButtonLabel = sandboxPowerAction === "starting"
      ? "Starting sandbox"
      : sandboxPowerAction === "stopping"
        ? "Scaling down sandbox"
        : sandbox?.status === "pending"
          ? "Starting sandbox"
        : showsStartSandbox
          ? "Start sandbox"
          : "Scale down sandbox";
    const archiveStatusLabel = formatArchiveTimestamp(session?.knowledge_last_committed_at);
    const knowledgeBadge = knowledgeStatusBadge(session, hasKnowledgeChanges);
    const archiveButtonDisabled = !canCommitKnowledge || waiting || savingKnowledge || deletingSession;
    const commitButtonTitle = !hasKnowledgeContent
      ? "This session has no conversation history yet."
      : session?.knowledge_last_committed_at
        ? hasKnowledgeChanges
          ? archiveStatusLabel
          : `${archiveStatusLabel}. No new changes to commit.`
        : undefined;

  return (
    <div className="flex h-full min-h-0 flex-1 flex-col overflow-hidden">
      {/* Status bar */}
      {status !== "connected" && (
        <div className="flex items-center gap-2 border-b border-border px-4 py-2 text-xs text-muted-foreground">
          <span
            className={`h-1.5 w-1.5 rounded-full ${status === "connecting" ? "bg-warning animate-pulse" : "bg-destructive"}`}
          />
          {status === "connecting" ? "Connecting…" : "Disconnected"}
        </div>
      )}

      <div className="border-b border-border px-3 py-2.5 sm:px-4 sm:py-3">
        <div className="w-full">
          <div className="min-w-0 w-full space-y-2">
            <div className="grid grid-cols-2 gap-2">
              <div className="min-w-0 rounded-lg border border-border/70 bg-muted/20 px-2.5 py-2 sm:px-3">
                <div className="flex items-start justify-between gap-2">
                  <div className="text-[11px] font-medium uppercase tracking-[0.12em] text-muted-foreground">
                    Sandbox
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
                      title="Reset sandbox"
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
                <div className="mt-1 min-w-0 space-y-0.5">
                  <div className="flex min-w-0 items-center gap-2 text-sm font-medium text-foreground">
                    <span
                      className={cn(
                        "h-2 w-2 shrink-0 rounded-full",
                        sandboxLoading
                          ? "bg-amber-500 animate-pulse"
                          : sandbox
                            ? sandboxStatusIndicatorClass(sandbox.status)
                            : "bg-slate-300",
                      )}
                    />
                    <span className="truncate">{sandboxLoading ? "Refreshing…" : sandbox ? sandboxStatusLabel(sandbox.status) : "Checking sandbox…"}</span>
                  </div>
                  <div className="truncate text-xs font-normal text-muted-foreground">
                    {sandboxStorageLabel(sandbox)}
                  </div>
                </div>
              </div>

              <div className="min-w-0 rounded-lg border border-border/70 bg-muted/20 px-2.5 py-2 sm:px-3">
                <div className="flex items-start justify-between gap-2">
                  <div className="text-[11px] font-medium uppercase tracking-[0.12em] text-muted-foreground">
                    Knowledge
                  </div>
                  <div className="flex shrink-0 items-center gap-1">
                    <button
                      onClick={() => void handleCommitKnowledge()}
                      disabled={archiveButtonDisabled}
                      title={commitButtonTitle ?? "Commit to repo"}
                      className="rounded-md p-1.5 text-emerald-900 transition-colors hover:bg-emerald-100 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {savingKnowledge ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <Save className="h-3.5 w-3.5" />
                      )}
                    </button>
                    <button
                      onClick={() => void handleTogglePinned()}
                      disabled={!session || !!updatingSessionAttribute || deletingSession || !onUpdateSessionAttributes}
                      title={sessionPinned ? "Unpin session" : "Pin session"}
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
                      title={sessionFavorite ? "Remove favorite" : "Favorite session"}
                      className="rounded-md p-1.5 text-amber-900 transition-colors hover:bg-amber-100 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {updatingSessionAttribute === "favorite" ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <Star className="h-3.5 w-3.5" />
                      )}
                    </button>
                    <button
                      onClick={() => void handleToggleArchived()}
                      disabled={!session || !!updatingSessionAttribute || deletingSession || !onUpdateSessionAttributes}
                      title={sessionArchived ? "Unarchive session" : "Archive session"}
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
                    <button
                      onClick={() => void handleTogglePrivacy()}
                      disabled={!session || !!updatingSessionAttribute || deletingSession}
                      title={sessionPrivate ? "Include in repo" : "Keep private"}
                      className="rounded-md p-1.5 text-zinc-900 transition-colors hover:bg-zinc-100 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {updatingSessionAttribute === "private" ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : sessionPrivate ? (
                        <Unlock className="h-3.5 w-3.5" />
                      ) : (
                        <Lock className="h-3.5 w-3.5" />
                      )}
                    </button>
                    <button
                      onClick={() => void handleDeleteSession()}
                      disabled={waiting || !!sandboxPowerAction || wipingSandbox || deletingSession || !onDeleteSession}
                      title="Delete session"
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
                <div className="mt-1 min-w-0 space-y-0.5">
                  <div className="flex min-w-0 flex-wrap items-center gap-2 text-xs text-muted-foreground">
                    <span
                      className={cn(
                        "rounded-full border px-2 py-0.5 font-medium uppercase tracking-[0.08em]",
                        knowledgeBadge.className,
                      )}
                    >
                      {knowledgeBadge.label}
                    </span>
                    {sessionPinned ? (
                      <span className="inline-flex items-center gap-1 text-sky-700">
                        <Pin className="h-3 w-3 shrink-0" />
                        <span>Pinned</span>
                      </span>
                    ) : null}
                    {sessionFavorite ? (
                      <span className="inline-flex items-center gap-1 text-amber-700">
                        <Star className="h-3 w-3 shrink-0" />
                        <span>Favorite</span>
                      </span>
                    ) : null}
                    <span className="truncate">{archiveStatusLabel}</span>
                  </div>
                </div>
                {session?.knowledge_last_archive_path ? (
                  <div
                    className="hidden max-w-full truncate text-xs font-mono text-muted-foreground md:block"
                    title={session.knowledge_last_archive_path}
                  >
                    {session.knowledge_last_archive_path}
                  </div>
                ) : null}
              </div>
            </div>
            {knowledgeNotice ? (
              <div
                className={cn(
                  "text-xs",
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
        </div>
      </div>

      {/* Messages */}
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="min-h-0 flex-1 overflow-y-auto px-4 py-4"
      >
        <div className="mx-auto max-w-3xl space-y-3">
          {loadingHistory && (
            <div className="flex justify-center py-8">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          )}
          {!loadingHistory && messages.length === 0 && (
            <div className="flex flex-col items-center justify-center py-16 text-center">
              <p className="text-lg font-medium text-foreground/80">carapace</p>
              <p className="mt-1 text-sm text-muted-foreground">
                {connected
                  ? "Send a message to get started"
                  : "Connecting to session…"}
              </p>
            </div>
          )}
          {messages.map((msg, i) => (
            <Message
              key={i}
              message={msg}
              activeLlmActivity={llmActivity}
              canFork={msg.kind === "assistant"}
              canRetry={i === latestTerminalIndex && isTurnTerminalMessage(msg)}
              canReset={i !== latestTerminalIndex && isTurnTerminalMessage(msg)}
              actionDisabled={turnActionsDisabled}
              onApproval={handleApproval}
              onEscalation={handleEscalation}
              onCredentialApproval={handleCredentialEscalation}
              onFork={msg.kind === "assistant" ? () => void handleFork(i) : undefined}
              onRetry={i === latestTerminalIndex && isTurnTerminalMessage(msg) ? handleRetry : undefined}
              onReset={i !== latestTerminalIndex && isTurnTerminalMessage(msg) ? () => void handleReset(i) : undefined}
            />
          ))}
          {waitingLabel && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              <span>{waitingLabel}</span>
            </div>
          )}
          <div ref={bottomRef} />
        </div>
      </div>

      {/* Input */}
      <ChatInput
        onSend={handleSend}
        onCancel={handleCancel}
        onInterrupt={handleInterrupt}
        connected={connected}
        disabled={inputDisabled}
        disabledPlaceholder={inputDisabledPlaceholder}
        waiting={waiting}
        queuedMessage={queuedMessage}
        commands={commands}
        availableModelEntries={availableModelEntries}
        usage={usage}
      />
    </div>
  );
}
