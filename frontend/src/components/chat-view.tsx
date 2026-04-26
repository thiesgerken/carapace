"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2, Lock, RotateCcw, Save, Trash2, Unlock } from "lucide-react";
import { useWebSocket } from "@/hooks/use-websocket";
import {
  type AvailableModelInfo,
  commitSessionKnowledge,
  fetchCommands,
  fetchHistory,
  fetchSandbox,
  fetchModels,
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
  LlmActivity,
  ServerMessage,
  SessionInfo,
  SessionSandboxSnapshot,
  TurnUsage,
} from "@/lib/types";
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
    hour: "2-digit",
    minute: "2-digit",
  })}`;
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

export function ChatView({
  server,
  token,
  sessionId,
  session,
  initialSandbox,
  onTitleUpdate,
  onSessionUpdate,
  onSandboxUpdate,
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
  const [togglingPrivacy, setTogglingPrivacy] = useState(false);
  const [knowledgeNotice, setKnowledgeNotice] = useState<{
    tone: "neutral" | "success" | "error";
    message: string;
  } | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const isAtBottomRef = useRef(true);
  const lastThinkingStartedAtRef = useRef<string | null>(null);
  const queueRef = useRef<string | null>(null);
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
        const msgs: ChatMessage[] = [];
        const pendingToolCallIndices = new Map<string, number[]>();

        function findLaterEscalationDecision(
          fromIndex: number,
          requestId: string,
          roleMatches: (role: string) => boolean,
        ): EscalationDecision | undefined {
          for (let j = fromIndex + 1; j < history.length; j++) {
            const e = history[j];
            if (e.request_id !== requestId || !roleMatches(e.role)) continue;
            const d = e.decision;
            if (d === "allow" || d === "deny") return d;
          }
          return undefined;
        }

        for (let i = 0; i < history.length; i++) {
          const h = history[i];
          if (h.role === "user") {
            msgs.push({ kind: "user", content: h.content });
          } else if (h.role === "tool_call") {
            const rawContexts = h.contexts ?? h.args?.contexts;
            const isLoading = isToolCallLoading(
              h.tool ?? "",
              h.approval_source,
              h.approval_verdict,
            );
            if (
              isUserApprovedReplay(
                h.tool ?? "",
                h.detail,
                h.approval_source,
                h.approval_verdict,
              )
            ) {
              const patched = applyApprovedApprovalToMessages(
                msgs,
                {
                  tool: h.tool ?? "",
                  args: (h.args ?? {}) as Record<string, unknown>,
                },
                isLoading,
              );
              msgs.length = 0;
              msgs.push(...patched);
              continue;
            }
            msgs.push({
              kind: "tool_call",
              tool: h.tool ?? "",
              args: h.args ?? {},
              detail: h.detail ?? "",
              contexts: Array.isArray(rawContexts)
                ? (rawContexts as string[])
                : undefined,
              approvalSource: h.approval_source,
              approvalVerdict: h.approval_verdict,
              approvalExplanation: h.approval_explanation,
              loading: isLoading,
              toolId: h.tool_id as string | undefined,
              parentToolId: h.parent_tool_id as string | undefined,
            });
            const toolName = h.tool ?? "";
            const idx = msgs.length - 1;
            const queue = pendingToolCallIndices.get(toolName) ?? [];
            queue.push(idx);
            pendingToolCallIndices.set(toolName, queue);
          } else if (h.role === "tool_result") {
            const toolResultId = h.tool_id as string | undefined;
            if (toolResultId) {
              const updated = updateToolResultById(msgs, toolResultId, {
                result: h.result ?? "",
                exitCode: h.exit_code,
              });
              if (updated.found) {
                msgs.length = 0;
                msgs.push(...updated.messages);
                continue;
              }
            }

            const toolName = h.tool ?? "";
            const queue = pendingToolCallIndices.get(toolName);
            const idx = queue?.shift();
            if (idx != null && msgs[idx]?.kind === "tool_call") {
              const toolCall = msgs[idx];
              msgs[idx] = {
                ...toolCall,
                result: h.result,
                exitCode: h.exit_code,
                loading: false,
              };
            }
            if (queue && queue.length === 0) {
              pendingToolCallIndices.delete(toolName);
            }
          } else if (h.role === "approval_response") {
            // Skip — consumed by the approval_request above
          } else if (h.role === "approval_request" && h.tool_call_id) {
            const request = {
              type: "approval_request" as const,
              tool_call_id: h.tool_call_id,
              tool: h.tool ?? "",
              args: (h.args ?? {}) as Record<string, unknown>,
              explanation: h.explanation ?? "",
              risk_level: h.risk_level ?? "",
            };
            const response = history.find(
              (r) =>
                r.role === "approval_response" &&
                r.tool_call_id === h.tool_call_id,
            );
            if (!response) {
              msgs.push({ kind: "approval", request });
            } else if (response.decision === "approved") {
              const patched = applyApprovedApprovalToMessages(msgs, request);
              msgs.length = 0;
              msgs.push(...patched);
            } else if (response.decision === "denied") {
              const patched = applyDeniedApprovalToMessages(
                msgs,
                request,
                response.message,
              );
              msgs.length = 0;
              msgs.push(...patched);
            }
          } else if (
            (h.role === "domain_access_approval" ||
              h.role === "proxy_approval") &&
            h.request_id
          ) {
            // Domain access approval: request entry, then decision (may be non-adjacent)
            if (!h.decision) {
              const decision = findLaterEscalationDecision(
                i,
                h.request_id,
                (role) =>
                  role === "domain_access_approval" ||
                  role === "proxy_approval",
              );
              if (!decision) {
                msgs.push({
                  kind: "domain_access_approval",
                  request: {
                    type: "domain_access_approval_request",
                    request_id: h.request_id,
                    domain: h.domain ?? "",
                    command: h.command ?? "",
                  },
                  decision,
                });
              }
            }
            // Skip decision-only events (consumed above)
          } else if (h.role === "git_push_approval" && h.request_id) {
            // Git push approval: request entry, then decision (may be non-adjacent)
            if (!h.decision) {
              const decision = findLaterEscalationDecision(
                i,
                h.request_id,
                (role) => role === "git_push_approval",
              );
              if (!decision) {
                msgs.push({
                  kind: "git_push_approval",
                  request: {
                    type: "git_push_approval_request",
                    request_id: h.request_id,
                    ref: h.ref ?? "",
                    explanation: h.explanation ?? "",
                    changed_files:
                      (h.changed_files as string[] | undefined) ?? [],
                  },
                  decision,
                });
              }
            }
          } else if (h.role === "credential_approval" && h.request_id) {
            if (!h.decision) {
              const decision = findLaterEscalationDecision(
                i,
                h.request_id,
                (role) => role === "credential_approval",
              );
              if (!decision) {
                msgs.push({
                  kind: "credential_approval",
                  request: {
                    type: "credential_approval_request",
                    request_id: h.request_id,
                    vault_paths: h.vault_paths ?? [],
                    names: h.names ?? [],
                    descriptions: h.descriptions ?? [],
                    skill_name: h.skill_name,
                    explanation: h.explanation ?? "",
                  },
                  decision,
                });
              }
            }
          } else if (h.role === "git_push") {
            msgs.push({
              kind: "tool_call",
              tool: "git_push",
              args: { ref: h.ref ?? "", decision: h.decision ?? "" },
              detail: h.detail ?? "",
              approvalSource: h.approval_source,
              approvalVerdict: h.approval_verdict,
              approvalExplanation: h.approval_explanation,
              toolId: h.tool_id as string | undefined,
              parentToolId: h.parent_tool_id as string | undefined,
            });
          } else if (h.role === "command") {
            msgs.push({
              kind: "command",
              command: h.command ?? "",
              data: h.data,
            });
          } else if (h.role === "thinking" && h.content) {
            msgs.push({
              kind: "thinking",
              content: h.content,
              reasoningDurationMs: h.reasoning_duration_ms,
              reasoningTokens: h.reasoning_tokens,
            });
          } else {
            msgs.push({ kind: "assistant", content: h.content });
          }
        }
        // Group auxiliary tool calls (credential_access, proxy_domain, git_push)
        // under their parent tool call by matching parentToolId → toolId.
        const parentIndex = new Map<string, number>();
        for (let i = 0; i < msgs.length; i++) {
          const m = msgs[i];
          if (m.kind === "tool_call" && m.toolId) {
            parentIndex.set(m.toolId, i);
          }
        }
        const childIndices = new Set<number>();
        for (let i = 0; i < msgs.length; i++) {
          const m = msgs[i];
          if (m.kind !== "tool_call" || !m.parentToolId) continue;
          const pi = parentIndex.get(m.parentToolId);
          if (pi == null) continue;
          const parent = msgs[pi];
          if (parent.kind !== "tool_call") continue;
          if (!parent.children) parent.children = [];
          parent.children.push(m);
          childIndices.add(i);
        }
        const grouped = childIndices.size > 0
          ? msgs.filter((_, i) => !childIndices.has(i))
          : msgs;
        setMessages(grouped);
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
          setMessages((prev) => [
            ...prev,
            { kind: "command", command: msg.command, data: msg.data },
          ]);
          setLlmActivity(null);
          lastThinkingStartedAtRef.current = null;
          finishWaiting();
          break;
        case "error":
          setMessages((prev) => [
            ...prev,
            { kind: "error", detail: msg.detail },
          ]);
          setLlmActivity(null);
          lastThinkingStartedAtRef.current = null;
          finishWaiting();
          break;
        case "cancelled":
          setMessages((prev) => [
            ...prev,
            { kind: "error", detail: msg.detail },
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
    queueRef.current = content;
    setQueuedMessage(content);
    send({ type: "cancel" });
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

  async function handleCommitKnowledge() {
    if (!session || session.private || waiting || savingKnowledge || deletingSession) return;

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
    if (!session || togglingPrivacy || deletingSession) return;

    const nextPrivate = !session.private;
    if (
      nextPrivate
      && session.knowledge_last_committed_at
      && !window.confirm("Mark this session private? Existing knowledge commits will remain in git history.")
    ) {
      return;
    }

    setTogglingPrivacy(true);
    setKnowledgeNotice(null);
    try {
      const updated = await updateSession(server, token, sessionId, { private: nextPrivate });
      onSessionUpdate?.(updated);
      setKnowledgeNotice({
        tone: "neutral",
        message: nextPrivate
          ? updated.knowledge_last_committed_at
            ? "Session is private. Existing knowledge commits remain unchanged."
            : "Session is private and will not be committed to knowledge."
          : "Session is public and eligible for knowledge commits.",
      });
    } catch (error) {
      setKnowledgeNotice({ tone: "error", message: errorDetail(error) });
    } finally {
      setTogglingPrivacy(false);
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
  const canCommitKnowledge = !!session && !session.private && hasKnowledgeContent && hasKnowledgeChanges;
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

      <div className="border-b border-border px-4 py-3">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="text-xs font-medium uppercase tracking-[0.12em] text-muted-foreground">
              Sandbox
            </div>
            <div className="mt-1 flex items-center gap-2 text-sm font-medium text-foreground">
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
              <span>{sandboxLoading ? "Refreshing…" : sandbox ? sandboxStatusLabel(sandbox.status) : "Checking sandbox…"}</span>
            </div>
            <div className="mt-1 text-xs text-muted-foreground">
              {sandboxStorageLabel(sandbox)}
            </div>
            <div className="mt-3 text-xs font-medium uppercase tracking-[0.12em] text-muted-foreground">
              Knowledge
            </div>
            <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              <span
                className={cn(
                  "rounded-full border px-2 py-0.5 font-medium uppercase tracking-[0.08em]",
                  session?.private
                    ? "border-zinc-300 bg-zinc-100 text-zinc-700"
                    : "border-emerald-300 bg-emerald-50 text-emerald-700",
                )}
              >
                {session?.private ? "private" : "public"}
              </span>
              <span>{archiveStatusLabel}</span>
            </div>
            {session?.knowledge_last_archive_path ? (
              <div
                className="mt-1 max-w-full truncate text-xs font-mono text-muted-foreground"
                title={session.knowledge_last_archive_path}
              >
                {session.knowledge_last_archive_path}
              </div>
            ) : null}
            {knowledgeNotice ? (
              <div
                className={cn(
                  "mt-1 text-xs",
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
          <div className="flex shrink-0 flex-wrap items-center justify-end gap-2">
            <button
              onClick={() => void handleCommitKnowledge()}
              disabled={archiveButtonDisabled}
              title={commitButtonTitle}
              className="rounded-md border border-emerald-300 bg-emerald-50 px-3 py-1.5 text-xs font-medium text-emerald-900 transition-colors hover:bg-emerald-100 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <span className="inline-flex items-center gap-1.5">
                {savingKnowledge ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
                Commit
              </span>
            </button>
            <button
              onClick={() => void handleTogglePrivacy()}
              disabled={!session || togglingPrivacy || deletingSession}
              className="rounded-md border border-zinc-300 bg-zinc-50 px-3 py-1.5 text-xs font-medium text-zinc-900 transition-colors hover:bg-zinc-100 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <span className="inline-flex items-center gap-1.5">
                {togglingPrivacy ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : session?.private ? (
                  <Unlock className="h-3.5 w-3.5" />
                ) : (
                  <Lock className="h-3.5 w-3.5" />
                )}
                {session?.private ? "Make public" : "Make private"}
              </span>
            </button>
            <button
              onClick={() => void handleSandboxPowerAction()}
              disabled={sandboxActionDisabled}
              className="rounded-md border border-sky-300 bg-sky-50 px-3 py-1.5 text-xs font-medium text-sky-900 transition-colors hover:bg-sky-100 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <span className="inline-flex items-center gap-1.5">
                {sandboxPowerAction ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
                {sandboxPowerButtonLabel}
              </span>
            </button>
            <button
              onClick={() => void handleWipeSandbox()}
              disabled={waiting || !!sandboxPowerAction || wipingSandbox || deletingSession}
              className="rounded-md border border-amber-300 bg-amber-50 px-3 py-1.5 text-xs font-medium text-amber-900 transition-colors hover:bg-amber-100 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {wipingSandbox ? (
                <span className="inline-flex items-center gap-1.5">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  Reset sandbox
                </span>
              ) : (
                <span className="inline-flex items-center gap-1.5">
                  <RotateCcw className="h-3.5 w-3.5" />
                  Reset sandbox
                </span>
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
              <p className="text-lg font-medium text-foreground/80">Carapace</p>
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
              onApproval={handleApproval}
              onEscalation={handleEscalation}
              onCredentialApproval={handleCredentialEscalation}
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
        waiting={waiting}
        queuedMessage={queuedMessage}
        commands={commands}
        availableModelEntries={availableModelEntries}
        usage={usage}
      />
    </div>
  );
}
