"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2 } from "lucide-react";
import { useWebSocket } from "@/hooks/use-websocket";
import {
  type AvailableModelInfo,
  fetchCommands,
  fetchHistory,
  fetchModels,
  type SlashCommand,
  wsUrl,
} from "@/lib/api";
import type {
  ChatMessage,
  ClientMessage,
  EscalationDecision,
  ServerMessage,
  TurnUsage,
} from "@/lib/types";
import { Message } from "./message";
import { ChatInput } from "./chat-input";

interface ChatViewProps {
  server: string;
  token: string;
  sessionId: string;
  onTitleUpdate?: (title: string) => void;
}

export function ChatView({
  server,
  token,
  sessionId,
  onTitleUpdate,
}: ChatViewProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [waiting, setWaiting] = useState(false);
  const [queuedMessage, setQueuedMessage] = useState<string | null>(null);
  const [usage, setUsage] = useState<TurnUsage | null>(null);
  const [loadingHistory, setLoadingHistory] = useState(true);
  const [commands, setCommands] = useState<SlashCommand[]>([]);
  const [availableModelEntries, setAvailableModelEntries] = useState<
    AvailableModelInfo[]
  >([]);
  const [approvalState, setApprovalState] = useState<Map<string, boolean>>(
    new Map(),
  );
  const bottomRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const isAtBottomRef = useRef(true);
  const queueRef = useRef<string | null>(null);
  const sendRef = useRef<(msg: ClientMessage) => void>(() => {});

  // Fetch available slash commands and models on mount
  useEffect(() => {
    fetchCommands(server, token).then(setCommands);
    fetchModels(server, token).then(setAvailableModelEntries);
  }, [server, token]);

  // Load history on mount
  useEffect(() => {
    let cancelled = false;

    fetchHistory(server, token, sessionId)
      .then((history) => {
        if (cancelled) return;
        const msgs: ChatMessage[] = [];
        const pendingToolCallIndices = new Map<string, number[]>();
        const approvals = new Map<string, boolean>();

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
            });
            const toolName = h.tool ?? "";
            const idx = msgs.length - 1;
            const queue = pendingToolCallIndices.get(toolName) ?? [];
            queue.push(idx);
            pendingToolCallIndices.set(toolName, queue);
          } else if (h.role === "tool_result") {
            const toolName = h.tool ?? "";
            const queue = pendingToolCallIndices.get(toolName);
            const idx = queue?.shift();
            if (idx != null && msgs[idx]?.kind === "tool_call") {
              const toolCall = msgs[idx];
              msgs[idx] = {
                ...toolCall,
                result: h.result,
                exitCode: h.exit_code,
              };
            }
            if (queue && queue.length === 0) {
              pendingToolCallIndices.delete(toolName);
            }
          } else if (h.role === "approval_response") {
            // Skip — consumed by the approval_request above
          } else if (h.role === "approval_request" && h.tool_call_id) {
            // Look ahead for a matching approval_response
            const response = history.find(
              (r) =>
                r.role === "approval_response" &&
                r.tool_call_id === h.tool_call_id,
            );
            if (response) {
              approvals.set(h.tool_call_id, response.decision === "approved");
            }
            msgs.push({
              kind: "approval",
              request: {
                type: "approval_request",
                tool_call_id: h.tool_call_id,
                tool: h.tool ?? "",
                args: (h.args ?? {}) as Record<string, unknown>,
                explanation: h.explanation ?? "",
                risk_level: h.risk_level ?? "",
              },
            });
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
            });
          } else if (h.role === "command") {
            msgs.push({
              kind: "command",
              command: h.command ?? "",
              data: h.data,
            });
          } else if (h.role === "thinking" && h.content) {
            msgs.push({ kind: "thinking", content: h.content });
          } else {
            msgs.push({ kind: "assistant", content: h.content });
          }
        }
        setMessages(msgs);
        setApprovalState(approvals);
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
      // stay in waiting state
    } else {
      setWaiting(false);
    }
  }, [clearToolLoading]);

  const onMessage = useCallback(
    (msg: ServerMessage) => {
      switch (msg.type) {
        case "done":
          setMessages((prev) => {
            const updated = [...prev];
            // Finalize thinking: update thinking_streaming or existing thinking with authoritative content
            const thinkStreamIdx = updated.findIndex((m) => m.kind === "thinking_streaming");
            if (thinkStreamIdx !== -1) {
              updated[thinkStreamIdx] = {
                kind: "thinking",
                content: msg.thinking ?? (updated[thinkStreamIdx] as { content: string }).content,
              };
            } else if (msg.thinking) {
              // Update already-finalized thinking with authoritative content, or insert if missing
              const thinkIdx = updated.findLastIndex((m) => m.kind === "thinking");
              if (thinkIdx !== -1) {
                updated[thinkIdx] = { kind: "thinking", content: msg.thinking };
              } else {
                updated.push({ kind: "thinking", content: msg.thinking });
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
          finishWaiting();
          break;
        case "tool_call": {
          const isGitPush = msg.tool === "git_push";
          if (!isGitPush) setWaiting(true); // agent is active (may restore after reconnect)
          const verdict = msg.approval_verdict;
          const isLoading =
            msg.tool !== "proxy_domain" &&
            msg.tool !== "credential_access" &&
            !isGitPush &&
            verdict === "allow";
          const rawContexts = msg.contexts ?? msg.args?.contexts;
          setMessages((prev) => [
            ...prev,
            {
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
            },
          ]);
          if (isGitPush) finishWaiting();
          break;
        }
        case "tool_result":
          setWaiting(true);
          setMessages((prev) => {
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
          finishWaiting();
          break;
        case "error":
          setMessages((prev) => [
            ...prev,
            { kind: "error", detail: msg.detail },
          ]);
          finishWaiting();
          break;
        case "cancelled":
          setMessages((prev) => [
            ...prev,
            { kind: "error", detail: msg.detail },
          ]);
          finishWaiting();
          break;
        case "session_title":
          onTitleUpdate?.(msg.title);
          break;
        case "status":
          if (msg.agent_running) setWaiting(true);
          if (msg.usage) setUsage(msg.usage);
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
            const updated = [...prev];
            // Finalize any open thinking_streaming → thinking when text tokens arrive
            const thinkIdx = updated.findIndex((m) => m.kind === "thinking_streaming");
            if (thinkIdx !== -1) {
              updated[thinkIdx] = {
                kind: "thinking",
                content: (updated[thinkIdx] as { content: string }).content,
              };
            }
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
              };
              return [
                ...prev.slice(0, -1),
                { kind: "thinking_streaming", content: last.content + msg.content },
              ];
            }
            return [...prev, { kind: "thinking_streaming", content: msg.content }];
          });
          break;
      }
    },
    [finishWaiting, onTitleUpdate],
  );

  const onWsDisconnect = useCallback(() => {
    queueRef.current = null;
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
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
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
      send({ type: "message", content });
      setWaiting(true);
    }
  }

  function handleInterrupt(content: string) {
    queueRef.current = content;
    setQueuedMessage(content);
    send({ type: "cancel" });
  }

  function handleApproval(toolCallId: string, approved: boolean) {
    setApprovalState((prev) => new Map(prev).set(toolCallId, approved));
    send({ type: "approval_response", tool_call_id: toolCallId, approved });
    // Force re-render to show resolved state
    setMessages((prev) => [...prev]);
  }

  function handleEscalation(requestId: string, decision: EscalationDecision) {
    send({ type: "escalation_response", request_id: requestId, decision });
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
  ) {
    send({ type: "escalation_response", request_id: requestId, decision });
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

  return (
    <div className="flex flex-1 min-h-0 flex-col">
      {/* Status bar */}
      {status !== "connected" && (
        <div className="flex items-center gap-2 border-b border-border px-4 py-2 text-xs text-muted-foreground">
          <span
            className={`h-1.5 w-1.5 rounded-full ${status === "connecting" ? "bg-warning animate-pulse" : "bg-destructive"}`}
          />
          {status === "connecting" ? "Connecting…" : "Disconnected"}
        </div>
      )}

      {/* Messages */}
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto px-4 py-4"
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
              onApproval={handleApproval}
              approvalResolved={
                msg.kind === "approval"
                  ? approvalState.get(msg.request.tool_call_id)
                  : undefined
              }
              onEscalation={handleEscalation}
              onCredentialApproval={handleCredentialEscalation}
            />
          ))}
          {waiting && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              <span>Working…</span>
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
